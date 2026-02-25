"""
Deterministic pricing engine — pure Python, no LLM.

Rules in config/pricing_rules.yaml are evaluated top-to-bottom.
First match wins. LLM never receives a compute request.
The LLM only receives the PricingOutput and writes a human-readable explanation.
"""
from __future__ import annotations

import logging

from app.config_loader import PricingRuleConditions, config
from app.models.pricing_models import PricingInput, PricingOutput

logger = logging.getLogger(__name__)


def _matches(conditions: PricingRuleConditions, inp: PricingInput) -> bool:
    """Return True if all conditions in a rule match the input."""
    if conditions.user_type and conditions.user_type != inp.user_type:
        return False
    if conditions.project_type and conditions.project_type.lower() != inp.project_type.lower():
        return False
    if conditions.house_size_sqft_max is not None:
        if inp.house_size_sqft is None or inp.house_size_sqft > conditions.house_size_sqft_max:
            return False
    return True


def compute_price(pricing_input: PricingInput) -> PricingOutput:
    """
    Evaluate pricing rules top-to-bottom. Return first match.
    Returns PricingOutput(matched=False) if no rule matches.
    A no-match result must trigger escalation in flow_controller.
    """
    for rule in config.pricing.rules:
        if _matches(rule.conditions, pricing_input):
            logger.info("Pricing rule matched: %s", rule.id)
            return PricingOutput(
                matched=True,
                rule_id=rule.id,
                price_min=rule.output.price_min,
                price_max=rule.output.price_max,
                unit=rule.output.unit,
                assumptions=rule.output.assumptions,
                disclaimer=config.pricing.disclaimer,
            )

    logger.warning(
        "No pricing rule matched for user_type=%s project_type=%s",
        pricing_input.user_type,
        pricing_input.project_type,
    )
    return PricingOutput(matched=False)


def build_pricing_input_from_slots(user_type: str, collected_slots: dict) -> PricingInput:
    """Convenience helper to construct PricingInput from session's collected_slots."""
    return PricingInput(
        user_type=user_type,
        project_type=collected_slots.get("project_type", ""),
        house_size_sqft=collected_slots.get("house_size_sqft"),
        monthly_bill_inr=(
            collected_slots.get("monthly_bill_inr")
            or collected_slots.get("monthly_bill")
        ),
        monthly_kwh=collected_slots.get("monthly_kwh"),
        budget_range=collected_slots.get("budget_range"),
        company_size=collected_slots.get("company_size"),
        timeline=collected_slots.get("timeline"),
    )
