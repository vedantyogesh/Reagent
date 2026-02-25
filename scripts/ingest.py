"""
Knowledge base ingestion — run once at deploy-time.
Re-run whenever knowledge_base/ions_energy.md changes.

Steps:
  1. Load knowledge_base/ions_energy.md via LangChain TextLoader
  2. Split into chunks by H2/H3 headings (MarkdownHeaderTextSplitter)
  3. Enrich each chunk with metadata (section_title, user_type_relevance, topic_tags)
  4. Embed each chunk with text-embedding-3-small
  5. Upsert to Pinecone
  6. Verify chunk count matches expected

Usage:
  python scripts/ingest.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import MarkdownHeaderTextSplitter
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone, ServerlessSpec

KNOWLEDGE_BASE_PATH = Path("knowledge_base/ions_energy.md")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# ---------------------------------------------------------------------------
# Section metadata — update this dict when new sections are added to the KB.
# slug → { user_type_relevance, topic_tags }
# ---------------------------------------------------------------------------
SECTION_METADATA: dict[str, dict] = {
    "about-the-company": {
        "user_type_relevance": ["enterprise", "smb", "individual"],
        "topic_tags": ["about", "company", "overview"],
    },
    "our-team": {
        "user_type_relevance": ["enterprise", "smb", "individual"],
        "topic_tags": ["team", "people", "credentials"],
    },
    "battery-energy-storage-bes": {
        "user_type_relevance": ["enterprise", "smb", "individual"],
        "topic_tags": ["bes", "battery", "storage", "backup"],
    },
    "solar-solutions": {
        "user_type_relevance": ["enterprise", "smb", "individual"],
        "topic_tags": ["solar", "panels", "pv", "rooftop"],
    },
    "hybrid-systems": {
        "user_type_relevance": ["enterprise", "smb", "individual"],
        "topic_tags": ["hybrid", "solar", "bes", "storage"],
    },
    "why-choose-ions-energy": {
        "user_type_relevance": ["enterprise", "smb", "individual"],
        "topic_tags": ["why", "differentiator", "value", "quality"],
    },
    "bes-vs-diesel-generator-dg": {
        "user_type_relevance": ["enterprise", "smb"],
        "topic_tags": ["bes", "diesel", "dg", "comparison", "backup"],
    },
    "pricing-overview": {
        "user_type_relevance": ["enterprise", "smb", "individual"],
        "topic_tags": ["pricing", "cost", "budget", "estimate"],
    },
    "faqs-for-homeowners": {
        "user_type_relevance": ["individual"],
        "topic_tags": ["faq", "homeowner", "residential", "solar", "battery"],
    },
    "faqs-for-businesses": {
        "user_type_relevance": ["enterprise", "smb"],
        "topic_tags": ["faq", "business", "commercial", "solar", "finance"],
    },
    "contact-and-next-steps": {
        "user_type_relevance": ["enterprise", "smb", "individual"],
        "topic_tags": ["contact", "next-steps", "sales", "process"],
    },
}

DEFAULT_METADATA = {
    "user_type_relevance": ["enterprise", "smb", "individual"],
    "topic_tags": ["general"],
}


def _slugify(text: str) -> str:
    """Convert a heading title to a slug for metadata lookup."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _get_section_metadata(section_title: str) -> dict:
    slug = _slugify(section_title)
    return SECTION_METADATA.get(slug, DEFAULT_METADATA)


def _ensure_index(pc: Pinecone, index_name: str) -> Any:
    """Create the Pinecone index if it doesn't exist."""
    existing = [idx.name for idx in pc.list_indexes()]
    if index_name not in existing:
        print(f"Creating Pinecone index: {index_name}")
        pc.create_index(
            name=index_name,
            dimension=EMBEDDING_DIMENSIONS,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        print("Index created.")
    else:
        print(f"Using existing Pinecone index: {index_name}")
    return pc.Index(index_name)


def run() -> None:
    print("=== Ions Energy Knowledge Base Ingestion ===\n")

    # Validate environment
    for var in ("OPENAI_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX_NAME"):
        if not os.environ.get(var):
            raise EnvironmentError(f"Missing required environment variable: {var}")

    index_name = os.environ["PINECONE_INDEX_NAME"]

    # Step 1 — Load
    print(f"Loading: {KNOWLEDGE_BASE_PATH}")
    loader = TextLoader(str(KNOWLEDGE_BASE_PATH), encoding="utf-8")
    docs = loader.load()
    print(f"Loaded {len(docs)} document(s)")

    # Step 2 — Split by H2 and H3 headings
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("##", "h2"), ("###", "h3")],
        strip_headers=False,
    )
    chunks = splitter.split_text(docs[0].page_content)
    print(f"Split into {len(chunks)} chunks")

    # Step 3 — Enrich metadata
    records = []
    for i, chunk in enumerate(chunks):
        # Prefer h3 title, fall back to h2
        section_title = chunk.metadata.get("h3") or chunk.metadata.get("h2") or "General"
        slug = _slugify(section_title)
        meta = _get_section_metadata(section_title)
        chunk_id = f"{slug}-{i:03d}"

        records.append({
            "id": chunk_id,
            "text": chunk.page_content,
            "metadata": {
                "chunk_id": chunk_id,
                "section_title": section_title,
                "content": chunk.page_content,   # stored for retrieval injection
                "user_type_relevance": meta["user_type_relevance"],
                "topic_tags": meta["topic_tags"],
            },
        })
        print(f"  [{i+1:2d}] {chunk_id} ({len(chunk.page_content)} chars)")

    # Step 4 — Embed
    print(f"\nEmbedding {len(records)} chunks with {EMBEDDING_MODEL}...")
    embeddings_model = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    texts = [r["text"] for r in records]
    vectors = embeddings_model.embed_documents(texts)
    print(f"Embeddings generated: {len(vectors)} x {len(vectors[0])} dims")

    # Step 5 — Upsert to Pinecone
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = _ensure_index(pc, index_name)

    upsert_data = [
        (r["id"], v, r["metadata"])
        for r, v in zip(records, vectors)
    ]

    # Upsert in batches of 100
    batch_size = 100
    for start in range(0, len(upsert_data), batch_size):
        batch = upsert_data[start:start + batch_size]
        index.upsert(vectors=batch)
        print(f"Upserted batch {start // batch_size + 1}: {len(batch)} vectors")

    # Step 6 — Verify
    stats = index.describe_index_stats()
    total_vectors = stats.total_vector_count
    print(f"\nIndex now contains {total_vectors} total vectors")

    if total_vectors < len(records):
        raise RuntimeError(
            f"Vector count mismatch: expected >= {len(records)}, got {total_vectors}"
        )

    print(f"\n✓ Ingestion complete — {len(records)} chunks upserted to '{index_name}'")


if __name__ == "__main__":
    run()
