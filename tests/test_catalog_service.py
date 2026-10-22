"""Catalog parsing and the backend price/availability authority."""
from __future__ import annotations

from pathlib import Path

from services.catalog_service import CatalogService, parse_catalog

SAMPLE = """
# Store

## Structured Product Catalog

| product_id | Назва | Ціна | Наявність | Категорія | Теги |
|---|---|---|---|---|---|
| dried_persimmon | Хурма | 340 | невідомо | Сухофрукти | сухофрукт, мʼяке |
| walnut | Волоський горіх | 150 | в наявності | Горіхи | горіх, хрустке |
| royal_dates | Фінік | невідомо | невідомо | Сухофрукти | сухофрукт |

## Next Section

| not | a | product | row |
"""


def test_parses_products_with_ids_prices_and_stock():
    products = parse_catalog(SAMPLE)
    assert set(products) == {"dried_persimmon", "walnut", "royal_dates"}
    assert products["dried_persimmon"].price_uah == 340
    assert products["walnut"].in_stock is True
    assert products["walnut"].tags == ("горіх", "хрустке")


def test_unconfirmed_price_is_none_not_guessed():
    products = parse_catalog(SAMPLE)
    assert products["royal_dates"].price_uah is None
    assert products["royal_dates"].has_confirmed_price is False


def test_unconfirmed_stock_is_none_not_false():
    """`невідомо` must stay unknown - it must never render as "in stock"."""
    products = parse_catalog(SAMPLE)
    assert products["dried_persimmon"].in_stock is None


def test_parsing_stops_at_the_next_heading():
    products = parse_catalog(SAMPLE)
    assert "not" not in products


def test_missing_catalog_section_yields_empty_catalog():
    assert parse_catalog("# Store\n\nNo catalog here.") == {}


def test_validate_ids_rejects_unknown_products():
    catalog = CatalogService(SAMPLE)
    confirmed, rejected = catalog.validate_ids(["walnut", "unicorn_jam", "dried_persimmon"])
    assert [p.product_id for p in confirmed] == ["walnut", "dried_persimmon"]
    assert rejected == ["unicorn_jam"]


def test_validate_ids_collapses_duplicates_and_blanks():
    catalog = CatalogService(SAMPLE)
    confirmed, rejected = catalog.validate_ids(["walnut", "walnut", "", "  "])
    assert [p.product_id for p in confirmed] == ["walnut"]
    assert rejected == []


def test_budget_uses_catalog_prices_not_supplied_ones():
    catalog = CatalogService(SAMPLE)
    result = catalog.build_budget(["dried_persimmon", "walnut"], budget=1000)
    assert result.total == 490  # 340 + 150, straight from the catalog
    assert result.within_budget is True


def test_budget_drops_products_without_a_confirmed_price():
    catalog = CatalogService(SAMPLE)
    result = catalog.build_budget(["dried_persimmon", "royal_dates"], budget=1000)
    assert result.dropped_unpriced_ids == ("royal_dates",)
    assert result.total == 340  # the unpriced item contributes nothing


def test_budget_drops_products_that_would_exceed_it():
    catalog = CatalogService(SAMPLE)
    result = catalog.build_budget(["dried_persimmon", "walnut"], budget=400)
    assert result.total == 340
    assert result.dropped_over_budget_ids == ("walnut",)
    assert result.within_budget is True


def test_budget_ignores_invented_products_entirely():
    catalog = CatalogService(SAMPLE)
    result = catalog.build_budget(["walnut", "imaginary_truffle"], budget=1000)
    assert [line.product.product_id for line in result.lines] == ["walnut"]
    assert result.total == 150


def test_real_business_md_catalog_parses():
    """The shipped knowledge base must expose a usable catalog."""
    content = Path("data/business.md").read_text(encoding="utf-8")
    catalog = CatalogService(content)
    assert len(catalog) > 10
    assert catalog.exists("dried_persimmon")
    assert catalog.get("dried_figs").price_uah == 520
    # Ambiguous public pricing must stay unconfirmed.
    assert catalog.get("royal_dates").has_confirmed_price is False


def test_prompt_block_never_claims_unconfirmed_stock_or_price():
    catalog = CatalogService(SAMPLE)
    block = catalog.catalog_prompt_block()
    assert "royal_dates" in block
    assert "ціна не підтверджена" in block
    assert "наявність не підтверджена" in block
