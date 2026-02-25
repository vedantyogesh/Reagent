"""
Entry layer — combined classification.
One LLM call returns both user_type and primary_intent (ClassificationOutput).
Never make two separate calls for classification and intent.
"""
from __future__ import annotations

import json
import logging
from typing import List, Dict

from openai import AsyncOpenAI

from app.config_loader import config
from app.models.output_models import ClassificationOutput
from app.models.session_state import SessionState
from app.utils import EscalationException, validate_or_escalate

logger = logging.getLogger(__name__)
_client = AsyncOpenAI()


def _build_classification_prompt() -> str:
    intent_descriptions = "\n".join(
        f"  - {i.name}: {i.description}" for i in config.intents.intents
    )
    return f"""You are a classification assistant for {config.company.company_name}, an energy solutions company.

Your job is to classify an incoming message with TWO outputs:
1. user_type — the type of customer sending the message
2. primary_intent — what the customer wants to do

USER TYPES:
  - enterprise: Large organisations, factories, industrial facilities, companies with many employees
  - smb: Small or medium businesses, shops, offices, restaurants, small factories
  - individual: Homeowners, residents, private individuals looking for home energy solutions
  - unknown: Cannot be determined from the message

INTENTS:
{intent_descriptions}

CONFIDENCE THRESHOLD: {config.intents.confidence_threshold}
If you cannot confidently determine user_type or intent, set the confidence below {config.intents.confidence_threshold}.

Return ONLY valid JSON matching this exact schema:
{{
  "user_type": "enterprise|smb|individual|unknown",
  "user_type_confidence": 0.0-1.0,
  "primary_intent": "intent_name",
  "intent_confidence": 0.0-1.0
}}"""


async def classify(message: str, session: SessionState) -> ClassificationOutput:
    """
    Classify user_type and primary_intent in a single LLM call.
    Uses the last 6 messages of conversation history for context.
    """
    system_prompt = _build_classification_prompt()

    history: List[Dict[str, str]] = session.conversation_history[-6:]

    raw_response = None

    async def _call() -> str:
        nonlocal raw_response
        response = await _client.chat.completions.create(
            model=config.company.models.classification,
            messages=[
                {"role": "system", "content": system_prompt},
                *history,
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        raw_response = response.choices[0].message.content
        return raw_response

    first_raw = await _call()
    result = validate_or_escalate(first_raw, ClassificationOutput, max_retries=2, retry_fn=_call)
    logger.info(
        "Classification: user_type=%s (%.2f) intent=%s (%.2f)",
        result.user_type,
        result.user_type_confidence,
        result.primary_intent,
        result.intent_confidence,
    )
    return result
