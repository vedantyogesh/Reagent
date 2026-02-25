"""
Slot extractor — extracts slot values from user messages via LLM.
Applies server-side regex validation for contact fields (email, phone).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from openai import AsyncOpenAI

from app.config_loader import config
from app.models.output_models import ChunkResult, ExtractionOutput, ExtractedField
from app.models.session_state import SessionState
from app.utils import EscalationException, validate_or_escalate

logger = logging.getLogger(__name__)
_client = AsyncOpenAI()

# Server-side contact validation regexes (same as widget client-side)
_EMAIL_RE = re.compile(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$')
_PHONE_RE = re.compile(r'^[6-9]\d{9}$')  # Indian mobile: starts 6-9, 10 digits


def _build_extraction_prompt(target_slots: List[str], user_type: str) -> str:
    slot_descriptions = []
    slots_cfg = config.slots.user_types.get(user_type)
    all_slots = []
    if slots_cfg:
        all_slots = slots_cfg.required_slots + slots_cfg.optional_slots

    for slot_name in target_slots:
        defn = next((s for s in all_slots if s.name == slot_name), None)
        if defn:
            slot_descriptions.append(
                f"  - {slot_name} (type: {defn.type}): {defn.question}"
            )
        else:
            slot_descriptions.append(f"  - {slot_name}")

    slots_str = "\n".join(slot_descriptions) if slot_descriptions else "  (none)"

    return f"""You are extracting information from a customer message for {config.company.company_name}.

Extract values for the following slots from the user's message:
{slots_str}

Rules:
- Only extract values that are clearly stated in the message.
- If a value is ambiguous or not present, put the slot name in unclear_fields.
- For contact slot: extract email addresses and/or phone numbers.
- For number slots: extract the numeric value only (no units).
- If the user updates a previously given value, extract the new value.

Return ONLY valid JSON:
{{
  "extracted": {{
    "slot_name": {{"value": <extracted_value>, "confidence": 0.0-1.0}},
    ...
  }},
  "unclear_fields": ["slot_name", ...]
}}"""


def _validate_contact_field(extraction: ExtractionOutput) -> ExtractionOutput:
    """
    Post-extraction: validate email/phone from contact slot using server-side regex.
    At least one of email or phone must pass validation.
    Replaces 'contact' key with 'email' and/or 'phone' keys.
    """
    if "contact" not in extraction.extracted:
        return extraction

    raw_value = str(extraction.extracted["contact"].value).strip()
    del extraction.extracted["contact"]

    email_match = _EMAIL_RE.match(raw_value)
    phone_match = _PHONE_RE.match(raw_value)

    if email_match:
        extraction.extracted["email"] = ExtractedField(value=email_match.group(), confidence=1.0)
    if phone_match:
        extraction.extracted["phone"] = ExtractedField(value=phone_match.group(), confidence=1.0)

    if not email_match and not phone_match:
        # Neither matched — put contact back as unclear
        if "contact" not in extraction.unclear_fields:
            extraction.unclear_fields.append("contact")

    return extraction


async def extract(
    message: str,
    target_slots: List[str],
    session: SessionState,
) -> ExtractionOutput:
    """
    Extract slot values from a user message.
    Applies regex validation for contact fields.
    Uses last 6 messages for context.
    """
    if not target_slots:
        return ExtractionOutput()

    user_type = session.user_type or "individual"
    system_prompt = _build_extraction_prompt(target_slots, user_type)

    async def _call() -> str:
        response = await _client.chat.completions.create(
            model=config.company.models.extraction,
            messages=[
                {"role": "system", "content": system_prompt},
                *session.conversation_history[-6:],
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        return response.choices[0].message.content

    raw = await _call()
    extraction = validate_or_escalate(raw, ExtractionOutput, max_retries=2, retry_fn=_call)

    # Apply contact field regex validation
    extraction = _validate_contact_field(extraction)

    logger.info(
        "Extraction: extracted=%s unclear=%s",
        list(extraction.extracted.keys()),
        extraction.unclear_fields,
    )
    return extraction
