"""Tests for app/leads.py — CSV lead capture."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

import app.leads as leads_module
from app.models.lead_models import LeadRecord


@pytest.fixture(autouse=True)
def tmp_leads_file(tmp_path, monkeypatch):
    """Redirect leads file to a temp path for each test."""
    tmp_csv = tmp_path / "leads.csv"
    monkeypatch.setattr(leads_module, "LEADS_PATH", tmp_csv)
    yield tmp_csv


class TestLeadsCSV:
    def _make_record(self, name="Test User", user_type="individual"):
        return LeadRecord(
            client_name=name,
            user_type=user_type,
            captured_at=datetime.utcnow(),
        )

    def test_append_creates_file_with_header(self, tmp_leads_file):
        leads_module.append_row(self._make_record())
        assert tmp_leads_file.exists()
        rows = leads_module.read_all()
        assert len(rows) == 1
        assert rows[0]["client_name"] == "Test User"

    def test_append_does_not_store_email_or_phone_initially(self, tmp_leads_file):
        leads_module.append_row(self._make_record())
        rows = leads_module.read_all()
        assert rows[0]["email"] == ""
        assert rows[0]["phone"] == ""

    def test_update_contact_writes_email(self, tmp_leads_file):
        leads_module.append_row(self._make_record())
        leads_module.update_contact("Test User", email="test@example.com", phone=None)
        rows = leads_module.read_all()
        assert rows[0]["email"] == "test@example.com"
        assert rows[0]["phone"] == ""

    def test_update_contact_writes_phone(self, tmp_leads_file):
        leads_module.append_row(self._make_record())
        leads_module.update_contact("Test User", email=None, phone="9876543210")
        rows = leads_module.read_all()
        assert rows[0]["phone"] == "9876543210"

    def test_update_proposal_generated(self, tmp_leads_file):
        leads_module.append_row(self._make_record())
        leads_module.update_proposal_generated("Test User")
        rows = leads_module.read_all()
        assert rows[0]["proposal_generated"] == "True"

    def test_multiple_rows_only_first_matching_updated(self, tmp_leads_file):
        leads_module.append_row(self._make_record("Alice"))
        leads_module.append_row(self._make_record("Bob"))
        leads_module.update_proposal_generated("Alice")
        rows = leads_module.read_all()
        alice = next(r for r in rows if r["client_name"] == "Alice")
        bob   = next(r for r in rows if r["client_name"] == "Bob")
        assert alice["proposal_generated"] == "True"
        assert bob["proposal_generated"] == "False"

    def test_rows_never_deleted(self, tmp_leads_file):
        leads_module.append_row(self._make_record("Alice"))
        leads_module.append_row(self._make_record("Bob"))
        leads_module.update_contact("Alice", email="a@a.com", phone=None)
        rows = leads_module.read_all()
        assert len(rows) == 2

    def test_file_opens_in_excel_format(self, tmp_leads_file):
        """Verify CSV is valid and has correct fieldnames."""
        leads_module.append_row(self._make_record())
        import csv
        with open(tmp_leads_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == leads_module.FIELDNAMES
