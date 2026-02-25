"""Tests for app/config_loader.py"""
from __future__ import annotations

import pytest
from app.config_loader import config, load_config


class TestConfigLoads:
    def test_company_name(self):
        assert config.company.company_name == "Ions Energy"

    def test_models_present(self):
        assert config.company.models.classification == "gpt-4o-mini"
        assert config.company.models.proposal_generation == "gpt-4o"

    def test_all_user_types_present(self):
        assert set(config.slots.user_types.keys()) == {"enterprise", "smb", "individual"}

    def test_client_name_always_first_slot(self):
        for user_type, slots in config.slots.user_types.items():
            assert slots.required_slots[0].name == "client_name", (
                f"First slot for {user_type} must be client_name"
            )

    def test_contact_slot_has_contact_form_input_type(self):
        for user_type, slots in config.slots.user_types.items():
            contact = next((s for s in slots.required_slots if s.name == "contact"), None)
            assert contact is not None, f"{user_type} missing contact slot"
            assert contact.input_type == "contact_form"

    def test_intent_count(self):
        assert len(config.intents.intents) >= 4

    def test_fallback_intent_exists_in_intents(self):
        names = {i.name for i in config.intents.intents}
        assert config.intents.fallback_intent in names

    def test_confidence_threshold_valid(self):
        assert 0.0 <= config.intents.confidence_threshold <= 1.0

    def test_pricing_rules_present(self):
        assert len(config.pricing.rules) >= 1

    def test_pricing_rule_price_min_lte_max(self):
        for rule in config.pricing.rules:
            assert rule.output.price_min <= rule.output.price_max

    def test_proposal_sections_present(self):
        assert len(config.proposal_template.sections) == 7

    def test_proposal_has_pricing_section(self):
        section_ids = {s.id for s in config.proposal_template.sections}
        assert "pricing" in section_ids

    def test_session_timeout_positive(self):
        assert config.company.session_timeout_minutes > 0
