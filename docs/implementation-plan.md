# Implementation Plan — Ions Energy Config-Driven Chatbot

**Version:** 2.0
**Status:** Approved
**Spec Reference:** `docs/spec.md` §13
**Prerequisite reading:** `docs/high-level-architecture.md`, `docs/rag-pipeline.md`, `docs/proposal-flow.md`

---

## 0. Standing Rules (Never Violate)

Before touching any step, re-read these. They apply to every line of code written.

- No company name, model name, price, or template content in application code — everything reads from `/config/`.
- LLM never computes prices. `pricing.py` is pure Python from `pricing_rules.yaml`.
- All LLM outputs use JSON mode or function calling. No free-text parsing.
- Session state is in-memory only. No DB writes for conversation history.
- Lead data written to `data/leads.csv` (CSV, not SQLite — confirmed correction to spec §13 step 7).
- One slot question per conversation turn.
- Streaming required for all user-facing LLM responses.
- `config_loader.py` validates all YAML at startup. App refuses to start on invalid config.

---

## 1. Phases Overview

```
Phase 0 — Foundation          Steps  1–2    Repo skeleton + config validation
Phase 1 — Data Layer          Steps  3–7    Knowledge base, Pinecone, models, session, leads
Phase 2 — Core Logic          Steps  8–13   Classification, flow, extraction, retrieval, pricing
Phase 3 — Generation & Output Steps 14–16   Proposal generation, PDF, FastAPI endpoints
Phase 4 — Frontend            Step  17      Embeddable widget
Phase 5 — QA & Deploy         Steps 18–20   Evaluation, deployment
```

Each phase produces a working, testable slice of the system. Do not start Phase N+1 until the acceptance criteria for Phase N are met.

---

## Phase 0 — Foundation

### Step 1 — Repo Structure, CLAUDE.md, `.env.example`, `requirements.txt`

**Creates:**
```
/
├── CLAUDE.md
├── .env.example
├── requirements.txt
├── config/
│   ├── company.yaml
│   ├── slots.yaml
│   ├── intents.yaml
│   ├── pricing_rules.yaml
│   └── proposal_template.yaml
├── knowledge_base/          # empty, populated in Step 3
├── data/                    # empty, leads.csv created on first write
├── tmp/
│   └── proposals/           # empty, PDFs written here at runtime
├── app/
│   ├── layers/
│   └── models/
├── templates/
├── widget/
├── scripts/
├── tests/
└── docs/                    # already populated by planning phase
```

**`requirements.txt` (exact versions — do not use `>=` for core dependencies):**
```
fastapi==0.111.0
uvicorn[standard]==0.29.0
pydantic==2.7.1
pydantic-settings==2.2.1
openai==1.30.1
pinecone-client==3.2.2
langchain==0.2.3
langchain-openai==0.1.8
langchain-community==0.2.3
weasyprint==62.3
python-dotenv==1.0.1
pyyaml==6.0.1
jinja2==3.1.4
python-multipart==0.0.9
sse-starlette==2.1.0
```

**`CLAUDE.md`** — copy from spec §1 verbatim. Update `## Current status` section as each architecture doc is approved.

**Config files** — populate all five YAML files from spec §6 exactly. `pricing_rules.yaml` price values are placeholder zeros (Ions Energy to fill).

**`.env.example`:**
```env
OPENAI_API_KEY=
PINECONE_API_KEY=
PINECONE_INDEX_NAME=ions-energy
SESSION_SECRET=
ENVIRONMENT=development
```

**Acceptance criteria:**
- [ ] All directories exist
- [ ] All five config YAML files present and non-empty
- [ ] `requirements.txt` installs cleanly: `pip install -r requirements.txt`
- [ ] No application code written yet

---

### Step 2 — `app/config_loader.py`

**Creates:** `app/config_loader.py`

**Purpose:** Load and validate all five YAML config files at startup using Pydantic. App refuses to start on any validation error.

**Key classes (all in `config_loader.py`):**

```python
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

class SlotDefinition(BaseModel):
    name: str
    question: str
    type: str                          # "string" | "number"
    input_type: Optional[str] = None   # "contact_form" if present
    validation: Optional[dict] = None

class UserTypeSlots(BaseModel):
    required_slots: List[SlotDefinition]
    optional_slots: List[SlotDefinition] = []

class SlotsConfig(BaseModel):
    user_types: Dict[str, UserTypeSlots]   # keys: enterprise, smb, individual

class IntentDefinition(BaseModel):
    name: str
    description: str
    triggers_flow: str   # "faq" | "proposal" | "escalate"

class IntentsConfig(BaseModel):
    intents: List[IntentDefinition]
    fallback_intent: str
    confidence_threshold: float

class PricingRuleConditions(BaseModel):
    user_type: Optional[str] = None
    project_type: Optional[str] = None
    house_size_sqft_max: Optional[float] = None
    # extend as new condition fields are added to pricing_rules.yaml

class PricingRuleOutput(BaseModel):
    price_min: int
    price_max: int
    unit: str
    assumptions: str

class PricingRule(BaseModel):
    id: str
    conditions: PricingRuleConditions
    output: PricingRuleOutput

class PricingConfig(BaseModel):
    rules: List[PricingRule]
    disclaimer: str

class ProposalSection(BaseModel):
    id: str
    title: str
    prompt_instruction: str

class ProposalTemplateConfig(BaseModel):
    sections: List[ProposalSection]

# Top-level loader — called once at startup
class AppConfig(BaseModel):
    company: CompanyConfig
    slots: SlotsConfig
    intents: IntentsConfig
    pricing: PricingConfig
    proposal_template: ProposalTemplateConfig

def load_config() -> AppConfig:
    # Load each YAML file, parse, validate, return AppConfig
    # Raise ValueError with clear message on any validation error
    ...

# Module-level singleton — imported by all layers
config: AppConfig = load_config()
```

**Startup hook** in `app/main.py` (written in Step 16) will import `config` at module load time, causing validation to run before any request is handled.

**Acceptance criteria:**
- [ ] `python -c "from app.config_loader import config; print(config.company.company_name)"` prints `"Ions Energy"`
- [ ] Corrupt a YAML field → `load_config()` raises `ValueError` with the offending field named
- [ ] All five config files parsed without error on current YAML

---

## Phase 1 — Data Layer

### Step 3 — `knowledge_base/ions_energy.md`

**Creates:** `knowledge_base/ions_energy.md`

**Required heading structure** (from spec §8.2 and `docs/rag-pipeline.md` §2.2):
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

**Authoring rules** (enforced at review time, not in code):
- Every section fully self-contained — no cross-references
- Pricing data only under `## Pricing Overview`
- User-type relevance evident per section (drives metadata tagging in Step 4)
- Plain factual language

**Acceptance criteria:**
- [ ] File exists with all required H2 and H3 headings present
- [ ] No section contains cross-references ("see above", "as mentioned in…")
- [ ] `## Pricing Overview` is the only section containing price figures

---

### Step 4 — `scripts/ingest.py`

**Creates:** `scripts/ingest.py`

**Purpose:** Parse knowledge base → chunk → embed → upsert to Pinecone. Run once at deploy-time.

**`SECTION_METADATA` mapping** (update when sections are added):
```python
SECTION_METADATA: Dict[str, dict] = {
    "about-the-company":              {"user_type_relevance": ["enterprise", "smb", "individual"], "topic_tags": ["about", "company", "overview"]},
    "our-team":                       {"user_type_relevance": ["enterprise", "smb", "individual"], "topic_tags": ["team", "people"]},
    "battery-energy-storage-bes":     {"user_type_relevance": ["enterprise", "smb", "individual"], "topic_tags": ["bes", "battery", "storage", "backup"]},
    "solar-solutions":                {"user_type_relevance": ["enterprise", "smb", "individual"], "topic_tags": ["solar", "panels", "pv"]},
    "hybrid-systems":                 {"user_type_relevance": ["enterprise", "smb"],              "topic_tags": ["hybrid", "solar", "bes"]},
    "why-choose-ions-energy":         {"user_type_relevance": ["enterprise", "smb", "individual"], "topic_tags": ["why", "differentiator", "value"]},
    "bes-vs-diesel-generator-dg":     {"user_type_relevance": ["enterprise", "smb"],              "topic_tags": ["bes", "diesel", "dg", "comparison"]},
    "pricing-overview":               {"user_type_relevance": ["enterprise", "smb", "individual"], "topic_tags": ["pricing", "cost", "budget"]},
    "faqs-for-homeowners":            {"user_type_relevance": ["individual"],                     "topic_tags": ["faq", "homeowner", "residential"]},
    "faqs-for-businesses":            {"user_type_relevance": ["enterprise", "smb"],              "topic_tags": ["faq", "business", "commercial"]},
    "contact-and-next-steps":         {"user_type_relevance": ["enterprise", "smb", "individual"], "topic_tags": ["contact", "next-steps", "sales"]},
}
```

**Implementation steps** (see `docs/rag-pipeline.md` §7 for full detail):
1. `TextLoader` → load `knowledge_base/ions_energy.md`
2. `MarkdownHeaderTextSplitter(headers_to_split_on=["##", "###"])` → split into chunks
3. For each chunk: assign `chunk_id` (slugified title + index), look up `SECTION_METADATA`, store `content` in metadata
4. `OpenAIEmbeddings(model="text-embedding-3-small")` → embed all chunks
5. `pinecone.Index(PINECONE_INDEX_NAME).upsert(vectors=[...])` → upsert
6. Print chunk count; raise if index vector count doesn't match

**Acceptance criteria:**
- [ ] `python scripts/ingest.py` completes without error
- [ ] Printed chunk count matches expected section count (≥11 chunks for current knowledge base)
- [ ] Pinecone console shows correct vector count after run
- [ ] Re-running is idempotent (no duplicate vectors — same `chunk_id` overwrites)

---

### Step 5 — `app/models/`

**Creates:**
- `app/models/session_state.py`
- `app/models/slot_models.py`
- `app/models/output_models.py`
- `app/models/pricing_models.py`
- `app/models/lead_models.py`

**Implement exactly as specified in spec §7.** Key notes:

**`session_state.py`** — `FlowState` enum + `SessionState`. Copy from spec §7.1 verbatim. No additions yet.

**`slot_models.py`** — Dynamic slot schema helpers:
```python
def get_required_slots(user_type: str, slots_config: SlotsConfig) -> List[str]:
    """Return ordered list of required slot names for a user_type.
    client_name is always index 0, contact always index 1."""
    slots = slots_config.user_types[user_type].required_slots
    ordered = sorted(slots, key=lambda s: (
        0 if s.name == "client_name" else
        1 if s.name == "contact" else
        2
    ))
    return [s.name for s in ordered]

def get_slot_definition(slot_name: str, user_type: str, slots_config: SlotsConfig) -> SlotDefinition:
    all_slots = (slots_config.user_types[user_type].required_slots +
                 slots_config.user_types[user_type].optional_slots)
    return next(s for s in all_slots if s.name == slot_name)
```

**`output_models.py`** — `ClassificationOutput`, `ExtractionOutput`, `FAQGenerationOutput`, `ProposalSectionOutput`, `ProposalOutput`, `ChunkResult`. Copy from spec §7.4.

**`pricing_models.py`** — `PricingInput`, `PricingOutput`. Copy from spec §7.3.

**`lead_models.py`** — `LeadRecord`. Copy from spec §7.2. Fix the `@validator` to Pydantic v2 `@model_validator` syntax.

**Acceptance criteria:**
- [ ] `python -c "from app.models.session_state import SessionState, FlowState; s = SessionState(session_id='test'); print(s.flow_state)"` → prints `FlowState.INIT`
- [ ] All model imports resolve without error
- [ ] `LeadRecord(client_name="Test", user_type="individual", captured_at=datetime.utcnow())` instantiates without error

---

### Step 6 — `app/session.py`

**Creates:** `app/session.py`

**Purpose:** In-memory session store. No persistence.

```python
class SessionStore:
    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}

    def create(self) -> SessionState:
        session_id = str(uuid.uuid4())
        session = SessionState(session_id=session_id)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[SessionState]:
        return self._sessions.get(session_id)

    def get_or_raise(self, session_id: str) -> SessionState:
        session = self.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    def delete(self, session_id: str) -> bool:
        # Also deletes tmp/proposals/{session_id}.pdf if it exists
        pdf_path = Path(f"tmp/proposals/{session_id}.pdf")
        if pdf_path.exists():
            pdf_path.unlink()
        return bool(self._sessions.pop(session_id, None))

    def cleanup_expired(self):
        """Called by background task. Removes sessions past session_timeout_minutes."""
        timeout = config.company.session_timeout_minutes
        cutoff = datetime.utcnow() - timedelta(minutes=timeout)
        expired = [
            sid for sid, s in self._sessions.items()
            if s.created_at < cutoff   # add created_at field to SessionState
        ]
        for sid in expired:
            self.delete(sid)

# Module-level singleton
store = SessionStore()
```

**Add `created_at: datetime` field to `SessionState`** with `default_factory=datetime.utcnow`.

**Acceptance criteria:**
- [ ] `store.create()` returns a `SessionState` with unique `session_id`
- [ ] `store.get(unknown_id)` returns `None`
- [ ] `store.delete(session_id)` removes session and deletes PDF if present
- [ ] `store.cleanup_expired()` removes sessions older than `session_timeout_minutes`

---

### Step 7 — `app/leads.py`

**Creates:** `app/leads.py`, `data/leads.csv` (on first write)

**Storage:** CSV via stdlib `csv`. Not SQLite. Columns: `client_name, email, phone, user_type, captured_at, proposal_generated`.

```python
LEADS_PATH = Path("data/leads.csv")
FIELDNAMES = ["client_name", "email", "phone", "user_type", "captured_at", "proposal_generated"]

def _ensure_file():
    """Create data/leads.csv with header row if it doesn't exist."""
    LEADS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LEADS_PATH.exists():
        with open(LEADS_PATH, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

def append_row(record: LeadRecord) -> None:
    """Write Op 1: append new row on client_name extraction."""
    _ensure_file()
    with open(LEADS_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow({
            "client_name":        record.client_name,
            "email":              record.email or "",
            "phone":              record.phone or "",
            "user_type":          record.user_type,
            "captured_at":        record.captured_at.isoformat(),
            "proposal_generated": str(record.proposal_generated),
        })

def update_contact(client_name: str, email: Optional[str], phone: Optional[str]) -> None:
    """Write Op 2: update email/phone once validated."""
    _rewrite_matching(client_name, {"email": email or "", "phone": phone or ""})

def update_proposal_generated(client_name: str) -> None:
    """Write Op 3: set proposal_generated=True after PDF is created."""
    _rewrite_matching(client_name, {"proposal_generated": "True"})

def _rewrite_matching(client_name: str, updates: dict) -> None:
    """Read all rows, update matching, rewrite file."""
    _ensure_file()
    rows = []
    with open(LEADS_PATH, "r", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if row["client_name"] == client_name:
            row.update(updates)
            break
    with open(LEADS_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
```

**Acceptance criteria:**
- [ ] `append_row(LeadRecord(...))` creates `data/leads.csv` with header + 1 data row
- [ ] `update_contact(...)` updates only the matching row's email/phone
- [ ] `update_proposal_generated(...)` sets `proposal_generated=True` on matching row
- [ ] File opens correctly in Excel/Google Sheets (UTF-8, proper quoting)

---

## Phase 2 — Core Logic

### Step 8 — `app/layers/entry.py`

**Creates:** `app/layers/entry.py`

**Purpose:** Single LLM call → `ClassificationOutput` (user_type + primary_intent).

```python
async def classify(message: str, session: SessionState) -> ClassificationOutput:
    system_prompt = build_classification_prompt(config)
    # system_prompt includes:
    #   - user type descriptions (enterprise / smb / individual)
    #   - intent names and descriptions from intents.yaml
    #   - instruction to return JSON matching ClassificationOutput schema
    #   - confidence_threshold from intents.yaml (for self-guidance only)

    response = await openai_client.chat.completions.create(
        model    = config.company.models.classification,
        messages = [
            {"role": "system", "content": system_prompt},
            *session.conversation_history,
            {"role": "user",   "content": message},
        ],
        response_format = {"type": "json_object"},
    )
    return validate_or_escalate(response, ClassificationOutput)
```

**Clarification logic** (in flow_controller, informed by entry.py output):
- If `user_type_confidence < config.intents.confidence_threshold` → flow stays `USER_TYPE_DETECTION`, bot asks: *"Are you looking for a solution for your home, a small business, or a large enterprise?"*
- If `intent_confidence < confidence_threshold` → use `fallback_intent` (general_faq) silently

**One call, two outputs. Never two separate calls.**

**Acceptance criteria:**
- [ ] Returns valid `ClassificationOutput` for a clear enterprise message
- [ ] Returns `user_type_confidence < 0.70` for a vague opener ("hi")
- [ ] Raises after 2 retries on malformed JSON (mock OpenAI to return bad JSON)

---

### Step 9 — `app/layers/flow_controller.py`

**Creates:** `app/layers/flow_controller.py`

**Purpose:** State machine. Every `FlowState` transition lives here. No business logic elsewhere overrides this.

```python
async def advance(session: SessionState, message: str) -> FlowResponse:
    """
    Main entry point for every /chat request.
    Returns FlowResponse(reply: str, stream: AsyncIterator, done_payload: DonePayload).
    """
    ...

class DonePayload(BaseModel):
    flow_state:     str
    proposal_ready: bool
    escalated:      bool
    input_type:     Optional[str]   # None | "contact_form"
```

**State transition table** (implement as a match/case or dict dispatch):

| Current state | Condition | Action | Next state |
|---|---|---|---|
| `INIT` | First message received | Call `entry.classify()` | `USER_TYPE_DETECTION` |
| `USER_TYPE_DETECTION` | `user_type_confidence >= threshold` | Populate `missing_slots` | `INTENT_DETECTION` |
| `USER_TYPE_DETECTION` | `user_type_confidence < threshold` | Emit clarification question | `USER_TYPE_DETECTION` |
| `INTENT_DETECTION` | Intent is `faq` | | `RETRIEVAL` |
| `INTENT_DETECTION` | Intent is `proposal` or `pricing` | | `SLOT_COLLECTION` |
| `INTENT_DETECTION` | Intent is `escalation` | | `ESCALATED` |
| `SLOT_COLLECTION` | `missing_slots` not empty | Ask next slot; set `input_type:"contact_form"` if slot is `contact` | `SLOT_COLLECTION` |
| `SLOT_COLLECTION` | `slot_attempt_counts[any] >= 2` | | `ESCALATED` |
| `SLOT_COLLECTION` | `missing_slots == []` | | `RETRIEVAL` |
| `RETRIEVAL` | (FAQ path) chunks returned | | `GENERATION` |
| `RETRIEVAL` | (Proposal path) chunks returned | | `PROPOSAL_GENERATION` |
| `RETRIEVAL` | chunks empty | | `ESCALATED` |
| `GENERATION` | Response streamed | Await next message | `INTENT_DETECTION` |
| `PROPOSAL_GENERATION` | All sections + PDF complete | | `COMPLETE` |
| `PROPOSAL_GENERATION` | Any generation/PDF error | | `ESCALATED` |
| `COMPLETE` | Follow-up message | | `INTENT_DETECTION` |
| `ESCALATED` | — | Emit escalation_message, disable input | terminal |

**`missing_slots` initialisation** (when entering `SLOT_COLLECTION`):
```python
session.missing_slots = get_required_slots(session.user_type, config.slots)
# client_name always first, contact always second
```

**Acceptance criteria:**
- [ ] Starting from `INIT`, a clear enterprise+proposal message reaches `SLOT_COLLECTION` in one advance() call
- [ ] `slot_attempt_counts["client_name"] = 2` triggers `ESCALATED`
- [ ] `missing_slots == []` after all slots filled transitions to `RETRIEVAL`

---

### Step 10 — `app/layers/extractor.py`

**Creates:** `app/layers/extractor.py`

**Purpose:** Extract slot values from a user message using LLM. Validate contact fields with regex.

```python
CONTACT_REGEXES = {
    "email": re.compile(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$'),
    "phone": re.compile(r'^[6-9]\d{9}$'),   # Indian mobile
}

async def extract(
    message: str,
    target_slots: List[str],
    collected_slots: Dict[str, Any],
    session: SessionState,
) -> ExtractionOutput:
    system_prompt = build_extraction_prompt(target_slots, config.slots)
    response = await openai_client.chat.completions.create(
        model    = config.company.models.extraction,
        messages = [
            {"role": "system", "content": system_prompt},
            *session.conversation_history[-6:],   # last 3 turns only — keep prompt small
            {"role": "user", "content": message},
        ],
        response_format = {"type": "json_object"},
    )
    extraction = validate_or_escalate(response, ExtractionOutput)

    # Post-extraction: validate contact fields with regex
    if "contact" in extraction.extracted:
        extraction = _validate_contact(extraction)

    return extraction

def _validate_contact(extraction: ExtractionOutput) -> ExtractionOutput:
    """
    Move email/phone from extracted to unclear_fields if they fail regex.
    At least one of email or phone must pass.
    """
    raw = str(extraction.extracted["contact"].value)
    email_match = CONTACT_REGEXES["email"].match(raw)
    phone_match = CONTACT_REGEXES["phone"].match(raw)

    if email_match:
        extraction.extracted["email"] = ExtractedField(value=email_match.group(), confidence=1.0)
    if phone_match:
        extraction.extracted["phone"] = ExtractedField(value=phone_match.group(), confidence=1.0)

    if not email_match and not phone_match:
        extraction.unclear_fields.append("contact")

    del extraction.extracted["contact"]   # replace with email/phone keys
    return extraction
```

**Acceptance criteria:**
- [ ] `"My name is Priya"` → `extracted["client_name"].value == "Priya"`
- [ ] `"priya@example.com"` → `extracted["email"].value == "priya@example.com"`
- [ ] `"9876543210"` → `extracted["phone"].value == "9876543210"`
- [ ] `"notaphone"` → `unclear_fields == ["contact"]`
- [ ] `"123456"` (invalid Indian mobile) → `unclear_fields == ["contact"]`

---

### Step 11 — `app/layers/retrieval.py`

**Creates:** `app/layers/retrieval.py`

**Purpose:** Embed query → Pinecone search with metadata pre-filter → return top-5 `ChunkResult` objects above threshold.

```python
SIMILARITY_THRESHOLD = 0.70
# Changing this model requires full re-ingestion of the Pinecone index.
EMBEDDING_MODEL = "text-embedding-3-small"

async def retrieve(query: str, session: SessionState) -> List[ChunkResult]:
    # Step 1: build metadata pre-filter
    filter_ = {}
    if session.user_type:
        filter_["user_type_relevance"] = {"$in": [session.user_type]}
    if session.collected_slots.get("project_type"):
        filter_["topic_tags"] = {"$in": [session.collected_slots["project_type"]]}

    # Step 2: embed query
    embedding = await openai_client.embeddings.create(
        model = EMBEDDING_MODEL,
        input = query,
    )
    query_vector = embedding.data[0].embedding

    # Step 3: vector search
    index = pinecone.Index(os.environ["PINECONE_INDEX_NAME"])
    results = index.query(
        vector          = query_vector,
        top_k           = 5,
        filter          = filter_ or None,
        include_metadata = True,
    )

    # Step 4: threshold filter
    return [
        ChunkResult(
            chunk_id      = m.id,
            section_title = m.metadata["section_title"],
            content       = m.metadata["content"],
            score         = m.score,
        )
        for m in results.matches
        if m.score >= SIMILARITY_THRESHOLD
    ]
```

**Acceptance criteria:**
- [ ] Query about solar returns chunks with `topic_tags` containing `"solar"`
- [ ] Query with `user_type="individual"` does not return chunks tagged `enterprise`+`smb` only
- [ ] Query with no relevant content returns `[]`
- [ ] `SIMILARITY_THRESHOLD` constant is documented with comment: *"Changing this model requires full re-ingestion of the Pinecone index."*

---

### Step 12 — `app/layers/generator.py` (FAQ path)

**Creates:** `app/layers/generator.py` — FAQ generation only. Proposal generation added in Step 14.

**Purpose:** Stream an FAQ response grounded in retrieved chunks.

```python
async def generate_faq(
    message:      str,
    chunks:       List[ChunkResult],
    session:      SessionState,
) -> AsyncIterator[str]:    # yields raw token strings for SSE
    system_prompt = build_faq_prompt(chunks, config.company)
    # system_prompt includes:
    #   - chunk content labelled [section_title]
    #   - instruction: answer only from context, cite section titles
    #   - output format: FAQGenerationOutput JSON

    stream = await openai_client.chat.completions.create(
        model    = config.company.models.faq_generation,
        messages = [
            {"role": "system", "content": system_prompt},
            *session.conversation_history[-6:],
            {"role": "user", "content": message},
        ],
        response_format = {"type": "json_object"},
        stream   = True,
    )

    full_response = ""
    async for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        full_response += token
        yield token

    # Validate assembled response
    validate_or_escalate(full_response, FAQGenerationOutput, max_retries=0)
    # (retries handled by caller — flow_controller re-calls if needed)
```

**Acceptance criteria:**
- [ ] Yields tokens incrementally (observable via print in test)
- [ ] Assembled JSON parses to valid `FAQGenerationOutput`
- [ ] `escalate: True` in output when question has no relevant chunks
- [ ] Response contains at least one citation matching a chunk's `section_title`

---

### Step 13 — `app/layers/pricing.py`

**Creates:** `app/layers/pricing.py`

**Purpose:** Pure Python rule evaluator. No LLM. Returns `PricingOutput`.

```python
def compute_price(pricing_input: PricingInput) -> PricingOutput:
    pricing_config = config.pricing

    for rule in pricing_config.rules:
        if _matches(rule.conditions, pricing_input):
            return PricingOutput(
                matched     = True,
                rule_id     = rule.id,
                price_min   = rule.output.price_min,
                price_max   = rule.output.price_max,
                unit        = rule.output.unit,
                assumptions = rule.output.assumptions,
                disclaimer  = pricing_config.disclaimer,
            )

    return PricingOutput(matched=False)

def _matches(conditions: PricingRuleConditions, inp: PricingInput) -> bool:
    if conditions.user_type and conditions.user_type != inp.user_type:
        return False
    if conditions.project_type and conditions.project_type != inp.project_type:
        return False
    if conditions.house_size_sqft_max is not None:
        if inp.house_size_sqft is None or inp.house_size_sqft > conditions.house_size_sqft_max:
            return False
    return True
```

**Acceptance criteria:**
- [ ] `individual` + `solar` + `house_size_sqft=800` → matches `individual_solar_small` rule
- [ ] `individual` + `solar` + `house_size_sqft=1200` → `PricingOutput(matched=False)` (no rule for >1000 sqft yet)
- [ ] `enterprise` + `solar` → `PricingOutput(matched=False)` (no enterprise rules yet)
- [ ] No OpenAI call is made at any point during pricing

---

## Phase 3 — Generation & Output

### Step 14 — `app/layers/generator.py` (Proposal path)

**Extends:** `app/layers/generator.py`

**Adds:** `generate_proposal()` — sequential section-by-section generation.

```python
async def generate_proposal(
    session:        SessionState,
    chunks:         List[ChunkResult],
    pricing_output: PricingOutput,
) -> AsyncIterator[str]:    # yields tokens across all sections

    sections = config.proposal_template.sections
    proposal_sections: List[ProposalSectionOutput] = []

    for section in sections:
        system_prompt = build_proposal_section_prompt(
            section        = section,
            collected_slots = session.collected_slots,
            chunks          = chunks,
            pricing_output  = pricing_output if section.id == "pricing" else None,
            company         = config.company,
        )
        # PricingOutput injected ONLY into the "pricing" section prompt
        # See docs/proposal-flow.md §7.3 for prompt shapes

        section_output, tokens = await _generate_section_with_retry(
            section       = section,
            system_prompt = system_prompt,
            session       = session,
            max_retries   = 2,
        )

        async for token in tokens:
            yield token                # stream tokens to SSE as they arrive

        proposal_sections.append(section_output)

    proposal = ProposalOutput(
        sections     = proposal_sections,
        client_name  = session.collected_slots["client_name"],
        generated_at = datetime.utcnow().isoformat(),
    )

    # Build PDF synchronously (WeasyPrint is sync)
    pdf_path = pdf_builder.build_pdf(proposal, config.company, session.session_id)

    # Lead Write Op 3
    leads.update_proposal_generated(proposal.client_name)
    session.proposal_ready = True
```

**Acceptance criteria:**
- [ ] All 7 sections generated in order with no parallelism
- [ ] `PricingOutput` present in prompt only for `pricing` section
- [ ] Price numbers in generated `pricing` section exactly match `PricingOutput.price_min/max`
- [ ] `session.proposal_ready == True` after function completes
- [ ] PDF file exists at `tmp/proposals/{session_id}.pdf` after completion

---

### Step 15 — `app/layers/pdf_builder.py`

**Creates:** `app/layers/pdf_builder.py`, `templates/proposal.html`

```python
def build_pdf(
    proposal:   ProposalOutput,
    company:    CompanyConfig,
    session_id: str,
) -> str:
    """Returns path to written PDF file."""
    template = jinja2_env.get_template("proposal.html")
    html = template.render(
        proposal     = proposal,
        company      = company,
        generated_at = proposal.generated_at,
    )
    output_path = Path(f"tmp/proposals/{session_id}.pdf")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    weasyprint.HTML(string=html).write_pdf(str(output_path))
    return str(output_path)
```

**`templates/proposal.html`** requirements:
- Iterates `proposal.sections` and renders each `section.title` + `section.content`
- Company name and `currency` injected from `company` object — no branding hardcoded
- Page header: `{company.company_name}` + `{proposal.generated_at}`
- Page footer: page number + `company.contact_email`
- Clean print layout — no nav bars, no chat UI chrome

**Acceptance criteria:**
- [ ] `build_pdf(proposal, config.company, "test-session")` creates `tmp/proposals/test-session.pdf`
- [ ] PDF contains all 7 section titles
- [ ] PDF header shows `"Ions Energy"` (from `company.yaml`, not hardcoded)
- [ ] PDF opens and renders correctly in a PDF viewer

---

### Step 16 — `app/main.py`

**Creates:** `app/main.py`

**Purpose:** FastAPI app with all 5 endpoints and SSE streaming.

```python
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)

@app.post("/session/start")
async def session_start() -> dict:
    session = store.create()
    return {"session_id": session.session_id}

@app.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    # ChatRequest: { session_id: str, message: str }
    session = store.get_or_raise(request.session_id)
    session.conversation_history.append({"role": "user", "content": request.message})
    return StreamingResponse(
        _chat_stream(session, request.message),
        media_type="text/event-stream",
    )

async def _chat_stream(session: SessionState, message: str) -> AsyncIterator[str]:
    """Yields SSE-formatted strings: 'data: {...}\n\n'"""
    async for token in flow_controller.advance(session, message):
        yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
    done_payload = flow_controller.get_done_payload(session)
    yield f"data: {json.dumps({'type': 'done', **done_payload.dict()})}\n\n"

@app.post("/proposal/generate")
async def proposal_generate(request: ProposalRequest) -> dict:
    # Manual trigger — validates all slots filled before starting
    session = store.get_or_raise(request.session_id)
    if session.missing_slots:
        raise HTTPException(400, detail=f"Missing slots: {session.missing_slots}")
    # generation handled by flow_controller on /chat in normal path
    # this endpoint is a direct trigger for testing/integration
    ...

@app.get("/proposal/download/{session_id}")
async def proposal_download(session_id: str) -> FileResponse:
    session = store.get_or_raise(session_id)
    if not session.proposal_ready:
        raise HTTPException(404, detail="Proposal not yet generated")
    pdf_path = Path(f"tmp/proposals/{session_id}.pdf")
    if not pdf_path.exists():
        raise HTTPException(404, detail="Proposal file not found")
    client_name = session.collected_slots.get("client_name", "client")
    return FileResponse(
        path             = str(pdf_path),
        media_type       = "application/pdf",
        filename         = f"proposal_{client_name}.pdf",
    )

@app.delete("/session/{session_id}")
async def session_delete(session_id: str) -> dict:
    deleted = store.delete(session_id)
    return {"success": deleted}
```

**Background task** — register `store.cleanup_expired()` as a FastAPI startup background task (using `asyncio` periodic loop, not APScheduler — no extra dependency).

**Acceptance criteria:**
- [ ] `POST /session/start` returns `{"session_id": "..."}` (UUID format)
- [ ] `POST /chat` returns `text/event-stream` content type
- [ ] SSE stream emits `type: "token"` events followed by `type: "done"` event
- [ ] `GET /proposal/download/{id}` returns 404 before proposal is generated
- [ ] `GET /proposal/download/{id}` returns PDF with correct `Content-Disposition` header after generation
- [ ] `DELETE /session/{id}` returns `{"success": true}` and removes session
- [ ] CORS headers present on all responses (`Access-Control-Allow-Origin: *`)
- [ ] `uvicorn app.main:app` starts without error

---

## Phase 4 — Frontend

### Step 17 — `widget/widget.js` + `widget/widget.css`

**Creates:** `widget/widget.js`, `widget/widget.css`

**Vanilla JS. No framework. No build step.** Embeds via single `<script>` tag.

**Internal state the widget must track:**
```javascript
const state = {
  sessionId:     null,     // set on POST /session/start
  apiBase:       '',       // from data-api attribute
  isOpen:        false,
  inputType:     'text',   // 'text' | 'contact_form'
  proposalReady: false,
  escalated:     false,
};
```

**Key behaviours (see spec §10 and `docs/proposal-flow.md` §4):**

| Event / Signal | Widget action |
|---|---|
| Script tag loads | Inject floating button (bottom-right, configurable via `data-position`) |
| Button clicked | `POST /session/start`, open chat window |
| User submits message | `POST /chat`, open SSE connection, show typing indicator |
| `type: "token"` event | Append token to current bot message bubble |
| `type: "done"` + `input_type: "contact_form"` | Hide text input, render contact form (email + phone fields) |
| `type: "done"` + `input_type: null` (after contact_form) | Restore text input |
| `type: "done"` + `proposal_ready: true` | Show **Download Proposal** button |
| `type: "done"` + `escalated: true` | Show escalation message, disable all input permanently |
| Download button clicked | `GET /proposal/download/{session_id}` (browser handles download) |
| Window close / explicit end | `DELETE /session/{session_id}` |

**Contact form client-side validation:**
```javascript
const EMAIL_RE = /^[\w\.-]+@[\w\.-]+\.\w{2,}$/;
const PHONE_RE = /^[6-9]\d{9}$/;

function validateContactForm(email, phone) {
  const emailOk = EMAIL_RE.test(email.trim());
  const phoneOk = PHONE_RE.test(phone.trim());
  if (!emailOk && !phoneOk) {
    showInlineError("Please enter a valid email address or 10-digit Indian mobile number.");
    return false;
  }
  return true;
}
```

**Event hooks** on `window.IonsEnergyChat`:
```javascript
window.IonsEnergyChat = {
  _listeners: {},
  on(event, callback) { ... },
  emit(event, data) { ... },
  // events: sessionStart, messageReceived, proposalReady, escalated, sessionEnd, error
};
```

**Acceptance criteria:**
- [ ] Widget renders floating button on any static HTML page via `<script data-api="...">` tag
- [ ] Full FAQ conversation completes end-to-end in browser
- [ ] Contact form appears when `input_type: "contact_form"` is received
- [ ] Invalid contact input shows inline error; form not submitted
- [ ] Valid contact input submitted → text input restored on next turn
- [ ] Download button appears after `proposal_ready: true`; clicking downloads PDF
- [ ] Input disabled and escalation message shown after `escalated: true`
- [ ] `window.IonsEnergyChat.on('proposalReady', cb)` fires correctly

---

## Phase 5 — QA & Deploy

### Step 18 — `tests/scenarios.json`

**Creates:** `tests/scenarios.json`

15 structured scenarios from spec §14. Each scenario has:

```json
{
  "id": 1,
  "description": "FAQ — enterprise user asks about BES",
  "user_type": "enterprise",
  "turns": [
    { "user": "Hi, I'm looking for industrial energy storage for my factory" },
    { "user": "Yes, enterprise" },
    { "user": "What's the difference between BES and a diesel generator?" }
  ],
  "expected": {
    "flow_state_final": "generation",
    "retrieval_triggered": true,
    "citations_include": ["BES vs Diesel Generator (DG)"],
    "escalated": false
  }
}
```

Scenario coverage — implement all 15 from spec §14 evaluation table:
- 1–3: FAQ (one per user type)
- 4–5: Ambiguous user type → clarification
- 6–8: Full proposal flow (one per user type)
- 9–10: Partial slot info across multiple turns
- 11: User corrects a previously given slot
- 12: Slot fails extraction twice → escalation
- 13: User explicitly requests human → escalation
- 14: Pricing inquiry — known rule match
- 15: Out-of-scope question → no hallucination

**Acceptance criteria:**
- [ ] All 15 scenarios present with `turns`, `expected`, `id`, `description`
- [ ] Scenarios 6–8 include expected `proposal_generated: true` assertion

---

### Step 19 — Evaluation Run

**No new files.** Run scenarios from Step 18 against the running server.

**Evaluation script** (write inline, not a saved file):
```bash
uvicorn app.main:app &
python - <<'EOF'
import json, httpx, asyncio

scenarios = json.load(open("tests/scenarios.json"))
results = []
for scenario in scenarios:
    # POST /session/start, play all turns via POST /chat, capture done payloads
    # Compare final flow_state, escalated, proposal_ready against expected
    ...
EOF
```

**Pass criteria (from spec §14):**
- [ ] Scenarios 1–3: retrieval relevance score ≥ 1/2 (manual check), citation accuracy pass
- [ ] Scenarios 4–5: correct clarification turn triggered
- [ ] Scenarios 6–8: all slots filled, PDF file created, `proposal_ready: true`
- [ ] Scenarios 9–10: additive slot extraction correct across turns
- [ ] Scenario 11: updated slot value overrides previous value
- [ ] Scenario 12: escalation triggered on second failed extraction
- [ ] Scenario 13: escalation intent detected immediately
- [ ] Scenario 14: `rule_id` in `PricingOutput` matches expected rule
- [ ] Scenario 15: response contains "I don't have that information" variant, `escalate: true`

---

### Step 20 — Deploy (Railway or Render)

**Target:** Railway (recommended — simpler env var management, free tier, auto-deploys from Git).

**Pre-deploy checklist:**
- [ ] `PINECONE_INDEX_NAME` env var set in Railway dashboard
- [ ] `OPENAI_API_KEY` env var set
- [ ] `SESSION_SECRET` env var set
- [ ] `ENVIRONMENT=production` env var set
- [ ] `scripts/ingest.py` run against production Pinecone index
- [ ] `data/` and `tmp/` directories excluded from Git (`.gitignore`)
- [ ] `CORS allow_origins=["*"]` confirmed (widget embeds on any domain)

**`railway.toml`** (create at repo root):
```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/docs"
healthcheckTimeout = 30
```

**Post-deploy smoke test:**
- [ ] `POST /session/start` returns `session_id`
- [ ] Complete one FAQ turn end-to-end via deployed URL
- [ ] Widget embeds on a test HTML page pointing to the deployed API URL
- [ ] Download a proposal PDF via the deployed `GET /proposal/download/{id}` endpoint

---

## Appendix A — `validate_or_escalate()` Helper

Used by every layer that makes an LLM call. Define once in `app/utils.py`.

```python
def validate_or_escalate(
    raw:         str | dict,
    schema:      Type[BaseModel],
    max_retries: int = 2,
    retry_fn:    Optional[Callable] = None,
) -> BaseModel:
    for attempt in range(max_retries + 1):
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return schema(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            if attempt < max_retries and retry_fn:
                raw = retry_fn()
            else:
                raise EscalationException(f"LLM output failed validation: {e}") from e

class EscalationException(Exception):
    """Caught by flow_controller to trigger FlowState.ESCALATED."""
```

---

## Appendix B — Dependency Graph

```
Step 1 (repo)
  └─► Step 2 (config_loader)
        └─► Step 3 (knowledge_base)
              └─► Step 4 (ingest) ─────────────────────────────────────────────┐
        └─► Step 5 (models)                                                     │
              └─► Step 6 (session)                                              │
              └─► Step 7 (leads)                                                │
              └─► Step 8 (entry)                                                │
              └─► Step 9 (flow_controller) ◄── Step 8, Step 10, Step 11 ───────┤
              └─► Step 10 (extractor)                                           │
              └─► Step 11 (retrieval) ◄─────────────────── Pinecone index ─────┘
              └─► Step 12 (generator FAQ) ◄── Step 11
              └─► Step 13 (pricing)
              └─► Step 14 (generator proposal) ◄── Step 11, Step 13, Step 15
              └─► Step 15 (pdf_builder)
        └─► Step 16 (main.py) ◄── Step 6, Step 9
              └─► Step 17 (widget) ◄── Step 16
                    └─► Step 18 (scenarios)
                          └─► Step 19 (eval)
                                └─► Step 20 (deploy)
```

No step should be started before all its upstream dependencies are passing their acceptance criteria.
