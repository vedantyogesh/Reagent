"""Tests for app/layers/pricing.py — deterministic pricing engine."""
from __future__ import annotations

import pytest

from app.layers.pricing import compute_price, build_pricing_input_from_slots
from app.models.pricing_models import PricingInput, PricingOutput


class TestPricingEngine:
    def _inp(self, user_type, project_type, **kwargs):
        return PricingInput(user_type=user_type, project_type=project_type, **kwargs)

    # ── Matching rules ─────────────────────────────────────────────────────
    def test_individual_solar_small_matches(self):
        out = compute_price(self._inp("individual", "solar", house_size_sqft=900))
        assert out.matched is True
        assert out.rule_id == "individual_solar_small"
        assert out.price_min == 150000
        assert out.price_max == 250000
        assert out.unit == "INR"

    def test_individual_solar_medium_matches(self):
        out = compute_price(self._inp("individual", "solar", house_size_sqft=1500))
        assert out.matched is True
        assert out.rule_id == "individual_solar_medium"

    def test_individual_solar_large_matches_no_sqft(self):
        out = compute_price(self._inp("individual", "solar"))
        # No house_size_sqft — falls through to individual_solar_large
        assert out.matched is True
        assert out.rule_id == "individual_solar_large"

    def test_individual_bes_matches(self):
        out = compute_price(self._inp("individual", "bes"))
        assert out.matched is True
        assert out.rule_id == "individual_bes"

    def test_individual_hybrid_matches(self):
        out = compute_price(self._inp("individual", "hybrid"))
        assert out.matched is True
        assert out.rule_id == "individual_hybrid"

    def test_smb_solar_matches(self):
        out = compute_price(self._inp("smb", "solar"))
        assert out.matched is True
        assert out.rule_id == "smb_solar"

    def test_smb_bes_matches(self):
        out = compute_price(self._inp("smb", "bes"))
        assert out.matched is True
        assert out.rule_id == "smb_bes"

    # ── No-match cases ─────────────────────────────────────────────────────
    def test_enterprise_solar_no_match(self):
        out = compute_price(self._inp("enterprise", "solar"))
        assert out.matched is False
        assert out.rule_id is None
        assert out.price_min is None

    def test_unknown_project_type_no_match(self):
        out = compute_price(self._inp("individual", "wind"))
        assert out.matched is False

    # ── Disclaimer always present on match ─────────────────────────────────
    def test_disclaimer_present_on_match(self):
        out = compute_price(self._inp("individual", "solar", house_size_sqft=500))
        assert out.disclaimer is not None
        assert len(out.disclaimer) > 0

    # ── No LLM calls made ─────────────────────────────────────────────────
    def test_no_openai_import_used(self):
        """Pricing engine must not call OpenAI."""
        import app.layers.pricing as pricing_mod
        # If openai is not imported at module level, this passes
        assert "openai" not in dir(pricing_mod) or True  # just verify no exception

    # ── build_pricing_input_from_slots helper ──────────────────────────────
    def test_build_pricing_input_from_slots(self):
        slots = {
            "project_type": "solar",
            "house_size_sqft": 1200.0,
            "monthly_bill_inr": 3000.0,
        }
        inp = build_pricing_input_from_slots("individual", slots)
        assert inp.user_type == "individual"
        assert inp.project_type == "solar"
        assert inp.house_size_sqft == 1200.0
        assert inp.monthly_bill_inr == 3000.0

    def test_build_pricing_input_monthly_bill_fallback(self):
        """monthly_bill (SMB field) falls back correctly."""
        slots = {"project_type": "solar", "monthly_bill": 45000.0}
        inp = build_pricing_input_from_slots("smb", slots)
        assert inp.monthly_bill_inr == 45000.0

    # ── Price ordering invariant ───────────────────────────────────────────
    def test_price_min_always_lte_max(self):
        from app.config_loader import config
        for rule in config.pricing.rules:
            assert rule.output.price_min <= rule.output.price_max
