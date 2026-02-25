"""Pricing engine I/O models."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PricingInput(BaseModel):
    user_type: str
    project_type: str
    house_size_sqft: Optional[float] = None
    monthly_bill_inr: Optional[float] = None
    monthly_kwh: Optional[float] = None
    budget_range: Optional[str] = None
    company_size: Optional[str] = None
    timeline: Optional[str] = None


class PricingOutput(BaseModel):
    matched: bool
    rule_id: Optional[str] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    unit: Optional[str] = "INR"
    assumptions: Optional[str] = None
    disclaimer: Optional[str] = None
