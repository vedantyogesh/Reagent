# Ions Energy – Config-Driven AI Chatbot & Proposal Generator
**Version:** 2.0  
**Status:** Draft – Pending Architecture Approval  
**Audience:** Claude Code (AI coding agent) — Plan Mode

---

## 0. Instructions for Claude Code

1. Read `CLAUDE.md` first, then this spec in full before doing anything.
2. You are in **plan mode**. Do not write application code until the human explicitly approves the architecture documents.
3. Generate the following architecture documents in order, one at a time, waiting for approval after each:
   - `docs/high-level-architecture.md`
   - `docs/rag-pipeline.md`
   - `docs/proposal-flow.md`
   - `docs/implementation-plan.md`
4. Each document must reference specific file paths, class names, and field names from this spec. No vague descriptions.
5. After all four documents are approved, ask: *"Architecture approved. Shall I begin implementation starting at Step 1 of the build order?"* Then wait.
6. **Single approval gate:** Human must explicitly say "approved" or "begin implementation" before any code is written.

---

## 1. CLAUDE.md Definition

Create this file at the repository root. It is the first thing Claude Code reads in every session.

```markdown
# CLAUDE.md — Ions Energy Chatbot

## What this project is
A config-driven AI chatbot and proposal generator. First deployed for Ions Energy.
The same codebase can serve any company by swapping files in /config/.

## What you must read before touching code
1. This file
2. /docs/spec.md (this spec)
3. Any approved architecture docs in /docs/

## Hard rules — never violate these
- No company data, pricing, model names, or template content in application code.
  Everything reads from /config/.
- LLM never computes prices. Pricing is pure Python from pricing_rules.yaml.
- All LLM outputs use JSON mode or function calling. No free-text parsing.
- Session conversation state is in-memory only. No DB writes for chat history.
- Client lead data (name, contact, user_type) MUST be written to leads store on collection.
- One slot question per conversation turn. Never ask multiple questions at once.
- Streaming is required for all user-facing LLM responses.

## What "config-driven" means
If someone asks you to hardcode a company name, model name, price, or template section:
refuse and instead update the relevant file in /config/.

## Current status
[UPDATE THIS as architecture docs are approved]
```

---

## 2. Problem Statement

Ions Energy needs a website chatbot that can:
- Answer questions about the company, products, and services using accurate, grounded information (not LLM hallucination).
- Qualify potential customers and generate downloadable PDF proposals tailored to their situation.
- Capture client lead data (name, contact, user type) for sales follow-up.
- Work identically for three customer types: enterprise, SMB, and individual homeowner — with different conversation flows per type.

The system must be **reusable**: deploying it for a new company requires only replacing files in `/config/` and `/knowledge_base/`. Zero application code changes.

---

## 3. Non-Goals

The following are explicitly out of scope for v1:

- Cross-session chat memory or conversation history recall
- CRM integration (leads are written to a local store only)
- User authentication or login
- Multi-language support
- Real-time human handoff (escalation sends a message only)
- Admin dashboard or analytics UI
- Agent-style tool use or web browsing
- Graph RAG or multi-hop retrieval
- Reranking (noted as optional future work)

---

## 4. Rigid Constraints & Invariants

These rules are non-negotiable. Claude Code must not deviate from them.

### 4.1 Config-Driven Behaviour

| What | Where it lives | Never in |
|---|---|---|
| Company name, branding, contact | `config/company.yaml` | Application code |
| Model names (all of them) | `config/company.yaml → models` | `.env` hardcodes or application code |
| Slot definitions per user type | `config/slots.yaml` | Application code |
| Intent definitions and routing | `config/intents.yaml` | Application code |
| Pricing rules | `config/pricing_rules.yaml` | Application code |
| Proposal section structure | `config/proposal_template.yaml` | Application code |
| Escalation message | `config/company.yaml → escalation_message` | Application code |

`config_loader.py` reads and validates all YAML files at startup using Pydantic. If any config is invalid, the application must refuse to start and log the validation error clearly.

### 4.2 Pricing Engine Rules

- The pricing engine is **pure Python**. It reads `pricing_rules.yaml` and evaluates conditions against collected slots.
- The LLM **never** receives a request to calculate, estimate, or infer a price.
- The LLM **only** receives the deterministic output of the pricing engine and is asked to write a human-readable explanation of that output.
- If no pricing rule matches the collected slots, the engine returns `{"matched": false}` and the flow controller triggers escalation.

### 4.3 Safety & Data Constraints

- Session conversation state (messages, slots, flow state) lives **in memory only**. It is destroyed when the session ends or times out.
- Client lead data (name, optional contact, user type, timestamp) is the **only** data written to persistent storage. This is a CSV file at `data/leads.csv`, openable directly in Excel or Google Sheets.
- The proposal PDF is generated into a temporary file store keyed by `session_id`. It is deleted when the session ends.
- No user message content is written to persistent storage.
- CORS must be open (`*`) to allow widget embedding on any domain.
- All LLM outputs must be validated against Pydantic schemas before use. Invalid output triggers a retry (max 2 attempts), then escalation.

---

## 5. Repository Structure

```
/
├── CLAUDE.md                         # Claude Code reads this first
├── docs/
│   ├── spec.md                       # This file
│   ├── high-level-architecture.md    # Generated by Claude Code (plan mode)
│   ├── rag-pipeline.md               # Generated by Claude Code (plan mode)
│   ├── proposal-flow.md              # Generated by Claude Code (plan mode)
│   └── implementation-plan.md        # Generated by Claude Code (plan mode)
│
├── config/
│   ├── company.yaml
│   ├── slots.yaml
│   ├── intents.yaml
│   ├── pricing_rules.yaml
│   └── proposal_template.yaml
│
├── knowledge_base/
│   └── ions_energy.md                # Source knowledge base (Markdown)
│
├── data/
│   └── leads.csv                     # Lead capture — open in Excel/Google Sheets
│
├── tmp/
│   └── proposals/                    # Temp PDF store, keyed by session_id
│
├── app/
│   ├── main.py                       # FastAPI entry point
│   ├── config_loader.py              # Loads + validates all YAML at startup
│   ├── session.py                    # In-memory session store
│   ├── leads.py                      # Lead capture — CSV append/update only
│   │
│   ├── layers/
│   │   ├── entry.py                  # Combined intent + user type classification
│   │   ├── flow_controller.py        # Session state machine + escalation
│   │   ├── extractor.py              # Slot extraction + Pydantic validation
│   │   ├── retrieval.py              # Pinecone vector search + metadata filter
│   │   ├── pricing.py                # Deterministic pricing engine
│   │   ├── generator.py              # LLM generation (streaming)
│   │   └── pdf_builder.py            # Proposal JSON → PDF via WeasyPrint
│   │
│   └── models/
│       ├── session_state.py          # SessionState, FlowState enum
│       ├── slot_models.py            # Dynamic slot schemas from slots.yaml
│       ├── output_models.py          # LLM structured output schemas
│       ├── pricing_models.py         # PricingInput, PricingOutput
│       └── lead_models.py            # LeadRecord schema
│
├── templates/
│   └── proposal.html                 # WeasyPrint HTML template
│
├── widget/
│   ├── widget.js                     # Embeddable widget (vanilla JS)
│   └── widget.css                    # Widget styles
│
├── scripts/
│   └── ingest.py                     # One-time: knowledge base → Pinecone
│
├── tests/
│   └── scenarios.json                # 15 structured evaluation scenarios
│
├── .env.example
├── requirements.txt
└── README.md
```

---

## 6. Config File Schemas

### 6.1 `config/company.yaml`

```yaml
company_name: "Ions Energy"
industry: "energy"
country: "India"
currency: "INR"
contact_email: "contact@ionsenergy.com"
escalation_message: "This requires a specialist. Would you like to connect with our team?"

models:
  classification: "gpt-4o-mini"      # Intent + user type detection
  extraction: "gpt-4o-mini"          # Slot extraction
  faq_generation: "gpt-4o-mini"      # FAQ responses
  proposal_generation: "gpt-4o"      # Proposal section generation

session_timeout_minutes: 30
```

### 6.2 `config/slots.yaml`

```yaml
user_types:
  enterprise:
    required_slots:
      - name: client_name
        question: "What is your name?"
        type: string
      - name: contact
        question: "What's the best way to reach you — a phone number or email?"
        type: string
        input_type: contact_form          # triggers form widget in frontend, not plain text input
        validation:
          regex_email: '^[\w\.-]+@[\w\.-]+\.\w{2,}$'
          regex_phone: '^[6-9]\d{9}$'   # Indian mobile: starts with 6-9, 10 digits
          error_message: "Please enter a valid email address or 10-digit Indian mobile number."
      - name: industry
        question: "What industry is your business in?"
        type: string
      - name: project_type
        question: "What type of project are you looking at? (solar, BES, hybrid)"
        type: string
      - name: budget_range
        question: "What is your approximate budget range (in INR)?"
        type: string
      - name: timeline
        question: "What is your expected timeline for this project?"
        type: string
      - name: company_size
        question: "How many employees does your organisation have?"
        type: string

  smb:
    required_slots:
      - name: client_name
        question: "What is your name?"
        type: string
      - name: contact
        question: "What's the best way to reach you — a phone number or email?"
        type: string
        input_type: contact_form          # triggers form widget in frontend, not plain text input
        validation:
          regex_email: '^[\w\.-]+@[\w\.-]+\.\w{2,}$'
          regex_phone: '^[6-9]\d{9}$'   # Indian mobile: starts with 6-9, 10 digits
          error_message: "Please enter a valid email address or 10-digit Indian mobile number."
      - name: industry
        question: "What type of business do you run?"
        type: string
      - name: project_type
        question: "Are you looking at solar, battery storage, or both?"
        type: string
      - name: monthly_bill
        question: "What is your average monthly electricity bill (in INR)?"
        type: number
      - name: timeline
        question: "When are you looking to get this installed?"
        type: string

  individual:
    required_slots:
      - name: client_name
        question: "What is your name?"
        type: string
      - name: contact
        question: "What's the best way to reach you — a phone number or email?"
        type: string
        input_type: contact_form          # triggers form widget in frontend, not plain text input
        validation:
          regex_email: '^[\w\.-]+@[\w\.-]+\.\w{2,}$'
          regex_phone: '^[6-9]\d{9}$'   # Indian mobile: starts with 6-9, 10 digits
          error_message: "Please enter a valid email address or 10-digit Indian mobile number."
      - name: state
        question: "Which state are you located in?"
        type: string
      - name: house_size_sqft
        question: "What is the approximate size of your home in square feet?"
        type: number
      - name: monthly_bill_inr
        question: "What was your last electricity bill amount in INR?"
        type: number
      - name: project_type
        question: "Are you interested in solar panels, home battery storage, or both?"
        type: string
    optional_slots:
      - name: monthly_kwh
        question: "If you know it, what was your monthly consumption in kWh?"
        type: number
```

`client_name` is always the **first required slot** for every user type.

### 6.3 `config/intents.yaml`

```yaml
intents:
  - name: general_faq
    description: "User is asking about the company, products, team, or general information"
    triggers_flow: faq

  - name: pricing_inquiry
    description: "User is asking about cost, pricing, or budget"
    triggers_flow: proposal

  - name: proposal_request
    description: "User explicitly wants a proposal, quote, or recommendation"
    triggers_flow: proposal

  - name: escalation_request
    description: "User wants to speak to a human or sales representative"
    triggers_flow: escalate

fallback_intent: general_faq
confidence_threshold: 0.70
```

### 6.4 `config/pricing_rules.yaml`

```yaml
# LLM never computes prices. Rules evaluated top-to-bottom. First match wins.

rules:
  - id: individual_solar_small
    conditions:
      user_type: individual
      project_type: solar
      house_size_sqft_max: 1000
    output:
      price_min: 0          # TO BE FILLED by Ions Energy
      price_max: 0          # TO BE FILLED by Ions Energy
      unit: INR
      assumptions: "Estimate for homes under 1000 sqft, standard solar setup"

  # Add further rules following identical structure

disclaimer: "All prices are indicative estimates and subject to site survey."
```

### 6.5 `config/proposal_template.yaml`

```yaml
sections:
  - id: executive_summary
    title: "Executive Summary"
    prompt_instruction: "Write a 2-3 sentence summary of the client's situation and what Ions Energy is proposing."

  - id: solution_overview
    title: "Proposed Solution"
    prompt_instruction: "Describe the recommended solution based on project_type and collected slot data."

  - id: why_ions_energy
    title: "Why Ions Energy"
    prompt_instruction: "Explain why Ions Energy is the right partner using only retrieved knowledge base chunks."

  - id: technical_specs
    title: "Technical Specifications"
    prompt_instruction: "Outline key technical details of the proposed solution."

  - id: pricing
    title: "Investment Overview"
    prompt_instruction: "Present the pricing range with assumptions and disclaimer. Use the deterministic price values provided exactly. Do not modify the numbers."

  - id: timeline
    title: "Project Timeline"
    prompt_instruction: "Provide a high-level timeline based on the client's stated timeline and project complexity."

  - id: next_steps
    title: "Next Steps"
    prompt_instruction: "List exactly 3 clear next steps for the client to proceed."
```

---

## 7. Data Models

### 7.1 Session State (`app/models/session_state.py`)

```python
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from enum import Enum

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
    user_type: Optional[str] = None               # enterprise | smb | individual
    user_type_confidence: Optional[float] = None
    primary_intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    flow_state: FlowState = FlowState.INIT
    collected_slots: Dict[str, Any] = {}
    missing_slots: List[str] = []
    conversation_history: List[Dict[str, str]] = []  # [{role, content}]
    slot_attempt_counts: Dict[str, int] = {}
    escalation_triggered: bool = False
    proposal_ready: bool = False
    lead_captured: bool = False                   # True once LeadRecord is written
```

### 7.2 Lead Record (`app/models/lead_models.py`)

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class LeadRecord(BaseModel):
    client_name: str
    email: Optional[str] = None       # validated against email regex before storage
    phone: Optional[str] = None       # validated against Indian mobile regex before storage
    user_type: str                    # enterprise | smb | individual
    captured_at: datetime
    proposal_generated: bool = False

    @validator("email", "phone")
    def at_least_one_contact(cls, v, values):
        # At least one of email or phone must be present
        if not v and not values.get("email") and not values.get("phone"):
            raise ValueError("At least one of email or phone is required")
        return v
```

**Storage:** Appended to `data/leads.csv`. Columns: `client_name`, `email`, `phone`, `user_type`, `captured_at`, `proposal_generated`. Open directly in Excel or Google Sheets — no database required.

**Write rules:**
- Row appended immediately when `client_name` is extracted.
- `proposal_generated` updated to `True` when PDF is successfully created.
- Rows are never deleted.

**Contact collection:** After `client_name`, the bot renders a **contact form field** (not a plain chat bubble) with two inputs: email and phone. The user fills at least one. Both inputs are validated client-side (widget) and server-side (extractor layer) using regex before the value is accepted.

- Email regex: `^[\w\.-]+@[\w\.-]+\.\w{2,}$`
- Phone regex: `^[6-9]\d{9}$` (Indian mobile — starts 6–9, 10 digits)
- At least one of email or phone is required. Both may be provided.
- If neither passes validation after 2 attempts, escalation is triggered.
- Raw input is never stored. Only the validated value is written to `leads.csv`.

### 7.3 Pricing Models (`app/models/pricing_models.py`)

```python
from pydantic import BaseModel
from typing import Optional

class PricingInput(BaseModel):
    user_type: str
    project_type: str
    house_size_sqft: Optional[float] = None
    monthly_bill_inr: Optional[float] = None
    monthly_kwh: Optional[float] = None
    budget_range: Optional[str] = None
    company_size: Optional[str] = None
    timeline: Optional[str] = None

class PricingOutput(BaseModel):
    matched: bool
    rule_id: Optional[str] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    unit: Optional[str] = "INR"
    assumptions: Optional[str] = None
    disclaimer: Optional[str] = None
```

### 7.4 LLM Output Models (`app/models/output_models.py`)

```python
from pydantic import BaseModel
from typing import List, Optional

class ClassificationOutput(BaseModel):
    user_type: str                      # enterprise | smb | individual | unknown
    user_type_confidence: float
    primary_intent: str
    intent_confidence: float

class ExtractionOutput(BaseModel):
    class ExtractedField(BaseModel):
        value: Any
        confidence: float
    extracted: Dict[str, ExtractedField]
    unclear_fields: List[str]

class FAQGenerationOutput(BaseModel):
    response: str
    citations: List[str]
    confidence: str                     # high | medium | low
    escalate: bool

class ProposalSectionOutput(BaseModel):
    id: str
    title: str
    content: str

class ProposalOutput(BaseModel):
    sections: List[ProposalSectionOutput]
    client_name: str
    generated_at: str                   # ISO timestamp
```

---

## 8. Functional Decomposition

### 8.1 Chatbot Flow

#### Entry: Combined Classification (`app/layers/entry.py`)

On the first meaningful message, make **one LLM call** using `models.classification` that returns `ClassificationOutput`.

Rules:
- If `user_type_confidence < confidence_threshold` → do not guess. Ask directly: *"Are you looking for a solution for your home, a small business, or a large enterprise?"*
- If `intent_confidence < confidence_threshold` → default to `fallback_intent` from `intents.yaml`.
- Do not make two separate calls for classification and intent. One call, two outputs.

#### Flow Controller (`app/layers/flow_controller.py`)

State machine. Governs every transition. Reads slot requirements from `slots.yaml`.

```
INIT
  └─► first message ──► USER_TYPE_DETECTION

USER_TYPE_DETECTION
  ├─► classified (confidence ≥ threshold) ──► INTENT_DETECTION
  └─► unclear ──► ask clarification ──► USER_TYPE_DETECTION

INTENT_DETECTION
  ├─► faq intent ──► RETRIEVAL
  ├─► proposal / pricing intent ──► SLOT_COLLECTION
  └─► escalation intent ──► ESCALATED

SLOT_COLLECTION
  ├─► missing_slots not empty ──► ask next missing slot (one at a time)
  └─► missing_slots empty ──► RETRIEVAL + PROPOSAL_GENERATION

RETRIEVAL
  └─► chunks retrieved ──► GENERATION

GENERATION
  └─► response streamed ──► await next message ──► INTENT_DETECTION

PROPOSAL_GENERATION
  └─► all slots filled ──► pricing engine ──► generate PDF ──► COMPLETE

ESCALATED
  └─► send escalation_message ──► end session

COMPLETE
  └─► proposal download link sent ──► session remains open for questions
```

Escalation triggers (any one sufficient):
- `slot_attempt_counts[slot] >= 2` for any slot
- Retrieval returns zero chunks above similarity threshold
- `pricing_output.matched == False`
- `faq_output.escalate == True`
- User message matches `escalation_request` intent

#### Slot Asking Rules
- Ask one slot per turn.
- After each user response, run the extraction layer before deciding the next slot.
- If a slot fails extraction twice, trigger escalation.
- If user provides a value for an already-collected slot, update it.
- `client_name` is always asked first regardless of user type.

### 8.2 RAG Subsystem

#### Ingestion (`scripts/ingest.py`)

Run once. Re-run whenever knowledge base changes.

Steps:
1. Parse `knowledge_base/ions_energy.md`
2. Split into chunks by H2 and H3 headings (semantic chunking)
3. Each chunk gets metadata: `{ section_title, user_type_relevance: [list], topic_tags: [list] }`
4. Embed each chunk using `text-embedding-3-small`
5. Upsert to Pinecone index named from `PINECONE_INDEX_NAME` env var

#### Retrieval (`app/layers/retrieval.py`)

Steps:
1. Apply metadata pre-filter using available session data (`user_type`, `project_type`)
2. Embed the user query using `text-embedding-3-small`
3. Run vector similarity search
4. Retrieve top 5 chunks
5. Return chunks as list of `{ chunk_id, section_title, content, score }`

Only trigger retrieval when:
- Intent is `general_faq`, OR
- All required slots are filled (for proposal context enrichment)

Do not retrieve during slot collection.

#### Knowledge Base Document Structure (`knowledge_base/ions_energy.md`)

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

Each section must be self-contained. No cross-references. Plain factual language.

#### Prompting Rules

- Inject only retrieved chunks, not the full knowledge base.
- Label each chunk with its `section_title`.
- System instruction: *"Answer using only the provided context. If the answer is not in the context, say so clearly. Do not invent facts."*
- Always require `FAQGenerationOutput` structured output.

### 8.3 Proposal Subsystem

#### Intake Flow

The proposal flow begins when intent is `proposal_request` or `pricing_inquiry`. Slot collection proceeds as described in 8.1.

#### Pricing Engine (`app/layers/pricing.py`)

```python
def compute_price(pricing_input: PricingInput) -> PricingOutput:
    # Load pricing_rules.yaml
    # Evaluate rules top-to-bottom
    # Return first matched rule's output as PricingOutput
    # If no rule matches, return PricingOutput(matched=False)
```

The LLM receives `PricingOutput` and is instructed to write a human-readable explanation. It must not alter `price_min`, `price_max`, or `disclaimer`.

#### Proposal Generation (`app/layers/generator.py`)

For each section in `proposal_template.yaml`:
- Build prompt: `section.prompt_instruction` + collected slots as JSON + top 5 retrieved chunks + `PricingOutput`
- Call LLM using `models.proposal_generation`
- Require `ProposalSectionOutput` structured output
- Assemble all sections into `ProposalOutput`

Proposal generation is **sequential per section**, not batched, to keep prompts focused.

#### PDF Generation (`app/layers/pdf_builder.py`)

- Input: `ProposalOutput`
- Template: `templates/proposal.html` (WeasyPrint)
- Company branding (name, colours) injected from `company.yaml`
- Output: PDF written to `tmp/proposals/{session_id}.pdf`
- File is deleted when session ends or times out

#### Audit Trail (`app/leads.py`)

On `client_name` extraction:
- Append `LeadRecord` row to `data/leads.csv`

On proposal generation:
- Update matching row in `data/leads.csv`: set `proposal_generated = True`

Logs (structured, to stdout):
- Session start / end
- Intent classification result
- Slot collection progress
- Retrieval chunk count and top score
- Pricing rule matched (rule_id only, no personal data)
- Proposal generation success / failure
- Errors with full traceback

---

## 9. API Contracts

All endpoints are on the FastAPI backend. CORS is open (`*`).

### `POST /session/start`
```
Request:  {}
Response: { session_id: str }
```

### `POST /chat`
```
Request:  { session_id: str, message: str }
Response: Server-Sent Events (SSE) stream
  Stream events:
    data: { type: "token", content: str }         # streaming token
    data: { type: "done", flow_state: str, proposal_ready: bool, escalated: bool, input_type: str | null }
    data: { type: "error", message: str }
```

All user-facing LLM replies stream via SSE. The `done` event signals end of stream and carries state. `input_type` is `null` for standard text input, or `"contact_form"` when the next expected input is contact details — the widget renders a form field in this case.

### `POST /proposal/generate`
```
Request:  { session_id: str }
Response: { success: bool, proposal_json: ProposalOutput }
```
Triggers proposal generation if all slots are filled. Returns `ProposalOutput`.

### `GET /proposal/download/{session_id}`
```
Response: PDF file (Content-Type: application/pdf)
          Content-Disposition: attachment; filename="proposal_{client_name}.pdf"
```
Returns 404 if session not found or proposal not yet generated.

### `DELETE /session/{session_id}`
```
Response: { success: bool }
```
Destroys session state and deletes `tmp/proposals/{session_id}.pdf`.

---

## 10. Frontend Widget

**Files:** `widget/widget.js`, `widget.css`

### Embedding

```html
<script
  src="https://your-deployment-url/widget/widget.js"
  data-api="https://your-deployment-url"
  data-company="ions_energy"
  data-position="bottom-right"
  data-primary-color="#0A84FF">
</script>
```

`data-api` is the only required attribute.

### Behaviour

- Floating button, bottom-right by default. Configurable via `data-position`.
- Click to expand into chat window.
- Calls `POST /session/start` on first open to obtain `session_id`.
- Sends messages via `POST /chat` and renders SSE tokens as they arrive (streaming).
- Shows typing indicator between user send and first token.
- When `done` event has `proposal_ready: true`, shows a **"Download Proposal"** button that calls `GET /proposal/download/{session_id}`.
- When `done` event has `escalated: true`, shows an escalation message and disables further input.
- When the backend signals `input_type: contact_form` (via the `done` event), renders a **form widget** instead of the standard text input. The form has two fields: Email and Phone. At least one must be filled. Client-side regex validation runs on blur and on submit before the value is sent to the backend. Invalid input shows an inline error message — the form is not submitted until at least one field passes validation.
- Vanilla JS only. No frameworks. No build step. Single script tag.

### Event Hooks

Exposed on `window.IonsEnergyChat` for the host page to listen:

```javascript
window.IonsEnergyChat.on('sessionStart', ({ session_id }) => {})
window.IonsEnergyChat.on('messageReceived', ({ message, flow_state }) => {})
window.IonsEnergyChat.on('proposalReady', ({ session_id }) => {})
window.IonsEnergyChat.on('escalated', ({ session_id }) => {})
window.IonsEnergyChat.on('sessionEnd', ({ session_id }) => {})
window.IonsEnergyChat.on('error', ({ message }) => {})
```

---

## 11. Environment Variables

```env
# Required
OPENAI_API_KEY=
PINECONE_API_KEY=
PINECONE_INDEX_NAME=ions-energy
SESSION_SECRET=
ENVIRONMENT=development         # development | production

# Optional model overrides (defaults read from company.yaml)
# MODEL_CLASSIFICATION=gpt-4o-mini
# MODEL_EXTRACTION=gpt-4o-mini
# MODEL_FAQ_GENERATION=gpt-4o-mini
# MODEL_PROPOSAL_GENERATION=gpt-4o
```

---

## 12. Tech Stack

| Layer | Tool |
|---|---|
| LLM — Classification & Extraction | OpenAI GPT-4o Mini |
| LLM — Proposal Generation | OpenAI GPT-4o |
| Embeddings | OpenAI text-embedding-3-small |
| RAG Framework | LangChain |
| Vector DB | Pinecone (free tier) |
| Backend | FastAPI (Python 3.11+) |
| Streaming | Server-Sent Events (SSE) via FastAPI `StreamingResponse` |
| Data Validation | Pydantic v2 |
| Lead Storage | CSV via `csv` (stdlib) — Excel/Google Sheets compatible |
| PDF Generation | WeasyPrint |
| Config Format | YAML |
| Widget | Vanilla JS + CSS |
| Hosting | Railway or Render |

---

## 13. Build Order

Build strictly in this sequence. Do not skip ahead.

1. Set up repo structure, `CLAUDE.md`, `.env.example`, `requirements.txt`
2. Build `config_loader.py` — loads and validates all YAML at startup
3. Create `knowledge_base/ions_energy.md` with correct heading structure
4. Write and run `scripts/ingest.py` — populate Pinecone
5. Build `app/models/` — all Pydantic models
6. Build `app/session.py` — in-memory session store
7. Build `app/leads.py` — SQLite lead capture
8. Build `app/layers/entry.py` — combined classification
9. Build `app/layers/flow_controller.py` — state machine
10. Build `app/layers/extractor.py` — slot extraction
11. Build `app/layers/retrieval.py` — vector search
12. Build `app/layers/generator.py` — streaming FAQ generation end-to-end
13. Build `app/layers/pricing.py` — deterministic pricing engine
14. Build `app/layers/generator.py` — proposal generation (extend existing file)
15. Build `app/layers/pdf_builder.py` — PDF output
16. Build `app/main.py` — all FastAPI endpoints with SSE
17. Build `widget/widget.js` and `widget.css`
18. Write `tests/scenarios.json` — 15 test scenarios
19. Run evaluation against all scenarios
20. Deploy to Railway or Render

---

## 14. Evaluation Plan

**File:** `tests/scenarios.json` — 15 structured scenarios

| # | Scenario | Metrics |
|---|---|---|
| 1–3 | FAQ — one per user type | Retrieval relevance (0–2), citation accuracy (pass/fail) |
| 4–5 | Ambiguous user type → clarification | Correct fallback triggered (pass/fail) |
| 6–8 | Full proposal flow — one per user type | Slot completeness, proposal quality (0–2), PDF generated (pass/fail) |
| 9–10 | Partial slot info across multiple turns | Additive extraction correctness (pass/fail) |
| 11 | User corrects a previously given slot | Slot update handled correctly (pass/fail) |
| 12 | Slot fails extraction twice | Escalation triggered (pass/fail) |
| 13 | User explicitly requests human | Escalation intent detected (pass/fail) |
| 14 | Pricing inquiry — known rule match | Price values correct (pass/fail) |
| 15 | Out-of-scope question | "Not in context" response, no hallucination (pass/fail) |

Log per scenario: retrieval relevance, slot fill accuracy, pricing correctness, escalation appropriateness, response latency (ms). Manual scoring acceptable for v1.

---

## 15. Hard Constraints Summary (for Claude Code)

- **LLM never computes prices.** Pure Python only from `pricing_rules.yaml`.
- **No hardcoded company data.** All from `/config/`.
- **No hardcoded model names.** All from `company.yaml → models`. Env vars may override.
- **Retrieval only after intent is clear.** Never mid-slot-collection.
- **One slot question per turn.**
- **`client_name` and `contact` are always the first two slots collected**, in that order, regardless of user type. Contact is collected via a form widget with regex validation — not plain text. At least one of email or phone is required.
- **Lead record written to SQLite immediately** after `client_name` is extracted.
- **Structured output enforced on all LLM calls.** Malformed output → retry max 2 → escalate.
- **All user-facing replies stream via SSE.**
- **Session state in memory only.** Proposal PDFs in `tmp/`, deleted on session end.
- **CORS open.** Widget must embed on any domain.
- **`config_loader.py` validates all YAML at startup.** App refuses to start on invalid config.
