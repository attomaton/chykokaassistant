"""Structured-output schema: the `recommend` status and field validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.openai_service import SYSTEM_PROMPT_TEMPLATE, AIResult


def test_recommend_status_is_accepted():
    result = AIResult(
        status="recommend",
        answer="До хурми пасують горіхи.",
        confidence=0.9,
        response_type="general_recommendation",
        recommended_product_ids=["walnut"],
        pairing_explanations=["Хрустка текстура врівноважує мʼяку хурму."],
    )
    assert result.status == "recommend"
    assert result.recommended_product_ids == ["walnut"]


def test_all_four_statuses_are_valid():
    for status in ("answered", "needs_clarification", "recommend", "escalate"):
        assert AIResult(status=status, answer="x", confidence=0.5).status == status


def test_invalid_status_is_rejected():
    with pytest.raises(ValidationError):
        AIResult(status="make_something_up", answer="x", confidence=0.5)


def test_invalid_response_type_is_rejected():
    with pytest.raises(ValidationError):
        AIResult(status="recommend", answer="x", confidence=0.5, response_type="whatever")


def test_missing_required_fields_are_rejected():
    with pytest.raises(ValidationError):
        AIResult(status="answered")
    with pytest.raises(ValidationError):
        AIResult(answer="x", confidence=0.5)


def test_confidence_must_be_a_probability():
    with pytest.raises(ValidationError):
        AIResult(status="answered", answer="x", confidence=1.5)
    with pytest.raises(ValidationError):
        AIResult(status="answered", answer="x", confidence=-0.1)


def test_recommendation_fields_default_to_empty():
    result = AIResult(status="answered", answer="x", confidence=0.9)
    assert result.recommended_product_ids == []
    assert result.external_suggestions == []
    assert result.used_business_facts == []
    assert result.used_general_knowledge == []
    assert result.response_type == "business_fact"


def test_system_prompt_requires_ukrainian_and_two_sources():
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        business_knowledge="KB", catalog_block="walnut | Горіх | 150 ₴"
    )
    assert "Ukrainian" in prompt
    assert "Never write a customer-facing\nanswer in English." in prompt
    assert "CATEGORY A - BUSINESS FACTS" in prompt
    assert "CATEGORY B - GENERAL RECOMMENDATIONS" in prompt
    # The confirmed catalog must actually be injected.
    assert "walnut | Горіх | 150 ₴" in prompt


def test_system_prompt_forbids_medical_claims_and_invented_facts():
    prompt = SYSTEM_PROMPT_TEMPLATE.format(business_knowledge="KB", catalog_block="")
    assert "Never give medical advice" in prompt
    assert "NEVER invent, guess, estimate, or extrapolate" in prompt
    assert "do NOT calculate any totals yourself" in prompt
