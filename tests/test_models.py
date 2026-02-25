"""Tests for app/models/ — Pydantic model validation."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.models.session_state import FlowState, SessionState
from app.models.output_models import (
    ClassificationOutput,
    ExtractionOutput,
    ExtractedField,
    FAQGenerationOutput,
    ProposalSectionOutput,
    ProposalOutput,
    ChunkResult,
)
from app.models.pricing_models import PricingInput, PricingOutput
from app.models.lead_models import LeadRecord
from app.models.slot_models import (
    get_required_slots,
    get_slot_definition,
    get_slot_question,
    is_contact_form_slot,
)
from app.config_loader import config


class TestSessionState:
    def test_default_flow_state_is_init(self):
        s = SessionState(session_id="abc")
        assert s.flow_state == FlowState.INIT

    def test_has_created_at(self):
        s = SessionState(session_id="abc")
        assert isinstance(s.created_at, datetime)

    def test_increment_slot_attempt(self):
        s = SessionState(session_id="abc")
        assert s.increment_slot_attempt("client_name") == 1
        assert s.increment_slot_attempt("client_name") == 2

    def test_should_escalate_slot_at_max(self):
        s = SessionState(session_id="abc")
        s.increment_slot_attempt("foo")
        assert not s.should_escalate_slot("foo")
        s.increment_slot_attempt("foo")
        assert s.should_escalate_slot("foo")


class TestOutputModels:
    def test_classification_output_clamps_confidence(self):
        out = ClassificationOutput(
            user_type="individual",
            user_type_confidence=1.5,   # over 1.0 — should be clamped
            primary_intent="general_faq",
            intent_confidence=-0.1,     # negative — should be clamped
        )
        assert out.user_type_confidence == 1.0
        assert out.intent_confidence == 0.0

    def test_extraction_output_defaults(self):
        out = ExtractionOutput()
        assert out.extracted == {}
        assert out.unclear_fields == []

    def test_faq_output_invalid_confidence_defaults_to_medium(self):
        out = FAQGenerationOutput(response="hello", confidence="extreme")
        assert out.confidence == "medium"

    def test_chunk_result(self):
        c = ChunkResult(
            chunk_id="solar-001",
            section_title="Solar Solutions",
            content="Solar panels are great.",
            score=0.85,
        )
        assert c.score == 0.85


class TestPricingModels:
    def test_pricing_input_optional_fields(self):
        inp = PricingInput(user_type="individual", project_type="solar")
        assert inp.house_size_sqft is None

    def test_pricing_output_not_matched(self):
        out = PricingOutput(matched=False)
        assert out.price_min is None


class TestLeadRecord:
    def test_empty_email_normalised_to_none(self):
        r = LeadRecord(
            client_name="Alice",
            email="",
            user_type="individual",
            captured_at=datetime.utcnow(),
        )
        assert r.email is None

    def test_valid_record(self):
        r = LeadRecord(
            client_name="Bob",
            email="bob@example.com",
            phone="9876543210",
            user_type="smb",
            captured_at=datetime.utcnow(),
        )
        assert r.email == "bob@example.com"
        assert r.proposal_generated is False


class TestSlotModels:
    def test_client_name_always_index_0(self):
        for user_type in ("enterprise", "smb", "individual"):
            slots = get_required_slots(user_type, config.slots)
            assert slots[0] == "client_name"

    def test_contact_always_index_1(self):
        for user_type in ("enterprise", "smb", "individual"):
            slots = get_required_slots(user_type, config.slots)
            assert slots[1] == "contact"

    def test_get_slot_definition_returns_correct_slot(self):
        defn = get_slot_definition("client_name", "individual", config.slots)
        assert defn is not None
        assert defn.name == "client_name"

    def test_get_slot_definition_none_for_unknown(self):
        defn = get_slot_definition("nonexistent_slot", "individual", config.slots)
        assert defn is None

    def test_is_contact_form_slot_true_for_contact(self):
        for user_type in ("enterprise", "smb", "individual"):
            assert is_contact_form_slot("contact", user_type, config.slots) is True

    def test_is_contact_form_slot_false_for_others(self):
        assert is_contact_form_slot("client_name", "individual", config.slots) is False

    def test_get_slot_question_returns_string(self):
        q = get_slot_question("client_name", "individual", config.slots)
        assert isinstance(q, str)
        assert len(q) > 0
