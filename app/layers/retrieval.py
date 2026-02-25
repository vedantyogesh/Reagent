"""
Retrieval layer — embed query, apply metadata pre-filter, return top-5 chunks from Pinecone.

IMPORTANT: EMBEDDING_MODEL is intentionally hardcoded here.
Changing this model requires full re-ingestion of the Pinecone index.
It is not in company.yaml because it is a system coupling constraint, not a config preference.
"""
from __future__ import annotations

import logging
import os
from typing import List

from openai import AsyncOpenAI
from pinecone import Pinecone

from app.models.output_models import ChunkResult
from app.models.session_state import SessionState

logger = logging.getLogger(__name__)

# Hardcoded by design — changing requires full Pinecone re-ingestion.
EMBEDDING_MODEL = "text-embedding-3-small"

# Chunks below this cosine similarity score are discarded.
# This is a system constant, not a config value. Changing it requires
# regression testing across all retrieval scenarios.
SIMILARITY_THRESHOLD = 0.70

_openai_client = AsyncOpenAI()
_pinecone_client: Pinecone | None = None
_pinecone_index = None


def _get_index():
    global _pinecone_client, _pinecone_index
    if _pinecone_index is None:
        _pinecone_client = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        index_name = os.environ.get("PINECONE_INDEX_NAME", "ions-energy")
        _pinecone_index = _pinecone_client.Index(index_name)
    return _pinecone_index


async def retrieve(query: str, session: SessionState) -> List[ChunkResult]:
    """
    Retrieve top-5 relevant chunks for a query.

    Pre-filter is applied progressively:
      - user_type known → filter by user_type_relevance
      - project_type known → also filter by topic_tags

    Returns empty list if no chunks score above SIMILARITY_THRESHOLD.
    An empty return triggers escalation in flow_controller.
    """
    # Build metadata pre-filter
    filter_: dict = {}
    if session.user_type:
        filter_["user_type_relevance"] = {"$in": [session.user_type]}
    if session.collected_slots.get("project_type"):
        project_type = session.collected_slots["project_type"].lower()
        filter_["topic_tags"] = {"$in": [project_type]}

    # Embed query
    embedding_response = await _openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
    )
    query_vector = embedding_response.data[0].embedding

    # Vector search
    index = _get_index()
    results = index.query(
        vector=query_vector,
        top_k=5,
        filter=filter_ if filter_ else None,
        include_metadata=True,
    )

    # Apply threshold filter
    chunks = [
        ChunkResult(
            chunk_id=match.id,
            section_title=match.metadata.get("section_title", ""),
            content=match.metadata.get("content", ""),
            score=match.score,
        )
        for match in results.matches
        if match.score >= SIMILARITY_THRESHOLD
    ]

    logger.info(
        "Retrieval: query=%r filter=%s returned=%d/%d above threshold",
        query[:60],
        filter_,
        len(chunks),
        len(results.matches),
    )

    if not chunks:
        logger.warning("Retrieval returned 0 chunks above threshold — escalation may be triggered")

    return chunks
