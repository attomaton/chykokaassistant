"""Recommendation validation: the backend, not the model, is the authority."""
from __future__ import annotations

from bot.locales import t
from services.catalog_service import CatalogService
from services.recommendation_service import (
    build_recommendation,
    contains_unconfirmed_price,
    parse_budget,
)

SAMPLE = """
## Structured Product Catalog

| product_id | Назва | Ціна | Наявність | Категорія | Теги |
|---|---|---|---|---|---|
| dried_persimmon | Хурма | 340 | невідомо | Сухофрукти | сухофрукт |
| walnut | Волоський горіх | 150 | в наявності | Горіхи | горіх |
| roasted_almond | Мигдаль смажений | невідомо | невідомо | Горіхи | горіх |
"""

CATALOG = CatalogService(SAMPLE)


def test_recommendation_uses_general_culinary_knowledge():
    """Pairing advice is allowed even though the KB documents no pairings."""
    outcome = build_recommendation(
        answer="До хурми добре пасують волоські горіхи — вони додають хрусткої текстури.",
        recommended_product_ids=["walnut"],
        external_suggestions=[],
        catalog=CATALOG,
    )
    assert outcome.should_escalate is False
    assert "хрусткої текстури" in outcome.text
    assert [p.product_id for p in outcome.products] == ["walnut"]


def test_invented_product_is_dropped_from_recommendation():
    outcome = build_recommendation(
        answer="Раджу спробувати ці поєднання.",
        recommended_product_ids=["walnut", "chocolate_truffle_deluxe"],
        external_suggestions=[],
        catalog=CATALOG,
    )
    assert "chocolate_truffle_deluxe" in outcome.rejected_product_ids
    assert [p.product_id for p in outcome.products] == ["walnut"]
    assert "chocolate_truffle_deluxe" not in outcome.text


def test_recommendation_with_only_invented_products_escalates():
    """If nothing survives validation we must not improvise a reply."""
    outcome = build_recommendation(
        answer="Ось наші чудові товари!",
        recommended_product_ids=["unicorn_jam", "dragon_fruit_cake"],
        external_suggestions=[],
        catalog=CATALOG,
    )
    assert outcome.should_escalate is True
    assert outcome.text is None


def test_empty_recommendation_escalates():
    outcome = build_recommendation(
        answer="",
        recommended_product_ids=[],
        external_suggestions=[],
        catalog=CATALOG,
    )
    assert outcome.should_escalate is True
    assert outcome.text is None


def test_model_invented_price_is_rejected_not_relayed():
    """A price the catalog does not confirm must never reach the customer."""
    outcome = build_recommendation(
        answer="Волоський горіх коштує 99 грн — чудова пропозиція!",
        recommended_product_ids=["walnut"],
        external_suggestions=[],
        catalog=CATALOG,
    )
    assert outcome.should_escalate is True
    assert outcome.text is None
    assert "price" in outcome.escalation_reason.lower()


def test_confirmed_price_in_answer_is_allowed():
    outcome = build_recommendation(
        answer="Волоський горіх — 150 ₴.",
        recommended_product_ids=["walnut"],
        external_suggestions=[],
        catalog=CATALOG,
    )
    assert outcome.should_escalate is False


def test_price_shown_comes_from_the_catalog():
    outcome = build_recommendation(
        answer="Раджу горіхи.",
        recommended_product_ids=["walnut"],
        external_suggestions=[],
        catalog=CATALOG,
    )
    assert "150 ₴" in outcome.text


def test_product_without_confirmed_price_shows_no_price():
    outcome = build_recommendation(
        answer="Раджу мигдаль.",
        recommended_product_ids=["roasted_almond"],
        external_suggestions=[],
        catalog=CATALOG,
    )
    assert "Мигдаль смажений" in outcome.text
    assert "₴" not in outcome.text.split("Мигдаль смажений")[1].split("\n")[0]
    assert t("recommendation_price_unknown") in outcome.text


def test_external_suggestion_is_marked_as_outside_the_catalog():
    outcome = build_recommendation(
        answer="До інжиру добре пасують мʼякі сири.",
        recommended_product_ids=["walnut"],
        external_suggestions=["мʼякі сири"],
        catalog=CATALOG,
    )
    assert "мʼякі сири" in outcome.text
    assert "У каталозі Lakomka Store таких позицій немає" in outcome.text


def test_external_suggestion_never_becomes_a_catalog_product():
    outcome = build_recommendation(
        answer="Спробуйте з сиром.",
        recommended_product_ids=["walnut"],
        external_suggestions=["сир"],
        catalog=CATALOG,
    )
    assert [p.product_id for p in outcome.products] == ["walnut"]
    assert all("сир" not in p.name.lower() for p in outcome.products)


def test_budget_total_is_calculated_by_the_backend():
    outcome = build_recommendation(
        answer="Ось набір.",
        recommended_product_ids=["walnut", "dried_persimmon"],
        external_suggestions=[],
        catalog=CATALOG,
        budget=600,
    )
    assert outcome.budget.total == 490
    assert t("budget_summary", total="490", budget="600") in outcome.text


def test_budget_excludes_products_over_the_limit():
    outcome = build_recommendation(
        answer="Ось набір.",
        recommended_product_ids=["dried_persimmon", "walnut"],
        external_suggestions=[],
        catalog=CATALOG,
        budget=400,
    )
    assert outcome.budget.total == 340
    assert "Волоський горіх" not in outcome.text


def test_missing_prices_produce_no_fabricated_total():
    outcome = build_recommendation(
        answer="Ось набір.",
        recommended_product_ids=["roasted_almond"],
        external_suggestions=[],
        catalog=CATALOG,
        budget=500,
    )
    assert outcome.budget.total == 0
    assert t("budget_no_prices") in outcome.text
    assert outcome.products == ()


def test_parse_budget_reads_customer_stated_limit():
    assert parse_budget("Склади подарунковий набір до 1000 грн") == 1000
    assert parse_budget("Що можна взяти на 300 ₴?") == 300
    assert parse_budget("Що краще взяти до хурми?") is None


def test_contains_unconfirmed_price_allows_echoing_the_budget():
    assert contains_unconfirmed_price("Набір до 500 грн", CATALOG, budget=500) is False
    assert contains_unconfirmed_price("Набір до 500 грн", CATALOG, budget=None) is True


def test_contains_unconfirmed_price_ignores_text_without_money():
    assert contains_unconfirmed_price("До хурми пасують горіхи.", CATALOG) is False
