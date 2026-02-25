"""LLM structured output schemas — all LLM calls must return one of these."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


class ClassificationOutput(BaseModel):
    """Output of the combined classification call in entry.py."""
    user_type: str                       # enterprise | smb | individual | unknown
    user_type_confidence: float
    primary_intent: str
    intent_confidence: float

    @field_validator("user_type_confidence", "intent_confidence")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class ExtractedField(BaseModel):
    value: Any
    confidence: float


class ExtractionOutput(BaseModel):
    """Output of the slot extraction call in extractor.py."""
    extracted: Dict[str, ExtractedField] = {}
    unclear_fields: List[str] = []


class FAQGenerationOutput(BaseModel):
    """Output of the FAQ generation call in generator.py."""
    response: str
    citations: List[str] = []
    confidence: str = "medium"          # high | medium | low
    escalate: bool = False

    @field_validator("confidence")
    @classmethod
    def valid_confidence(cls, v: str) -> str:
        if v not in ("high", "medium", "low"):
            return "medium"
        return v


class ProposalSectionOutput(BaseModel):
    """Output of a single proposal section generation call."""
    id: str
    title: str
    content: str


class ProposalOutput(BaseModel):
    """Assembled full proposal — all sections complete."""
    sections: List[ProposalSectionOutput]
    client_name: str
    generated_at: str                   # ISO timestamp


class ChunkResult(BaseModel):
    """A single retrieved chunk from Pinecone."""
    chunk_id: str
    section_title: str
    content: str
    score: float
