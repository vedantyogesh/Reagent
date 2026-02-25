"""
Config loader — loads and validates all five YAML config files at startup.
App refuses to start if any file is missing or has a validation error.
All company data, model names, pricing, and templates live in /config/ only.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator

CONFIG_DIR = Path(__file__).parent.parent / "config"


# ---------------------------------------------------------------------------
# company.yaml
# ---------------------------------------------------------------------------

class ModelConfig(BaseModel):
    classification: str
    extraction: str
    faq_generation: str
    proposal_generation: str


class CompanyConfig(BaseModel):
    company_name: str
    industry: str
    country: str
    currency: str
    contact_email: str
    escalation_message: str
    models: ModelConfig
    session_timeout_minutes: int

    @field_validator("session_timeout_minutes")
    @classmethod
    def timeout_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("session_timeout_minutes must be positive")
        return v


# ---------------------------------------------------------------------------
# slots.yaml
# ---------------------------------------------------------------------------

class SlotValidation(BaseModel):
    regex_email: Optional[str] = None
    regex_phone: Optional[str] = None
    error_message: Optional[str] = None


class SlotDefinition(BaseModel):
    name: str
    question: str
    type: str  # "string" | "number"
    input_type: Optional[str] = None  # "contact_form" triggers form widget
    validation: Optional[SlotValidation] = None

    @field_validator("type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in ("string", "number"):
            raise ValueError(f"slot type must be 'string' or 'number', got '{v}'")
        return v


class UserTypeSlots(BaseModel):
    required_slots: List[SlotDefinition]
    optional_slots: List[SlotDefinition] = []


class SlotsConfig(BaseModel):
    user_types: Dict[str, UserTypeSlots]

    @model_validator(mode="after")
    def required_user_types_present(self) -> "SlotsConfig":
        required = {"enterprise", "smb", "individual"}
        missing = required - set(self.user_types.keys())
        if missing:
            raise ValueError(f"slots.yaml missing user_types: {missing}")
        return self

    @model_validator(mode="after")
    def client_name_first(self) -> "SlotsConfig":
        for user_type, slots in self.user_types.items():
            names = [s.name for s in slots.required_slots]
            if names and names[0] != "client_name":
                raise ValueError(
                    f"slots.yaml: first required slot for '{user_type}' must be 'client_name', got '{names[0]}'"
                )
        return self


# ---------------------------------------------------------------------------
# intents.yaml
# ---------------------------------------------------------------------------

class IntentDefinition(BaseModel):
    name: str
    description: str
    triggers_flow: str  # "faq" | "proposal" | "escalate"

    @field_validator("triggers_flow")
    @classmethod
    def valid_flow(cls, v: str) -> str:
        if v not in ("faq", "proposal", "escalate"):
            raise ValueError(f"triggers_flow must be faq/proposal/escalate, got '{v}'")
        return v


class IntentsConfig(BaseModel):
    intents: List[IntentDefinition]
    fallback_intent: str
    confidence_threshold: float

    @field_validator("confidence_threshold")
    @classmethod
    def threshold_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence_threshold must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def fallback_exists(self) -> "IntentsConfig":
        names = {i.name for i in self.intents}
        if self.fallback_intent not in names:
            raise ValueError(
                f"fallback_intent '{self.fallback_intent}' not found in intents list"
            )
        return self


# ---------------------------------------------------------------------------
# pricing_rules.yaml
# ---------------------------------------------------------------------------

class PricingRuleConditions(BaseModel):
    user_type: Optional[str] = None
    project_type: Optional[str] = None
    house_size_sqft_max: Optional[float] = None


class PricingRuleOutput(BaseModel):
    price_min: int
    price_max: int
    unit: str
    assumptions: str

    @model_validator(mode="after")
    def min_lte_max(self) -> "PricingRuleOutput":
        if self.price_min > self.price_max:
            raise ValueError("price_min must be <= price_max")
        return self


class PricingRule(BaseModel):
    id: str
    conditions: PricingRuleConditions
    output: PricingRuleOutput


class PricingConfig(BaseModel):
    rules: List[PricingRule]
    disclaimer: str

    @field_validator("rules")
    @classmethod
    def at_least_one_rule(cls, v: List[PricingRule]) -> List[PricingRule]:
        if not v:
            raise ValueError("pricing_rules.yaml must contain at least one rule")
        return v


# ---------------------------------------------------------------------------
# proposal_template.yaml
# ---------------------------------------------------------------------------

class ProposalSection(BaseModel):
    id: str
    title: str
    prompt_instruction: str


class ProposalTemplateConfig(BaseModel):
    sections: List[ProposalSection]

    @field_validator("sections")
    @classmethod
    def at_least_one_section(cls, v: List[ProposalSection]) -> List[ProposalSection]:
        if not v:
            raise ValueError("proposal_template.yaml must contain at least one section")
        return v


# ---------------------------------------------------------------------------
# Top-level AppConfig
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    company: CompanyConfig
    slots: SlotsConfig
    intents: IntentsConfig
    pricing: PricingConfig
    proposal_template: ProposalTemplateConfig


def _load_yaml(filename: str) -> Any:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config() -> AppConfig:
    """
    Load and validate all five config YAML files.
    Raises ValueError with a clear message on any validation error.
    Called once at module import; result is the module-level `config` singleton.
    """
    try:
        company_data = _load_yaml("company.yaml")
        slots_data = _load_yaml("slots.yaml")
        intents_data = _load_yaml("intents.yaml")
        pricing_data = _load_yaml("pricing_rules.yaml")
        template_data = _load_yaml("proposal_template.yaml")

        return AppConfig(
            company=CompanyConfig(**company_data),
            slots=SlotsConfig(**slots_data),
            intents=IntentsConfig(**intents_data),
            pricing=PricingConfig(**pricing_data),
            proposal_template=ProposalTemplateConfig(**template_data),
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"[config_loader] Missing config file — {e}") from e
    except Exception as e:
        raise RuntimeError(f"[config_loader] Config validation failed — {e}") from e


# Module-level singleton — imported by all layers.
# Raises RuntimeError at import time if any config is invalid.
config: AppConfig = load_config()
