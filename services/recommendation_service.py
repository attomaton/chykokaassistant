"""Validates and renders AI product recommendations.

The language model is never trusted with the catalog. It proposes
`product_id` values and culinary reasoning; everything factual - which
products exist, what they cost, whether stock is confirmed - is resolved
here from `CatalogService`. Invented IDs are dropped, invented prices cause
the answer to be rejected rather than shown, and budget totals are computed
on the backend.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bot.locales import t
from services.catalog_service import BudgetResult, CatalogService, Product

logger = logging.getLogger(__name__)

# "500 грн", "500₴", "500 uah" - used both to read a customer's budget and to
# detect a price the model stated on its own.
_MONEY_RE = re.compile(r"(\d[\d\s]{0,8}(?:[.,]\d{1,2})?)\s*(?:₴|грн|гривень|грн\.|uah)", re.IGNORECASE)
_BUDGET_RE = re.compile(
    r"(?:до|за|на|бюджет[а-яіїєґ]*|у межах|в межах)\s*(\d[\d\s]{0,8})\s*(?:₴|грн|гривень|uah)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RecommendationOutcome:
    """Result of validating a model recommendation.

    `text` is None when nothing survived validation - the caller must then
    escalate or ask a clarifying question rather than showing anything.
    """

    text: str | None
    products: tuple[Product, ...]
    rejected_product_ids: tuple[str, ...]
    external_suggestions: tuple[str, ...]
    budget: BudgetResult | None
    should_escalate: bool
    escalation_reason: str = ""


def parse_budget(text: str) -> float | None:
    """Read a budget figure out of a customer message, if one is stated."""
    match = _BUDGET_RE.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(" ", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _stated_amounts(text: str) -> set[float]:
    amounts: set[float] = set()
    for raw in _MONEY_RE.findall(text):
        try:
            amounts.add(float(raw.replace(" ", "").replace(",", ".")))
        except ValueError:
            continue
    return amounts


def contains_unconfirmed_price(text: str, catalog: CatalogService, budget: float | None = None) -> bool:
    """True if the text states a money amount the catalog does not confirm.

    A safety net behind the system prompt: the model is told not to quote
    prices, and if it does so anyway we refuse to forward the answer instead
    of relaying a possibly invented number.
    """
    confirmed = {
        product.price_uah for product in catalog.products.values() if product.price_uah is not None
    }
    if budget is not None:
        confirmed.add(budget)  # echoing the customer's own budget is fine
    return any(amount not in confirmed for amount in _stated_amounts(text))


def _format_product_line(product: Product) -> str:
    if product.has_confirmed_price:
        return f"— {product.name} — {product.price_uah:g} ₴"
    return f"— {product.name}"


def build_recommendation(
    *,
    answer: str,
    recommended_product_ids: list[str],
    external_suggestions: list[str],
    catalog: CatalogService,
    budget: float | None = None,
) -> RecommendationOutcome:
    """Turn a model recommendation into a safe, catalog-grounded message."""
    products, rejected = catalog.validate_ids(recommended_product_ids)

    if not products:
        # Every product the model proposed was invented, or it proposed none.
        # Never paper over this - hand control back to the escalation flow.
        return RecommendationOutcome(
            text=None,
            products=(),
            rejected_product_ids=tuple(rejected),
            external_suggestions=tuple(external_suggestions),
            budget=None,
            should_escalate=True,
            escalation_reason="No recommended product survived catalog validation",
        )

    if contains_unconfirmed_price(answer, catalog, budget):
        logger.warning("recommendation_rejected_unconfirmed_price")
        return RecommendationOutcome(
            text=None,
            products=tuple(products),
            rejected_product_ids=tuple(rejected),
            external_suggestions=tuple(external_suggestions),
            budget=None,
            should_escalate=True,
            escalation_reason="Model stated a price not confirmed by the catalog",
        )

    budget_result: BudgetResult | None = None
    shown = products
    if budget is not None:
        budget_result = catalog.build_budget([p.product_id for p in products], budget=budget)
        shown = tuple(line.product for line in budget_result.lines)
        if not shown:
            # Nothing priced fits (or nothing has a confirmed price at all):
            # say so honestly instead of inventing a total.
            return RecommendationOutcome(
                text=f"{answer.strip()}\n\n{t('budget_no_prices')}",
                products=(),
                rejected_product_ids=tuple(rejected),
                external_suggestions=tuple(external_suggestions),
                budget=budget_result,
                should_escalate=False,
            )

    parts = [answer.strip()]
    parts.append("\n".join(_format_product_line(product) for product in shown))

    if budget_result is not None:
        parts.append(t("budget_summary", total=f"{budget_result.total:g}", budget=f"{budget:g}"))
        if budget_result.dropped_unpriced_ids:
            parts.append(t("recommendation_price_unknown"))
    elif any(not product.has_confirmed_price for product in shown):
        parts.append(t("recommendation_price_unknown"))

    external = [item.strip() for item in external_suggestions if item and item.strip()]
    if external:
        parts.append(t("recommendation_external_note", items=", ".join(external)))

    return RecommendationOutcome(
        text="\n\n".join(parts),
        products=tuple(shown),
        rejected_product_ids=tuple(rejected),
        external_suggestions=tuple(external),
        budget=budget_result,
        should_escalate=False,
    )
