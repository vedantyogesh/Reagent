"""Lead capture model — written to data/leads.csv."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, model_validator


class LeadRecord(BaseModel):
    client_name: str
    email: Optional[str] = None       # validated against email regex before storage
    phone: Optional[str] = None       # validated against Indian mobile regex before storage
    user_type: str                     # enterprise | smb | individual
    captured_at: datetime
    proposal_generated: bool = False

    @model_validator(mode="after")
    def normalise_empty_strings(self) -> "LeadRecord":
        """Convert empty strings to None so CSV round-trips cleanly."""
        if self.email == "":
            self.email = None
        if self.phone == "":
            self.phone = None
        return self
