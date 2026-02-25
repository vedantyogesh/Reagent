# RAG Pipeline — Ions Energy Config-Driven Chatbot

**Version:** 2.0
**Status:** Approved
**Spec Reference:** `docs/spec.md` §8.2

---

## 1. Overview

The RAG (Retrieval-Augmented Generation) pipeline grounds all chatbot responses in verified company content. It has two phases:

- **Ingestion** (`scripts/ingest.py`) — run once at deploy-time, re-run on knowledge base updates. Parses, chunks, embeds, and upserts the knowledge base to Pinecone.
- **Retrieval** (`app/layers/retrieval.py`) — called at runtime per conversation turn. Pre-filters, embeds the query, and returns the top-5 most relevant chunks to the generation layer.

The LLM is **never** shown the full knowledge base. It only ever receives the chunks returned by retrieval.

---

## 2. Knowledge Base

### 2.1 Source File

**Path:** `knowledge_base/ions_energy.md`

Single Markdown file. Heading structure drives chunking. Every section must be self-contained — no cross-references between sections. Plain factual language.

### 2.2 Required Heading Structure

```markdown
# Ions Energy — Knowledge Base

## About the Company
## Our Team
## Products and Solutions
### Battery Energy Storage (BES)
### Solar Solutions
### Hybrid Systems
## Why Choose Ions Energy
## BES vs Diesel Generator (DG)
## Pricing Overview
## FAQs
### For Homeowners
### For Businesses
## Contact and Next Steps
```

### 2.3 Section Authoring Rules

| Rule | Rationale |
|---|---|
| Each section fully self-contained | A retrieved chunk must be useful without needing adjacent sections |
| No cross-references ("see above", "as mentioned in…") | Retrieval pulls individual chunks; cross-references break in isolation |
| Plain factual language, no LLM-style elaboration | Reduces hallucination risk when the LLM paraphrases retrieved content |
| Pricing data lives in `## Pricing Overview` only | Prevents pricing leaking into FAQ or product chunks and being cited incorrectly |
| User-type relevance should be evident per section | Drives metadata tagging at ingestion time |

---

## 3. Chunking Strategy

**Method:** Semantic chunking by Markdown heading level.

| Heading level | Creates a chunk? | Notes |
|---|---|---|
| `# H1` | No | Document title; not a chunk |
| `## H2` | Yes — if it has no H3 children | Entire H2 content becomes one chunk |
| `## H2` with H3 children | No — parent only | H2 preamble is merged into first H3 chunk |
| `### H3` | Yes — always | Each H3 and its content is one chunk |

**Rationale:** H2/H3 headings in `ions_energy.md` correspond to distinct topics. Splitting at headings preserves semantic coherence and avoids cutting a concept mid-sentence (as fixed-size character/token chunking would).

**Implementation notes (`scripts/ingest.py`):**
- Parse the Markdown file sequentially, tracking current H2 and H3 context.
- When an H3 is encountered, flush any accumulated H2 preamble into that H3 chunk.
- Chunk text = heading title + body content under that heading.
- No overlap between chunks (topic boundaries are natural break points).
- Strip leading/trailing whitespace from each chunk before embedding.

**LangChain component used:** `langchain.document_loaders.TextLoader` (load file) + `langchain.text_splitter.MarkdownHeaderTextSplitter` (split by headings). The splitter preserves heading metadata automatically.

---

## 4. Chunk Metadata Schema

Every chunk upserted to Pinecone carries the following metadata:

```json
{
  "chunk_id": "solutions-bes-001",
  "section_title": "Battery Energy Storage (BES)",
  "content": "...",
  "user_type_relevance": ["enterprise", "smb", "individual"],
  "topic_tags": ["bes", "battery", "storage", "backup"]
}
```

| Field | Type | Source | Purpose |
|---|---|---|---|
| `chunk_id` | `string` | Generated at ingest: `{slugified-section-title}-{index}` | Stable identifier; returned in retrieval results |
| `section_title` | `string` | Heading text from Markdown | Injected as label in LLM prompt (e.g., `[Battery Energy Storage (BES)]`) |
| `content` | `string` | Chunk body text | Stored for direct injection into prompts — Pinecone metadata |
| `user_type_relevance` | `string[]` | Manually tagged in `ingest.py` mapping or inferred by heuristic | Drives metadata pre-filter at retrieval time |
| `topic_tags` | `string[]` | Manually tagged or derived from section title words | Secondary filter and debug aid |

> **Tagging convention:** The `ingest.py` script maintains a small `SECTION_METADATA` dict that maps section slugs to relevance arrays. This is the only place where tagging logic lives. It is **not** config-driven — it is part of the ingest script and must be updated when new sections are added to the knowledge base.

---

## 5. Embedding Model

| Property | Value |
|---|---|
| Model | `text-embedding-3-small` |
| Provider | OpenAI API |
| Output dimensions | 1536 |
| Similarity metric | Cosine |
| Usage | Ingestion (chunk embedding) + Retrieval (query embedding) |

The same model is used for both chunk and query embedding to guarantee vector space consistency. The model is **not** read from `company.yaml` — it is hardcoded in both `ingest.py` and `retrieval.py` because changing it would require full re-ingestion and is a system-level concern, not a company config concern.

---

## 6. Pinecone Index

| Property | Value |
|---|---|
| Index name | From `PINECONE_INDEX_NAME` env var (default: `ions-energy`) |
| Tier | Free (Serverless) |
| Dimensions | 1536 (matches `text-embedding-3-small`) |
| Metric | Cosine |
| Namespace | Default (no namespace) |

**Index creation** is handled once manually or via a setup helper in `ingest.py`. The app itself (`app/layers/retrieval.py`) only reads from the index — it never creates or modifies it.

---

## 7. Ingestion Pipeline (`scripts/ingest.py`)

Run once at deploy-time. Re-run whenever `knowledge_base/ions_energy.md` changes.

```
scripts/ingest.py
  │
  ├── Step 1 — Load
  │     TextLoader("knowledge_base/ions_energy.md")
  │     → raw Document
  │
  ├── Step 2 — Split
  │     MarkdownHeaderTextSplitter(headers_to_split_on=["##", "###"])
  │     → List[Document]  (one per H2 or H3 section)
  │
  ├── Step 3 — Enrich metadata
  │     For each Document:
  │       chunk_id         = slugify(section_title) + "-" + str(index)
  │       section_title    = from splitter metadata
  │       user_type_relevance = SECTION_METADATA[slug]["user_type_relevance"]
  │       topic_tags       = SECTION_METADATA[slug]["topic_tags"]
  │       content          = doc.page_content  (stored in metadata for retrieval)
  │
  ├── Step 4 — Embed
  │     OpenAI("text-embedding-3-small").embed_documents([doc.page_content, ...])
  │     → List[List[float]]  (1536-dim vector per chunk)
  │
  ├── Step 5 — Upsert
  │     Pinecone index.upsert(vectors=[
  │       (chunk_id, embedding_vector, metadata_dict),
  │       ...
  │     ])
  │
  └── Step 6 — Verify
        Print: total chunks upserted, index vector count after upsert
        Raise on mismatch (safeguard against silent partial upserts)
```

**Idempotency:** Pinecone upsert is idempotent by `chunk_id`. Re-running `ingest.py` on an unchanged knowledge base is safe — it overwrites existing vectors with identical values.

**On knowledge base update:** Re-run `ingest.py`. Chunks for removed sections will remain in the index as orphans (they will score low and be filtered out). For a clean re-index, delete and recreate the Pinecone index before running.

---

## 8. Retrieval Pipeline (`app/layers/retrieval.py`)

Called at runtime. Returns top-5 chunks to the generation layer.

```
app/layers/retrieval.py  retrieve(query: str, session: SessionState) -> List[ChunkResult]
  │
  ├── Step 1 — Build metadata pre-filter
  │     filter = {}
  │     if session.user_type:
  │       filter["user_type_relevance"] = {"$in": [session.user_type]}
  │     if session.collected_slots.get("project_type"):
  │       filter["topic_tags"] = {"$in": [session.collected_slots["project_type"]]}
  │
  ├── Step 2 — Embed query
  │     OpenAI("text-embedding-3-small").embed_query(query)
  │     → query_vector: List[float]  (1536-dim)
  │
  ├── Step 3 — Vector search
  │     pinecone_index.query(
  │       vector=query_vector,
  │       top_k=5,
  │       filter=filter,         # metadata pre-filter (Step 1)
  │       include_metadata=True
  │     )
  │     → QueryResponse (Pinecone SDK)
  │
  ├── Step 4 — Threshold check
  │     Discard any match where score < SIMILARITY_THRESHOLD (0.70)
  │     If zero chunks remain after filtering → return [] (caller triggers escalation)
  │
  └── Step 5 — Return
        List[ChunkResult]:
          chunk_id:      str   (from metadata)
          section_title: str   (from metadata)
          content:       str   (from metadata)
          score:         float (cosine similarity, 0–1)
```

**Return type** (`app/models/output_models.py` or inline dataclass):
```python
class ChunkResult(BaseModel):
    chunk_id: str
    section_title: str
    content: str
    score: float
```

### 8.1 Similarity Threshold

| Value | Constant | Defined in |
|---|---|---|
| `0.70` | `SIMILARITY_THRESHOLD` | Top of `retrieval.py` (not config — system constant) |

If all returned chunks score below `0.70`, retrieval returns an empty list. The flow controller treats an empty retrieval result as an escalation trigger.

### 8.2 Pre-filter Logic

The metadata pre-filter narrows the search space **before** vector scoring. It is applied progressively — only fields that are known at query time are included:

| Session data available | Filter applied |
|---|---|
| Neither `user_type` nor `project_type` known | No filter — full index searched |
| `user_type` known only | `user_type_relevance` filter only |
| Both `user_type` and `project_type` known | Both filters applied (`$in` on each field) |

> **Why `$in` not equality:** A chunk can be relevant to multiple user types (e.g., "About the Company" is relevant to all three). Using `$in` means the chunk is returned if the session's user_type appears anywhere in the chunk's relevance array.

---

## 9. When Retrieval Is (and Is Not) Triggered

This is a hard rule from the spec. Violating it causes retrieval noise during slot collection.

| Flow state | Retrieval triggered? | Reason |
|---|---|---|
| `INIT` | ❌ No | No meaningful query yet |
| `USER_TYPE_DETECTION` | ❌ No | Classifying user, not answering questions |
| `INTENT_DETECTION` | ❌ No | Intent classification only |
| `SLOT_COLLECTION` | ❌ No | Asking for slot data; context not yet sufficient for grounded retrieval |
| `RETRIEVAL` (FAQ intent) | ✅ Yes | User asked a factual question; retrieve to ground the answer |
| `PROPOSAL_GENERATION` | ✅ Yes | All slots filled; retrieve context to enrich proposal sections |
| `ESCALATED` | ❌ No | Session ending |
| `COMPLETE` | ✅ Yes (if user asks follow-up) | Session open; user may ask questions post-proposal |

---

## 10. How Retrieved Chunks Are Injected into LLM Prompts

Applied in `app/layers/generator.py` for both FAQ and proposal generation.

### 10.1 FAQ Prompt Structure

```
SYSTEM:
  You are the Ions Energy assistant. Answer the user's question using ONLY the
  provided context sections below. If the answer is not found in the context,
  say: "I don't have that information. Would you like to speak with our team?"
  Do not invent or infer facts. Always cite the section title you used.

CONTEXT:
  [About the Company]
  {chunk.content}

  [Battery Energy Storage (BES)]
  {chunk.content}

  ... (up to 5 chunks, each labelled with section_title)

USER:
  {user_message}

OUTPUT FORMAT: FAQGenerationOutput (JSON mode)
```

### 10.2 Proposal Section Prompt Structure

```
SYSTEM:
  You are writing the "{section.title}" section of a proposal for {client_name}.
  Use ONLY the collected slot data and retrieved context below.
  Do not alter pricing numbers — use the exact values from PricingOutput.
  {section.prompt_instruction}

SLOT DATA:
  {collected_slots as JSON}

PRICING:
  {PricingOutput as JSON}   (included only in the "pricing" section)

CONTEXT:
  [Why Choose Ions Energy]
  {chunk.content}

  ... (up to 5 chunks)

OUTPUT FORMAT: ProposalSectionOutput (JSON mode)
```

### 10.3 Prompt Rules

- Every chunk is prefixed with `[{section_title}]` so the LLM can cite its source.
- Chunks are ordered by score descending (most relevant first).
- If fewer than 5 chunks are returned (e.g., strict pre-filter), only the available chunks are injected. The prompt is not padded.
- The full knowledge base document is **never** injected into any prompt.
- Citation in `FAQGenerationOutput.citations` must be a list of `section_title` strings — the LLM is instructed to use exact section_title values from the context headers, not invented labels.

---

## 11. Escalation from Retrieval

Retrieval returns an empty list (all chunks below threshold) → `retrieve()` returns `[]`.

The flow controller in `app/layers/flow_controller.py` checks the return value:

```python
chunks = await retrieve(query, session)
if not chunks:
    session.flow_state = FlowState.ESCALATED
    session.escalation_triggered = True
    return escalation_message  # from company.yaml
```

This is the only escalation path owned by the retrieval layer. All other escalation paths (slot failure, pricing no-match, explicit escalation intent) are handled by the flow controller directly.

---

## 12. Structured Output Enforcement

All retrieval results feed directly into LLM calls. Those LLM calls must return structured output:

| Call | Schema | On malformed output |
|---|---|---|
| FAQ generation | `FAQGenerationOutput` | Retry ≤2 → escalate |
| Proposal section | `ProposalSectionOutput` | Retry ≤2 → escalate |

The retrieval layer itself has no structured output requirement — it returns a typed Python list of `ChunkResult` objects validated by Pydantic.

---

## 13. Re-ingestion Checklist

When `knowledge_base/ions_energy.md` is updated:

1. Review changed/added sections and update `SECTION_METADATA` in `ingest.py` if new sections were added.
2. *(Optional for clean slate)* Delete and recreate the Pinecone index.
3. Run `python scripts/ingest.py`.
4. Verify printed chunk count matches expected section count.
5. Smoke-test with a retrieval query covering the changed content.
