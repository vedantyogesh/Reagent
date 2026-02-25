# CLAUDE.md — Ions Energy Chatbot

## What this project is
A config-driven AI chatbot and proposal generator. First deployed for Ions Energy.
The same codebase can serve any company by swapping files in /config/.

## What you must read before touching code
1. This file
2. docs/ragent_spec.md (the full spec)
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

## Lead storage
CSV only — data/leads.csv. Not SQLite. Three write operations per session:
1. Append row on client_name extraction
2. Update email/phone on contact validation
3. Update proposal_generated=True on PDF creation

## Current status
Architecture approved. Implementation in progress.
Approved docs: high-level-architecture.md, rag-pipeline.md, proposal-flow.md, implementation-plan.md
