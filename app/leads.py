"""
Lead capture — CSV only (data/leads.csv).
Three write operations per session:
  1. append_row()           — on client_name extraction
  2. update_contact()       — on email/phone validation
  3. update_proposal_generated() — on PDF creation
Rows are never deleted.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.models.lead_models import LeadRecord

LEADS_PATH = Path("data/leads.csv")
FIELDNAMES = ["client_name", "email", "phone", "user_type", "captured_at", "proposal_generated"]


def _ensure_file() -> None:
    """Create data/leads.csv with header row if it doesn't exist."""
    LEADS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LEADS_PATH.exists():
        with open(LEADS_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def append_row(record: LeadRecord) -> None:
    """
    Write Op 1 — append new row when client_name is first extracted.
    email and phone are empty at this stage.
    """
    _ensure_file()
    with open(LEADS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow({
            "client_name":        record.client_name,
            "email":              record.email or "",
            "phone":              record.phone or "",
            "user_type":          record.user_type,
            "captured_at":        record.captured_at.isoformat(),
            "proposal_generated": str(record.proposal_generated),
        })


def update_contact(
    client_name: str,
    email: Optional[str],
    phone: Optional[str],
) -> None:
    """
    Write Op 2 — update email and/or phone on the existing row
    after server-side validation passes. Only validated values are stored.
    """
    updates: dict = {}
    if email:
        updates["email"] = email
    if phone:
        updates["phone"] = phone
    if updates:
        _rewrite_matching(client_name, updates)


def update_proposal_generated(client_name: str) -> None:
    """Write Op 3 — set proposal_generated=True after PDF is created."""
    _rewrite_matching(client_name, {"proposal_generated": "True"})


def _rewrite_matching(client_name: str, updates: dict) -> None:
    """
    Read all rows, apply updates to the first row matching client_name, rewrite file.
    This is safe for the low-volume lead capture use case.
    """
    _ensure_file()
    rows = []
    with open(LEADS_PATH, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    matched = False
    for row in rows:
        if row["client_name"] == client_name and not matched:
            row.update(updates)
            matched = True

    with open(LEADS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def read_all() -> list[dict]:
    """Return all lead rows as dicts. Used in tests."""
    _ensure_file()
    with open(LEADS_PATH, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
