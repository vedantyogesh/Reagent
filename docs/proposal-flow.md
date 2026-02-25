# Proposal Flow — Ions Energy Config-Driven Chatbot

**Version:** 2.0
**Status:** Approved
**Spec Reference:** `docs/spec.md` §8.1, §8.3

---

## 1. Overview

The proposal flow is the primary revenue path. It is triggered when the user's intent is `proposal_request` or `pricing_inquiry`. It spans five sequential phases:

```
SLOT COLLECTION  →  RETRIEVAL  →  PRICING  →  GENERATION  →  PDF
```

Each phase has hard constraints that the implementation must not violate. This document covers each phase in full, including the contact form SSE handshake, the section-by-section generation loop, the exact shape of the pricing injection, and the PDF temp file lifecycle.

---

## 2. Entry Condition

The proposal flow begins when `app/layers/flow_controller.py` routes to `SLOT_COLLECTION` after intent detection.

**Triggering intents** (from `config/intents.yaml`):
- `proposal_request` — user explicitly wants a proposal or quote
- `pricing_inquiry` — user asking about cost or budget

**Pre-conditions at entry:**
- `session.user_type` is known (confidence ≥ threshold)
- `session.primary_intent` is one of the two above
- `session.missing_slots` is populated from `config/slots.yaml` for the detected `user_type`
- `session.flow_state` transitions to `FlowState.SLOT_COLLECTION`

---

## 3. Slot Collection Phase

### 3.1 Slot Order Rules

```
For every user_type:
  1. client_name   — always first
  2. contact       — always second (triggers contact form widget — see §4)
  3. remaining required_slots — in order defined in slots.yaml
  4. optional_slots — asked only if required slots are all filled
```

These rules are enforced by `flow_controller.py`, not by the slot order in `slots.yaml`. `client_name` and `contact` are always promoted to positions 1 and 2 regardless of their position in the YAML.

### 3.2 One Slot Per Turn

The flow controller asks exactly one missing slot per conversation turn. It never batches slot questions.

```
Turn N:   bot asks for client_name
Turn N+1: user answers → extractor.py validates → slot marked collected
           bot asks for contact (→ triggers contact form, see §4)
Turn N+2: user submits contact form → extractor.py validates → slot marked collected
           bot asks for next missing slot
...
Turn N+k: last missing slot collected → flow transitions to RETRIEVAL
```

### 3.3 Slot Extraction (`app/layers/extractor.py`)

After each user response, `extractor.py` is called before the flow controller decides the next action.

```python
# Input
ExtractionInput(
    user_message: str,
    target_slots: List[str],      # slots still missing
    collected_slots: Dict[str, Any],
    conversation_history: List[Dict]
)

# LLM call: models.extraction (gpt-4o-mini), JSON mode → ExtractionOutput
ExtractionOutput(
    extracted: Dict[str, ExtractedField(value, confidence)],
    unclear_fields: List[str]
)
```

**After extraction:**
- Merge `extracted` into `session.collected_slots`.
- Remove newly collected slots from `session.missing_slots`.
- If a slot the user already answered appears in `extracted` with a new value, update it (`collected_slots[slot] = new_value`).
- Increment `slot_attempt_counts[slot]` for each slot in `unclear_fields`.
- If `slot_attempt_counts[slot] >= 2` for any slot → trigger escalation immediately.

### 3.4 Lead Write Op 1 — Row Creation

Triggered the turn `client_name` is first successfully extracted:

```python
# app/leads.py
leads.append_row(LeadRecord(
    client_name = session.collected_slots["client_name"],
    user_type   = session.user_type,
    captured_at = datetime.utcnow(),
    email       = None,
    phone       = None,
    proposal_generated = False
))
session.lead_captured = True
```

The row is written immediately — before the bot asks the next slot question. `email` and `phone` are `None` at this point.

---

## 4. Contact Form SSE Handshake

This is the mechanism by which the backend signals the widget to replace the text input with a structured form. It happens exactly once per session, when `contact` is the next missing slot.

### 4.1 Sequence

```
flow_controller detects next missing slot == "contact"
  │
  ▼
generator.py produces the contact prompt question
  ("What's the best way to reach you — a phone number or email?")
  │
  ▼
SSE stream to widget:
  data: { type: "token", content: "What's the best way..." }  ← streamed tokens
  ...
  data: {
    type: "done",
    flow_state: "slot_collection",
    proposal_ready: false,
    escalated: false,
    input_type: "contact_form"          ← KEY SIGNAL
  }
  │
  ▼
widget.js detects input_type == "contact_form"
  → hides standard <input type="text">
  → renders contact form:
       [ Email input          ]
       [ Phone input          ]
       [ Submit button        ]
  → client-side validation on blur and submit:
       email regex: ^[\w\.-]+@[\w\.-]+\.\w{2,}$
       phone regex: ^[6-9]\d{9}$  (Indian mobile)
       at least one field must pass before form submits
  │
  ▼
user fills form, clicks Submit
  │
  ▼
widget.js serialises form as a plain message string:
  "email: user@example.com | phone: 9876543210"
  POST /chat { session_id, message: "email: user@example.com | phone: 9876543210" }
  │
  ▼
extractor.py parses the message → ExtractionOutput
  extracted["email"] = { value: "user@example.com", confidence: 1.0 }
  extracted["phone"] = { value: "9876543210", confidence: 1.0 }
  │
  ▼
Server-side validation (extractor.py applies same regexes):
  ✓ valid  → continue to Lead Write Op 2
  ✗ invalid → unclear_fields += ["contact"]
               slot_attempt_counts["contact"] += 1
               if count >= 2 → ESCALATED
               else → re-ask, resend input_type: "contact_form" in next done event
```

### 4.2 `input_type` Values

| Value | When set | Widget behaviour |
|---|---|---|
| `null` | All turns except contact slot | Render standard `<input type="text">` |
| `"contact_form"` | When `contact` is the next missing slot | Render two-field contact form |

`input_type` is always present in every `done` event. It is `null` by default; the flow controller sets it to `"contact_form"` only when appropriate.

### 4.3 Lead Write Op 2 — Contact Update

Triggered immediately after `email` and/or `phone` pass server-side validation:

```python
# app/leads.py
leads.update_row(
    client_name = session.collected_slots["client_name"],
    email       = session.collected_slots.get("email"),
    phone       = session.collected_slots.get("phone")
)
```

Only validated values are written. Raw unvalidated input is never stored.

---

## 5. Retrieval Phase (Pre-Proposal)

Once `session.missing_slots == []`, the flow controller transitions to `FlowState.RETRIEVAL` before generation begins.

```python
# app/layers/flow_controller.py
if not session.missing_slots:
    session.flow_state = FlowState.RETRIEVAL
    chunks = await retrieval.retrieve(
        query   = build_proposal_query(session.collected_slots),
        session = session
    )
    session.flow_state = FlowState.PROPOSAL_GENERATION
```

**Query construction for proposal context:**
```python
def build_proposal_query(slots: dict) -> str:
    # Synthesise a natural-language query from slots for relevant retrieval
    # e.g. "solar installation for individual homeowner in Maharashtra"
    parts = [slots.get("project_type", ""), slots.get("user_type", "")]
    if slots.get("state"):       parts.append(slots["state"])
    if slots.get("industry"):    parts.append(slots["industry"])
    return " ".join(filter(None, parts))
```

Retrieved chunks are passed directly into proposal section generation. If retrieval returns `[]` (all scores below threshold), escalation is triggered before proposal generation begins.

---

## 6. Pricing Phase (`app/layers/pricing.py`)

Runs synchronously before the generation loop starts. No LLM involved.

### 6.1 Input Construction

```python
pricing_input = PricingInput(
    user_type         = session.user_type,
    project_type      = session.collected_slots.get("project_type"),
    house_size_sqft   = session.collected_slots.get("house_size_sqft"),
    monthly_bill_inr  = session.collected_slots.get("monthly_bill_inr")
                        or session.collected_slots.get("monthly_bill"),
    monthly_kwh       = session.collected_slots.get("monthly_kwh"),
    budget_range      = session.collected_slots.get("budget_range"),
    company_size      = session.collected_slots.get("company_size"),
    timeline          = session.collected_slots.get("timeline"),
)
```

### 6.2 Rule Evaluation

```python
def compute_price(pricing_input: PricingInput) -> PricingOutput:
    rules = load_pricing_rules()          # config/pricing_rules.yaml
    for rule in rules:                    # top-to-bottom, first match wins
        if _matches(rule.conditions, pricing_input):
            return PricingOutput(
                matched     = True,
                rule_id     = rule.id,
                price_min   = rule.output.price_min,
                price_max   = rule.output.price_max,
                unit        = rule.output.unit,
                assumptions = rule.output.assumptions,
                disclaimer  = rules.disclaimer   # global disclaimer from yaml root
            )
    return PricingOutput(matched=False)
```

### 6.3 No-Match → Escalation

```python
pricing_output = compute_price(pricing_input)
if not pricing_output.matched:
    session.flow_state = FlowState.ESCALATED
    session.escalation_triggered = True
    return escalation_message   # from company.yaml
```

The proposal generation loop **never starts** if pricing has no match. This is a hard stop.

---

## 7. Proposal Generation Loop (`app/layers/generator.py`)

### 7.1 Section Order

Sections are generated **sequentially** in the order defined in `config/proposal_template.yaml`. No parallelism. This keeps each prompt focused and prevents sections from influencing each other via shared context.

```
proposal_template.yaml sections (in order):
  1. executive_summary
  2. solution_overview
  3. why_ions_energy
  4. technical_specs
  5. pricing              ← PricingOutput injected here only
  6. timeline
  7. next_steps
```

### 7.2 Per-Section Generation

For each section:

```python
for section in proposal_template.sections:
    prompt = build_section_prompt(
        section         = section,
        collected_slots = session.collected_slots,
        chunks          = retrieved_chunks,          # same top-5 for all sections
        pricing_output  = pricing_output if section.id == "pricing" else None,
        client_name     = session.collected_slots["client_name"],
        company         = company_config,
    )
    raw = await llm.generate(
        model    = company_config.models.proposal_generation,   # gpt-4o
        messages = prompt,
        response_format = ProposalSectionOutput,   # JSON mode / function calling
    )
    section_output = validate_or_retry(raw, ProposalSectionOutput, max_retries=2)
    proposal_sections.append(section_output)

proposal = ProposalOutput(
    sections     = proposal_sections,
    client_name  = session.collected_slots["client_name"],
    generated_at = datetime.utcnow().isoformat(),
)
```

### 7.3 Prompt Shape Per Section

**All sections except `pricing`:**

```
SYSTEM:
  You are writing the "{section.title}" section of a proposal for {client_name}.
  Company: {company_name} | Currency: {currency}
  {section.prompt_instruction}

  Rules:
  - Use ONLY the slot data and retrieved context provided below.
  - Do not invent facts, pricing, or specifications.
  - Write in clear, professional English suitable for {user_type} clients.

SLOT DATA:
  {json.dumps(collected_slots, indent=2)}

CONTEXT:
  [{chunk.section_title}]
  {chunk.content}

  [{chunk.section_title}]
  {chunk.content}
  ... (up to 5 chunks, ordered by score descending)

OUTPUT FORMAT: ProposalSectionOutput (JSON mode)
  { "id": "{section.id}", "title": "{section.title}", "content": "..." }
```

**`pricing` section only — `PricingOutput` is appended:**

```
SYSTEM:
  You are writing the "Investment Overview" section of a proposal for {client_name}.
  {section.prompt_instruction}

  Rules:
  - Present the pricing range using EXACTLY the values in the PRICING block below.
  - Do NOT alter price_min, price_max, or disclaimer text.
  - You may write a human-readable narrative around these numbers, but the numbers
    themselves must not change.
  - Include the disclaimer verbatim.

SLOT DATA:
  {json.dumps(collected_slots, indent=2)}

PRICING:
  {
    "price_min":   {pricing_output.price_min},
    "price_max":   {pricing_output.price_max},
    "unit":        "{pricing_output.unit}",
    "assumptions": "{pricing_output.assumptions}",
    "disclaimer":  "{pricing_output.disclaimer}"
  }

CONTEXT:
  [{chunk.section_title}]
  {chunk.content}
  ... (up to 5 chunks)

OUTPUT FORMAT: ProposalSectionOutput (JSON mode)
```

**Why `PricingOutput` is injected only into the `pricing` section:**
Injecting it into every section risks the LLM referencing numbers in the wrong context (e.g., mentioning price in the Executive Summary when it shouldn't). The pricing section prompt explicitly forbids altering numbers; other section prompts are not burdened with that constraint.

### 7.4 Retry and Escalation

For each section:

```
LLM call → attempt 1
  ✓ valid ProposalSectionOutput → continue
  ✗ malformed → retry (attempt 2)
    ✓ valid → continue
    ✗ malformed → ESCALATED (stop generation, do not emit partial proposal)
```

A partial proposal is never returned. Either all sections succeed or escalation is triggered.

### 7.5 Streaming During Generation

Each section is streamed to the widget as tokens arrive. The SSE stream does not wait for all sections to complete before sending tokens.

```
Section 1 (executive_summary):
  data: { type: "token", content: "Ions Energy..." }
  data: { type: "token", content: " is pleased..." }
  ...
Section 2 (solution_overview):
  data: { type: "token", content: "Based on your..." }
  ...
...
Section 7 (next_steps):
  data: { type: "token", content: "..." }
  ...
  data: {
    type: "done",
    flow_state: "complete",
    proposal_ready: true,            ← PDF is ready at this point
    escalated: false,
    input_type: null
  }
```

The `done` event is emitted only after **all sections are generated and the PDF is written** (see §8). The widget shows the Download button upon receiving `proposal_ready: true`.

---

## 8. PDF Generation (`app/layers/pdf_builder.py`)

### 8.1 Rendering

```python
def build_pdf(proposal: ProposalOutput, company: CompanyConfig, session_id: str) -> str:
    html = render_template(
        "templates/proposal.html",
        proposal    = proposal,
        company     = company,      # name, colours from company.yaml
        generated_at = proposal.generated_at,
    )
    output_path = f"tmp/proposals/{session_id}.pdf"
    weasyprint.HTML(string=html).write_pdf(output_path)
    return output_path
```

`templates/proposal.html` is a WeasyPrint-compatible Jinja2 template. It iterates `proposal.sections` and renders each section. Company branding (name, primary colour) is injected from `company.yaml` — no branding is hardcoded in the template.

### 8.2 Lead Write Op 3 — Proposal Flag

Immediately after `build_pdf()` returns without error:

```python
# app/leads.py
leads.update_proposal_generated(
    client_name = proposal.client_name
)
session.proposal_ready = True
```

If `build_pdf()` raises an exception, `proposal_generated` is **not** set and `proposal_ready` remains `False`. The error is logged and escalation is triggered.

### 8.3 PDF Temp File Lifecycle

```
File created:   tmp/proposals/{session_id}.pdf
                └─ written by pdf_builder.py after all sections generated

File served:    GET /proposal/download/{session_id}
                └─ streams file as application/pdf
                └─ Content-Disposition: attachment; filename="proposal_{client_name}.pdf"
                └─ Returns 404 if session_id not found or proposal_ready == False

File deleted:   one of three events, whichever comes first:
  1. DELETE /session/{session_id}   — explicit session end by widget
  2. Session timeout                 — session_timeout_minutes from company.yaml
                                       background cleanup task in session.py
  3. Application restart             — tmp/ is not persistent storage;
                                       session state is also lost on restart
```

**The `tmp/proposals/` directory is ephemeral.** It is not backed up and is not served as a static directory. Only `GET /proposal/download/{session_id}` can access files within it.

---

## 9. Post-Proposal State

After `proposal_ready: true` is sent, the session transitions to `FlowState.COMPLETE` but **remains open**. The user may continue asking follow-up questions.

```
FlowState.COMPLETE
  │
  ├─ user asks follow-up question
  │    → INTENT_DETECTION
  │    → if faq intent: RETRIEVAL → GENERATION → back to COMPLETE
  │    → if proposal intent: bot explains proposal is already generated,
  │                           offers to answer questions or connect with the team
  │    → if escalation intent: ESCALATED
  │
  └─ session ends (DELETE /session or timeout)
       → tmp/proposals/{session_id}.pdf deleted
       → SessionState destroyed
```

---

## 10. Three Lead Write Operations — Summary

| # | Trigger | `app/leads.py` call | Fields written |
|---|---|---|---|
| 1 | `client_name` successfully extracted | `append_row(LeadRecord(...))` | `client_name`, `user_type`, `captured_at` |
| 2 | `email` and/or `phone` pass server-side validation | `update_row(client_name, email, phone)` | `email`, `phone` |
| 3 | `build_pdf()` returns without error | `update_proposal_generated(client_name)` | `proposal_generated = True` |

**Invariants:**
- Write Op 1 always happens before Write Op 2 (client_name is slot 1, contact is slot 2).
- Write Op 3 only happens if Write Ops 1 and 2 have both completed (proposal generation requires all slots to be filled).
- Raw unvalidated contact input is never written.
- Rows are never deleted.

---

## 11. Escalation Points in the Proposal Flow

| Phase | Trigger | Handler |
|---|---|---|
| Slot collection | `slot_attempt_counts[slot] >= 2` | `flow_controller.py` → `ESCALATED` |
| Contact validation | Contact fails regex twice | `flow_controller.py` → `ESCALATED` |
| Pre-proposal retrieval | `retrieve()` returns `[]` | `flow_controller.py` → `ESCALATED` |
| Pricing | `pricing_output.matched == False` | `flow_controller.py` → `ESCALATED` |
| Section generation | Malformed LLM output after 2 retries | `generator.py` → `ESCALATED` |
| PDF build | `build_pdf()` raises exception | `pdf_builder.py` → `ESCALATED` |

On escalation: `session.escalation_triggered = True`, `flow_state = ESCALATED`, SSE `done` event carries `escalated: true`. Widget disables input and shows `escalation_message` from `company.yaml`. Session remains in memory until timeout or DELETE.

---

## 12. Proposal Flow State Transitions (Complete)

```
SLOT_COLLECTION
  ├─ missing_slots not empty
  │    └─► ask next missing slot
  │          if next slot == "contact" → set input_type: "contact_form" in done event
  │
  ├─ slot_attempt_counts[any] >= 2
  │    └─► ESCALATED
  │
  └─ missing_slots == []
       └─► RETRIEVAL
             ├─ chunks returned
             │    └─► PROPOSAL_GENERATION
             │          ├─ pricing.matched == False → ESCALATED
             │          ├─ all sections generated + PDF written
             │          │    └─► COMPLETE
             │          └─ generation/PDF error → ESCALATED
             └─ chunks == [] → ESCALATED
```
