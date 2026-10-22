"""Parses the machine-readable product catalog out of the knowledge base.

This exists so product recommendations can be validated *programmatically*
rather than trusted from the model. The language model is only ever allowed
to return `product_id` values; this module is the authority on which IDs
exist, what they cost, and whether stock is confirmed. Any ID the model
invents is dropped before the customer sees anything, and prices/availability
shown to the customer always come from here - never from model output.

The catalog lives inside `data/business.md` (see the "Structured Product
Catalog" section) so the knowledge base stays the single source of truth.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

CATALOG_HEADING = "Structured Product Catalog"
UNKNOWN_MARKERS = {"невідомо", "unknown", "n/a", "-", "—", ""}
IN_STOCK_MARKER = "в наявності"

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$")
_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|$")


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    price_uah: float | None
    in_stock: bool | None
    category: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_confirmed_price(self) -> bool:
        return self.price_uah is not None


@dataclass(frozen=True)
class BudgetLine:
    product: Product
    quantity: int

    @property
    def subtotal(self) -> float:
        # Only ever constructed for products with a confirmed price.
        assert self.product.price_uah is not None
        return self.product.price_uah * self.quantity


@dataclass(frozen=True)
class BudgetResult:
    lines: tuple[BudgetLine, ...]
    total: float
    budget: float | None
    dropped_unpriced_ids: tuple[str, ...]
    dropped_over_budget_ids: tuple[str, ...]

    @property
    def within_budget(self) -> bool:
        return self.budget is None or self.total <= self.budget


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_price(raw: str) -> float | None:
    cleaned = raw.strip().lower()
    if cleaned in UNKNOWN_MARKERS:
        return None
    # Tolerate a trailing currency symbol and decimal commas.
    cleaned = cleaned.replace("₴", "").replace("грн", "").replace(",", ".").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_stock(raw: str) -> bool | None:
    cleaned = raw.strip().lower()
    if cleaned in UNKNOWN_MARKERS:
        return None
    return IN_STOCK_MARKER in cleaned


def parse_catalog(markdown: str) -> dict[str, Product]:
    """Extract products from the "Structured Product Catalog" table.

    Returns an empty mapping when the section or its table is absent, so a
    knowledge base without a structured catalog simply disables product
    recommendations rather than breaking plain Q&A.
    """
    lines = markdown.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match and match.group(1).strip() == CATALOG_HEADING:
            start = index + 1
            break
    if start is None:
        return {}

    products: dict[str, Product] = {}
    header_seen = False
    for line in lines[start:]:
        if _HEADING_RE.match(line):
            break  # next section: the catalog table is over
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if _SEPARATOR_RE.match(stripped):
            continue
        cells = _split_row(stripped)
        if len(cells) < 4:
            continue
        if not header_seen:
            # First table row under the heading is the column header.
            header_seen = True
            if cells[0].lower() == "product_id":
                continue
        product_id = cells[0]
        if not product_id or " " in product_id:
            continue
        tags = tuple(
            tag.strip().lower() for tag in cells[5].split(",") if tag.strip()
        ) if len(cells) > 5 else ()
        products[product_id] = Product(
            product_id=product_id,
            name=cells[1],
            price_uah=_parse_price(cells[2]),
            in_stock=_parse_stock(cells[3]),
            category=cells[4] if len(cells) > 4 else "",
            tags=tags,
        )
    return products


class CatalogService:
    """Read-only view over the products confirmed by the knowledge base."""

    def __init__(self, markdown: str) -> None:
        self._products = parse_catalog(markdown)

    @property
    def products(self) -> dict[str, Product]:
        return dict(self._products)

    def __len__(self) -> int:
        return len(self._products)

    def exists(self, product_id: str) -> bool:
        return product_id in self._products

    def get(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    def validate_ids(self, product_ids: list[str]) -> tuple[list[Product], list[str]]:
        """Split model-supplied IDs into confirmed products and rejects.

        Order is preserved and duplicates collapsed. Anything not present in
        the catalog is returned as a reject so the caller can log it and drop
        it - a hallucinated product must never reach the customer.
        """
        confirmed: list[Product] = []
        rejected: list[str] = []
        seen: set[str] = set()
        for raw in product_ids:
            product_id = (raw or "").strip()
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            product = self._products.get(product_id)
            if product is None:
                rejected.append(product_id)
            else:
                confirmed.append(product)
        if rejected:
            logger.warning("catalog_rejected_unknown_product_ids ids=%s", rejected)
        return confirmed, rejected

    def build_budget(
        self,
        product_ids: list[str],
        budget: float | None = None,
        quantities: dict[str, int] | None = None,
    ) -> BudgetResult:
        """Cost a set of products using catalog prices only.

        Products without a confirmed price are dropped rather than estimated,
        and products that would push the running total past `budget` are
        dropped too. The model never gets to do this arithmetic.
        """
        quantities = quantities or {}
        confirmed, _ = self.validate_ids(product_ids)

        lines: list[BudgetLine] = []
        dropped_unpriced: list[str] = []
        dropped_over: list[str] = []
        total = 0.0

        for product in confirmed:
            if not product.has_confirmed_price:
                dropped_unpriced.append(product.product_id)
                continue
            quantity = max(1, int(quantities.get(product.product_id, 1)))
            line = BudgetLine(product=product, quantity=quantity)
            if budget is not None and total + line.subtotal > budget:
                dropped_over.append(product.product_id)
                continue
            lines.append(line)
            total += line.subtotal

        return BudgetResult(
            lines=tuple(lines),
            total=total,
            budget=budget,
            dropped_unpriced_ids=tuple(dropped_unpriced),
            dropped_over_budget_ids=tuple(dropped_over),
        )

    def catalog_prompt_block(self) -> str:
        """Render the catalog for the model prompt, IDs first.

        Deliberately states unknown price/stock as unknown rather than
        omitting the column, so the model is never nudged into filling a gap.
        """
        if not self._products:
            return "(каталог порожній)"
        rows = []
        for product in self._products.values():
            price = f"{product.price_uah:g} ₴" if product.has_confirmed_price else "ціна не підтверджена"
            if product.in_stock is True:
                stock = "в наявності"
            elif product.in_stock is False:
                stock = "немає в наявності"
            else:
                stock = "наявність не підтверджена"
            tags = ", ".join(product.tags) if product.tags else "—"
            rows.append(
                f"- {product.product_id} | {product.name} | {price} | {stock} | {product.category} | {tags}"
            )
        return "\n".join(rows)
