"""
Generator layer — streaming LLM responses for both FAQ and proposal generation.

FAQ path:    generate_faq()     → streams FAQGenerationOutput tokens
Proposal path: generate_proposal() → streams ProposalSectionOutput tokens sequentially
                                      across all sections, then builds PDF.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, List, Optional

from openai import AsyncOpenAI

from app.config_loader import config
from app.models.output_models import (
    ChunkResult,
    FAQGenerationOutput,
    ProposalOutput,
    ProposalSectionOutput,
)
from app.models.pricing_models import PricingOutput
from app.models.session_state import SessionState
from app.utils import EscalationException, validate_or_escalate

logger = logging.getLogger(__name__)
_client = AsyncOpenAI()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _format_chunks(chunks: List[ChunkResult]) -> str:
    """Format retrieved chunks as labelled context blocks."""
    if not chunks:
        return "(No context available)"
    parts = []
    for chunk in sorted(chunks, key=lambda c: c.score, reverse=True):
        parts.append(f"[{chunk.section_title}]\n{chunk.content}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# FAQ generation
# ---------------------------------------------------------------------------

def _build_faq_system_prompt(chunks: List[ChunkResult]) -> str:
    context = _format_chunks(chunks)
    return f"""You are the {config.company.company_name} assistant.

Answer the user's question using ONLY the context sections provided below.
If the answer is not in the context, say: "I don't have that information. Would you like to connect with our team?"
Do not invent or infer facts. Always cite the section title(s) you used in the citations field.

CONTEXT:
{context}

Return ONLY valid JSON matching this schema:
{{
  "response": "Your answer here",
  "citations": ["Section Title 1", "Section Title 2"],
  "confidence": "high|medium|low",
  "escalate": false
}}"""


async def generate_faq(
    message: str,
    chunks: List[ChunkResult],
    session: SessionState,
) -> AsyncIterator[str]:
    """
    Stream an FAQ response grounded in retrieved chunks.
    Yields raw token strings for SSE. Validates assembled JSON at end.
    """
    system_prompt = _build_faq_system_prompt(chunks)
    full_response = ""

    stream = await _client.chat.completions.create(
        model=config.company.models.faq_generation,
        messages=[
            {"role": "system", "content": system_prompt},
            *session.conversation_history[-6:],
            {"role": "user", "content": message},
        ],
        response_format={"type": "json_object"},
        stream=True,
        temperature=0.3,
    )

    async for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        if token:
            full_response += token
            yield token

    # Validate assembled response — EscalationException propagates to flow_controller
    faq_output = validate_or_escalate(full_response, FAQGenerationOutput, max_retries=0)

    # Update conversation history with the parsed response text
    session.conversation_history.append({
        "role": "assistant",
        "content": faq_output.response,
    })

    logger.info(
        "FAQ generation: citations=%s confidence=%s escalate=%s",
        faq_output.citations,
        faq_output.confidence,
        faq_output.escalate,
    )

    # Signal escalation to caller via attribute on the generator
    # (caller checks session.escalation_triggered after iteration)
    if faq_output.escalate:
        session.escalation_triggered = True


# ---------------------------------------------------------------------------
# Proposal section generation
# ---------------------------------------------------------------------------

def _build_proposal_section_prompt(
    section_id: str,
    section_title: str,
    prompt_instruction: str,
    collected_slots: dict,
    chunks: List[ChunkResult],
    pricing_output: Optional[PricingOutput],
    client_name: str,
) -> str:
    context = _format_chunks(chunks)
    slots_json = json.dumps(collected_slots, indent=2, default=str)

    base = f"""You are writing the "{section_title}" section of a proposal for {client_name}.
Company: {config.company.company_name} | Currency: {config.company.currency}

{prompt_instruction}

Rules:
- Use ONLY the slot data and retrieved context provided below.
- Do not invent facts, pricing, or specifications.
- Write in clear, professional English.
- Keep the section focused — do not repeat information from other sections.

SLOT DATA:
{slots_json}

CONTEXT:
{context}
"""

    if pricing_output and pricing_output.matched:
        pricing_block = json.dumps({
            "price_min": pricing_output.price_min,
            "price_max": pricing_output.price_max,
            "unit": pricing_output.unit,
            "assumptions": pricing_output.assumptions,
            "disclaimer": pricing_output.disclaimer,
        }, indent=2)
        base += f"""
PRICING (use these exact numbers — do not modify):
{pricing_block}

IMPORTANT: Present price_min and price_max exactly as given. Do not alter numbers.
Include the disclaimer verbatim at the end of this section.
"""

    base += f"""
Return ONLY valid JSON:
{{
  "id": "{section_id}",
  "title": "{section_title}",
  "content": "Full section content here"
}}"""

    return base


async def _generate_section_with_stream(
    section_id: str,
    section_title: str,
    prompt_instruction: str,
    collected_slots: dict,
    chunks: List[ChunkResult],
    pricing_output: Optional[PricingOutput],
    client_name: str,
    session: SessionState,
) -> tuple[ProposalSectionOutput, str]:
    """
    Generate a single proposal section. Returns (ProposalSectionOutput, full_raw_json).
    Streams tokens; caller yields them.
    """
    system_prompt = _build_proposal_section_prompt(
        section_id=section_id,
        section_title=section_title,
        prompt_instruction=prompt_instruction,
        collected_slots=collected_slots,
        chunks=chunks,
        pricing_output=pricing_output,
        client_name=client_name,
    )

    full_response = ""
    tokens_buffer: list[str] = []

    stream = await _client.chat.completions.create(
        model=config.company.models.proposal_generation,
        messages=[
            {"role": "system", "content": system_prompt},
        ],
        response_format={"type": "json_object"},
        stream=True,
        temperature=0.4,
    )

    async for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        if token:
            full_response += token
            tokens_buffer.append(token)

    # Validate with retry
    attempts = 0
    while attempts <= 2:
        try:
            section_output = validate_or_escalate(
                full_response, ProposalSectionOutput, max_retries=0
            )
            return section_output, "".join(tokens_buffer)
        except EscalationException:
            attempts += 1
            if attempts > 2:
                raise
            # Retry the LLM call
            logger.warning("Retrying proposal section %s (attempt %d)", section_id, attempts + 1)
            retry_response = await _client.chat.completions.create(
                model=config.company.models.proposal_generation,
                messages=[{"role": "system", "content": system_prompt}],
                response_format={"type": "json_object"},
                temperature=0.4,
            )
            full_response = retry_response.choices[0].message.content
            tokens_buffer = [full_response]

    raise EscalationException(f"Proposal section {section_id} failed after 2 retries")


async def generate_proposal(
    session: SessionState,
    chunks: List[ChunkResult],
    pricing_output: PricingOutput,
) -> AsyncIterator[str]:
    """
    Generate all proposal sections sequentially. Yields tokens for SSE streaming.
    After all sections are generated, builds PDF and updates leads.
    Raises EscalationException if any section fails after retries.
    """
    # Import here to avoid circular imports
    from app.layers import pdf_builder
    import app.leads as leads

    sections = config.proposal_template.sections
    proposal_sections: List[ProposalSectionOutput] = []
    client_name = session.collected_slots.get("client_name", "Client")

    for section in sections:
        logger.info("Generating proposal section: %s", section.id)

        # PricingOutput injected ONLY into the pricing section
        section_pricing = pricing_output if section.id == "pricing" else None

        section_output, tokens_str = await _generate_section_with_stream(
            section_id=section.id,
            section_title=section.title,
            prompt_instruction=section.prompt_instruction,
            collected_slots=session.collected_slots,
            chunks=chunks,
            pricing_output=section_pricing,
            client_name=client_name,
            session=session,
        )

        proposal_sections.append(section_output)

        # Stream tokens for this section
        for char in tokens_str:
            yield char

    # Assemble full proposal
    proposal = ProposalOutput(
        sections=proposal_sections,
        client_name=client_name,
        generated_at=datetime.utcnow().isoformat(),
    )

    # Build PDF synchronously (WeasyPrint is sync)
    pdf_path = pdf_builder.build_pdf(proposal, config.company, session.session_id)
    logger.info("PDF written to: %s", pdf_path)

    # Lead Write Op 3
    leads.update_proposal_generated(client_name)

    session.proposal_ready = True
    session.collected_slots["_proposal"] = proposal.dict()

    logger.info("Proposal generation complete for session %s", session.session_id)
