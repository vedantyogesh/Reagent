# Config-Driven AI Chatbot & Proposal Generator

A config-driven AI chatbot and PDF proposal generator. Reusable across companies by swapping `/config/` and `/knowledge_base/` — zero application code changes required.

## Quick Start

```bash
# 1. Clone and install
git clone <repo>
cd ragent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — add OPENAI_API_KEY, PINECONE_API_KEY, PINECONE_INDEX_NAME

# 3. Ingest knowledge base into Pinecone (run once)
python scripts/ingest.py

# 4. Start the server
uvicorn app.main:app --reload

# 5. Open http://localhost:8000/docs to explore the API
```

## Embed the Widget

```html
<script
  src="https://your-deployment-url/widget/widget.js"
  data-api="https://your-deployment-url"
  data-position="bottom-right"
  data-primary-color="#0A84FF">
</script>
```

## Deploying to a New Company

1. Replace all files in `/config/` with company-specific values
2. Replace `knowledge_base/ions_energy.md` with the new knowledge base
3. Re-run `python scripts/ingest.py`
4. Update `PINECONE_INDEX_NAME` env var
5. Deploy — no code changes required

## Project Structure

```
app/
  config_loader.py     # Validates all YAML at startup
  session.py           # In-memory session store
  leads.py             # CSV lead capture (3 write ops)
  layers/
    entry.py           # Combined classification (1 LLM call)
    flow_controller.py # State machine
    extractor.py       # Slot extraction + contact validation
    retrieval.py       # Pinecone vector search
    pricing.py         # Deterministic pricing (pure Python)
    generator.py       # FAQ + Proposal generation (streaming)
    pdf_builder.py     # WeasyPrint PDF
  models/              # All Pydantic schemas

config/                # Company config — swap to redeploy
knowledge_base/        # Source knowledge base (Markdown)
scripts/ingest.py      # Knowledge base → Pinecone
widget/                # Embeddable vanilla JS widget
templates/             # WeasyPrint HTML template
tests/                 # 90 unit tests + 15 eval scenarios
```

## Running Tests

```bash
pytest tests/ -v
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `PINECONE_API_KEY` | Yes | Pinecone API key |
| `PINECONE_INDEX_NAME` | Yes | Pinecone index name (e.g. `ions-energy`) |
| `SESSION_SECRET` | Yes | Secret for session signing |
| `ENVIRONMENT` | No | `development` or `production` |

## Architecture

See [`docs/high-level-architecture.md`](docs/high-level-architecture.md) for full system architecture.

Key constraints (see [`CLAUDE.md`](CLAUDE.md) for full rules):
- LLM never computes prices — pricing is pure Python from `pricing_rules.yaml`
- All LLM outputs use JSON mode — no free-text parsing
- Session state is in-memory only
- Lead data written to `data/leads.csv` (Excel-compatible)
