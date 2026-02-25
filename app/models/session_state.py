"""Session state model and FlowState enum."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FlowState(str, Enum):
    INIT = "init"
    USER_TYPE_DETECTION = "user_type_detection"
    INTENT_DETECTION = "intent_detection"
    SLOT_COLLECTION = "slot_collection"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"
    PROPOSAL_GENERATION = "proposal_generation"
    ESCALATED = "escalated"
    COMPLETE = "complete"


class SessionState(BaseModel):
    session_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Classification outputs
    user_type: Optional[str] = None               # enterprise | smb | individual
    user_type_confidence: Optional[float] = None
    primary_intent: Optional[str] = None
    intent_confidence: Optional[float] = None

    # Flow control
    flow_state: FlowState = FlowState.INIT
    collected_slots: Dict[str, Any] = Field(default_factory=dict)
    missing_slots: List[str] = Field(default_factory=list)

    # Conversation history for LLM context — [{role, content}]
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)

    # Escalation guards
    slot_attempt_counts: Dict[str, int] = Field(default_factory=dict)
    MAX_SLOT_ATTEMPTS: int = Field(default=2, exclude=True)

    # Status flags
    escalation_triggered: bool = False
    proposal_ready: bool = False
    lead_captured: bool = False       # True once LeadRecord row is appended

    def increment_slot_attempt(self, slot_name: str) -> int:
        """Increment attempt count for a slot and return the new count."""
        self.slot_attempt_counts[slot_name] = self.slot_attempt_counts.get(slot_name, 0) + 1
        return self.slot_attempt_counts[slot_name]

    def should_escalate_slot(self, slot_name: str) -> bool:
        return self.slot_attempt_counts.get(slot_name, 0) >= self.MAX_SLOT_ATTEMPTS
