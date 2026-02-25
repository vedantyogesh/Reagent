"""
Flow controller — state machine governing every FlowState transition.
This is the single source of truth for conversation routing.
No other layer should change session.flow_state directly.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from pydantic import BaseModel

from app.config_loader import config
from app.models.session_state import FlowState, SessionState
from app.models.slot_models import (
    get_required_slots,
    get_slot_question,
    is_contact_form_slot,
)
from app.utils import EscalationException

logger = logging.getLogger(__name__)


class DonePayload(BaseModel):
    flow_state: str
    proposal_ready: bool
    escalated: bool
    input_type: Optional[str]  # None | "contact_form"


async def advance(
    session: SessionState,
    message: str,
) -> AsyncIterator[str]:
    """
    Main entry point for every /chat request.
    Yields raw token strings. Caller wraps in SSE format.
    After iteration, call get_done_payload(session) for the done event.
    """
    # Append user message to history
    session.conversation_history.append({"role": "user", "content": message})

    try:
        async for token in _route(session, message):
            yield token
    except EscalationException as e:
        logger.error("EscalationException: %s", e)
        _trigger_escalation(session)
        yield config.company.escalation_message


def get_done_payload(session: SessionState) -> DonePayload:
    """Build the SSE done event payload from current session state."""
    input_type = _get_input_type(session)
    return DonePayload(
        flow_state=session.flow_state.value,
        proposal_ready=session.proposal_ready,
        escalated=session.escalation_triggered,
        input_type=input_type,
    )


def _get_input_type(session: SessionState) -> Optional[str]:
    """Return 'contact_form' if the next missing slot uses the contact form widget."""
    if session.flow_state != FlowState.SLOT_COLLECTION:
        return None
    if not session.missing_slots:
        return None
    next_slot = session.missing_slots[0]
    user_type = session.user_type or "individual"
    if is_contact_form_slot(next_slot, user_type, config.slots):
        return "contact_form"
    return None


def _trigger_escalation(session: SessionState) -> None:
    session.flow_state = FlowState.ESCALATED
    session.escalation_triggered = True


async def _route(session: SessionState, message: str) -> AsyncIterator[str]:
    """Route to the correct handler based on current flow state."""

    state = session.flow_state

    # ── INIT / USER_TYPE_DETECTION ──────────────────────────────────────
    if state in (FlowState.INIT, FlowState.USER_TYPE_DETECTION):
        async for token in _handle_classification(session, message):
            yield token
        return

    # ── INTENT_DETECTION ────────────────────────────────────────────────
    if state == FlowState.INTENT_DETECTION:
        async for token in _handle_intent_routing(session, message):
            yield token
        return

    # ── SLOT_COLLECTION ──────────────────────────────────────────────────
    if state == FlowState.SLOT_COLLECTION:
        async for token in _handle_slot_collection(session, message):
            yield token
        return

    # ── GENERATION (FAQ) ─────────────────────────────────────────────────
    if state == FlowState.GENERATION:
        async for token in _handle_faq_generation(session, message):
            yield token
        return

    # ── COMPLETE (post-proposal follow-up) ──────────────────────────────
    if state == FlowState.COMPLETE:
        # Re-route as a new intent from complete state
        async for token in _handle_intent_routing(session, message):
            yield token
        return

    # ── ESCALATED ────────────────────────────────────────────────────────
    if state == FlowState.ESCALATED:
        yield config.company.escalation_message
        return

    # Fallback
    yield "I'm sorry, something went wrong. Please try again."


# ---------------------------------------------------------------------------
# State handlers
# ---------------------------------------------------------------------------

async def _handle_classification(
    session: SessionState, message: str
) -> AsyncIterator[str]:
    """INIT → USER_TYPE_DETECTION → INTENT_DETECTION."""
    from app.layers import entry

    session.flow_state = FlowState.USER_TYPE_DETECTION
    classification = await entry.classify(message, session)

    threshold = config.intents.confidence_threshold

    # User type confidence check
    if (
        classification.user_type == "unknown"
        or classification.user_type_confidence < threshold
    ):
        reply = (
            "To help you best, could you tell me — are you looking for an energy solution "
            "for your home, a small business, or a large enterprise?"
        )
        session.conversation_history.append({"role": "assistant", "content": reply})
        for char in reply:
            yield char
        return

    session.user_type = classification.user_type
    session.user_type_confidence = classification.user_type_confidence

    # Intent confidence check — fall back to general_faq if low
    if classification.intent_confidence < threshold:
        session.primary_intent = config.intents.fallback_intent
    else:
        session.primary_intent = classification.primary_intent
    session.intent_confidence = classification.intent_confidence

    # Route based on intent
    async for token in _dispatch_intent(session, message):
        yield token


async def _handle_intent_routing(
    session: SessionState, message: str
) -> AsyncIterator[str]:
    """Re-classify intent for follow-up messages."""
    from app.layers import entry

    session.flow_state = FlowState.INTENT_DETECTION
    classification = await entry.classify(message, session)

    threshold = config.intents.confidence_threshold
    if classification.intent_confidence < threshold:
        session.primary_intent = config.intents.fallback_intent
    else:
        session.primary_intent = classification.primary_intent

    async for token in _dispatch_intent(session, message):
        yield token


async def _dispatch_intent(
    session: SessionState, message: str
) -> AsyncIterator[str]:
    """Route to slot collection, retrieval/generation, or escalation based on intent."""
    intent = session.primary_intent or config.intents.fallback_intent

    # Find the triggers_flow for this intent
    intent_defn = next(
        (i for i in config.intents.intents if i.name == intent), None
    )
    triggers_flow = intent_defn.triggers_flow if intent_defn else "faq"

    if triggers_flow == "escalate":
        _trigger_escalation(session)
        yield config.company.escalation_message
        return

    if triggers_flow == "proposal":
        # Start slot collection
        session.flow_state = FlowState.SLOT_COLLECTION
        session.missing_slots = get_required_slots(session.user_type, config.slots)
        # Remove already-collected slots
        session.missing_slots = [
            s for s in session.missing_slots if s not in session.collected_slots
        ]
        async for token in _handle_slot_collection(session, message):
            yield token
        return

    # Default: faq → retrieval + generation
    async for token in _do_retrieval_and_faq(session, message):
        yield token


async def _handle_slot_collection(
    session: SessionState, message: str
) -> AsyncIterator[str]:
    """
    Extract slots from message, update session, ask next missing slot.
    Triggers contact form signal when contact slot is next.
    When all slots collected, transitions to retrieval + proposal generation.
    """
    from app.layers import extractor
    import app.leads as leads
    from app.models.lead_models import LeadRecord

    session.flow_state = FlowState.SLOT_COLLECTION

    # Extract from the current message
    if session.missing_slots:
        extraction = await extractor.extract(
            message=message,
            target_slots=session.missing_slots,
            session=session,
        )

        # Merge extracted values into collected_slots
        for slot_name, field in extraction.extracted.items():
            session.collected_slots[slot_name] = field.value

        # Handle contact field — email/phone keys replace contact
        for contact_key in ("email", "phone"):
            if contact_key in session.collected_slots:
                # Remove "contact" from missing_slots now that we have contact info
                session.missing_slots = [
                    s for s in session.missing_slots if s != "contact"
                ]

        # Increment attempt counts for unclear fields
        for slot_name in extraction.unclear_fields:
            count = session.increment_slot_attempt(slot_name)
            if session.should_escalate_slot(slot_name):
                logger.warning("Escalating: slot %s failed %d times", slot_name, count)
                _trigger_escalation(session)
                yield config.company.escalation_message
                return

        # Remove collected slots from missing list
        session.missing_slots = [
            s for s in session.missing_slots
            if s not in session.collected_slots
        ]

        # Lead Write Op 1 — write row as soon as client_name is collected
        if (
            "client_name" in session.collected_slots
            and not session.lead_captured
        ):
            from datetime import datetime
            leads.append_row(LeadRecord(
                client_name=session.collected_slots["client_name"],
                user_type=session.user_type or "unknown",
                captured_at=datetime.utcnow(),
            ))
            session.lead_captured = True

        # Lead Write Op 2 — update contact fields when validated
        if "email" in session.collected_slots or "phone" in session.collected_slots:
            if session.lead_captured:
                leads.update_contact(
                    client_name=session.collected_slots.get("client_name", ""),
                    email=session.collected_slots.get("email"),
                    phone=session.collected_slots.get("phone"),
                )

    # All slots collected → proposal generation
    if not session.missing_slots:
        async for token in _do_retrieval_and_proposal(session):
            yield token
        return

    # Ask next missing slot
    next_slot = session.missing_slots[0]
    user_type = session.user_type or "individual"
    question = get_slot_question(next_slot, user_type, config.slots)

    session.conversation_history.append({"role": "assistant", "content": question})
    for char in question:
        yield char


async def _do_retrieval_and_faq(
    session: SessionState, message: str
) -> AsyncIterator[str]:
    """Retrieve context and stream FAQ response."""
    from app.layers import retrieval, generator

    session.flow_state = FlowState.RETRIEVAL
    chunks = await retrieval.retrieve(message, session)

    if not chunks:
        _trigger_escalation(session)
        yield config.company.escalation_message
        return

    session.flow_state = FlowState.GENERATION
    async for token in generator.generate_faq(message, chunks, session):
        yield token

    if session.escalation_triggered:
        session.flow_state = FlowState.ESCALATED
    else:
        # Return to intent detection for follow-up questions
        session.flow_state = FlowState.INTENT_DETECTION


async def _do_retrieval_and_proposal(session: SessionState) -> AsyncIterator[str]:
    """Retrieve context, run pricing, stream full proposal generation."""
    from app.layers import retrieval, generator, pricing

    session.flow_state = FlowState.RETRIEVAL

    # Build a focused query from collected slots
    query_parts = [
        session.collected_slots.get("project_type", ""),
        session.user_type or "",
        session.collected_slots.get("state", ""),
        session.collected_slots.get("industry", ""),
    ]
    query = " ".join(filter(None, query_parts)) or "energy solution"

    chunks = await retrieval.retrieve(query, session)

    if not chunks:
        _trigger_escalation(session)
        yield config.company.escalation_message
        return

    # Pricing — pure Python, no LLM
    pricing_input = pricing.build_pricing_input_from_slots(
        session.user_type, session.collected_slots
    )
    pricing_output = pricing.compute_price(pricing_input)

    if not pricing_output.matched:
        _trigger_escalation(session)
        yield config.company.escalation_message
        return

    session.flow_state = FlowState.PROPOSAL_GENERATION

    try:
        async for token in generator.generate_proposal(session, chunks, pricing_output):
            yield token
    except EscalationException as e:
        logger.error("Proposal generation failed: %s", e)
        _trigger_escalation(session)
        yield config.company.escalation_message
        return

    session.flow_state = FlowState.COMPLETE
