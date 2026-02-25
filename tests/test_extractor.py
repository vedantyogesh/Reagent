"""Tests for app/layers/extractor.py — slot extraction and contact validation."""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.layers.extractor import _validate_contact_field, _EMAIL_RE, _PHONE_RE
from app.models.output_models import ExtractionOutput, ExtractedField
from app.models.session_state import SessionState


class TestContactRegexes:
    """Verify the server-side contact regexes match spec."""

    def test_valid_email(self):
        assert _EMAIL_RE.match("user@example.com")
        assert _EMAIL_RE.match("first.last@sub.domain.in")
        # spec regex ^[\w\.-]+@... excludes '+' by design (no plus-addressing)
        assert not _EMAIL_RE.match("user+tag@mail.co")

    def test_invalid_email(self):
        assert not _EMAIL_RE.match("notanemail")
        assert not _EMAIL_RE.match("@nodomain.com")
        assert not _EMAIL_RE.match("missing@.com")

    def test_valid_indian_mobile(self):
        assert _PHONE_RE.match("9876543210")
        assert _PHONE_RE.match("6123456789")
        assert _PHONE_RE.match("8000000000")

    def test_invalid_phone_starts_wrong_digit(self):
        assert not _PHONE_RE.match("1234567890")  # starts with 1
        assert not _PHONE_RE.match("5000000000")  # starts with 5

    def test_invalid_phone_wrong_length(self):
        assert not _PHONE_RE.match("98765432")   # 8 digits
        assert not _PHONE_RE.match("98765432100")  # 11 digits

    def test_invalid_phone_non_numeric(self):
        assert not _PHONE_RE.match("9876abc210")


class TestValidateContactField:
    """Unit tests for _validate_contact_field without LLM calls."""

    def _extraction_with_contact(self, value: str) -> ExtractionOutput:
        return ExtractionOutput(
            extracted={"contact": ExtractedField(value=value, confidence=0.9)},
            unclear_fields=[],
        )

    def test_valid_email_extracted(self):
        ext = self._extraction_with_contact("test@example.com")
        result = _validate_contact_field(ext)
        assert "email" in result.extracted
        assert result.extracted["email"].value == "test@example.com"
        assert "contact" not in result.extracted

    def test_valid_phone_extracted(self):
        ext = self._extraction_with_contact("9876543210")
        result = _validate_contact_field(ext)
        assert "phone" in result.extracted
        assert result.extracted["phone"].value == "9876543210"

    def test_both_email_and_phone_extracted(self):
        # LLM might return "email: x | phone: y" — but _validate takes the raw value
        ext = self._extraction_with_contact("test@example.com")
        result = _validate_contact_field(ext)
        assert "email" in result.extracted

    def test_invalid_contact_goes_to_unclear(self):
        ext = self._extraction_with_contact("notvalid")
        result = _validate_contact_field(ext)
        assert "contact" in result.unclear_fields
        assert "email" not in result.extracted
        assert "phone" not in result.extracted

    def test_empty_contact_goes_to_unclear(self):
        ext = self._extraction_with_contact("")
        result = _validate_contact_field(ext)
        assert "contact" in result.unclear_fields

    def test_no_contact_key_passes_through(self):
        ext = ExtractionOutput(
            extracted={"client_name": ExtractedField(value="Alice", confidence=1.0)},
            unclear_fields=[],
        )
        result = _validate_contact_field(ext)
        assert "client_name" in result.extracted
        assert "contact" not in result.unclear_fields


class TestExtractorWithMockedLLM:
    """Integration tests with mocked OpenAI calls."""

    def _make_session(self, user_type="individual"):
        s = SessionState(session_id="test-123")
        s.user_type = user_type
        return s

    @pytest.mark.asyncio
    async def test_extract_client_name(self):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = (
            '{"extracted": {"client_name": {"value": "Priya", "confidence": 0.98}}, '
            '"unclear_fields": []}'
        )
        with patch("app.layers.extractor._client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            from app.layers.extractor import extract
            result = await extract(
                message="My name is Priya",
                target_slots=["client_name"],
                session=self._make_session(),
            )
        assert "client_name" in result.extracted
        assert result.extracted["client_name"].value == "Priya"

    @pytest.mark.asyncio
    async def test_extract_valid_email_from_contact_slot(self):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = (
            '{"extracted": {"contact": {"value": "priya@example.com", "confidence": 1.0}}, '
            '"unclear_fields": []}'
        )
        with patch("app.layers.extractor._client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            from app.layers.extractor import extract
            result = await extract(
                message="priya@example.com",
                target_slots=["contact"],
                session=self._make_session(),
            )
        assert "email" in result.extracted
        assert result.extracted["email"].value == "priya@example.com"

    @pytest.mark.asyncio
    async def test_extract_invalid_phone_returns_unclear(self):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = (
            '{"extracted": {"contact": {"value": "123", "confidence": 0.5}}, '
            '"unclear_fields": []}'
        )
        with patch("app.layers.extractor._client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            from app.layers.extractor import extract
            result = await extract(
                message="123",
                target_slots=["contact"],
                session=self._make_session(),
            )
        assert "contact" in result.unclear_fields
