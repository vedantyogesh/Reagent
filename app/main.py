"""
FastAPI entry point — all five endpoints with SSE streaming.
CORS is open (*) to allow widget embedding on any domain.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
from pydantic import BaseModel

from app.config_loader import config  # validates all YAML at import time
from app.layers import flow_controller
from app.session import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background cleanup task
# ---------------------------------------------------------------------------

async def _session_cleanup_loop() -> None:
    """Periodically remove expired sessions. Runs every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        removed = store.cleanup_expired()
        if removed:
            logger.info("Cleaned up %d expired session(s)", removed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s backend", config.company.company_name)
    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    yield
    cleanup_task.cancel()
    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title=f"{config.company.company_name} Chatbot API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,   # must be False when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    message: str


class ProposalRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/session/start")
async def session_start() -> dict:
    """Create a new session. Returns session_id."""
    session = store.create()
    logger.info("Session created: %s", session.session_id)
    return {"session_id": session.session_id}


@app.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """
    Send a message and receive a streaming SSE response.
    Stream events:
      data: {"type": "token", "content": "..."}
      data: {"type": "done", "flow_state": "...", "proposal_ready": bool,
             "escalated": bool, "input_type": null|"contact_form"}
      data: {"type": "error", "message": "..."}
    """
    session = store.get_or_raise(request.session_id)

    async def event_stream():
        try:
            async for token in flow_controller.advance(session, request.message):
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
        except Exception as e:
            logger.exception("Unexpected error in chat stream: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'An unexpected error occurred.'})}\n\n"
        finally:
            done_payload = flow_controller.get_done_payload(session)
            yield f"data: {json.dumps({'type': 'done', **done_payload.model_dump()})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/proposal/generate")
async def proposal_generate(request: ProposalRequest) -> dict:
    """
    Direct proposal generation trigger (for integration/testing).
    Validates all slots are filled before starting.
    """
    session = store.get_or_raise(request.session_id)

    if session.missing_slots:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required slots: {session.missing_slots}",
        )

    if session.proposal_ready:
        return {"success": True, "message": "Proposal already generated"}

    # Trigger via a synthetic "generate proposal" message
    tokens = []
    async for token in flow_controller.advance(session, "Please generate the proposal"):
        tokens.append(token)

    return {
        "success": session.proposal_ready,
        "proposal": session.collected_slots.get("_proposal"),
    }


@app.get("/proposal/download/{session_id}")
async def proposal_download(session_id: str) -> FileResponse:
    """Download the generated proposal PDF."""
    session = store.get_or_raise(session_id)

    if not session.proposal_ready:
        raise HTTPException(status_code=404, detail="Proposal not yet generated")

    pdf_path = Path(f"tmp/proposals/{session_id}.pdf")
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Proposal file not found")

    client_name = session.collected_slots.get("client_name", "client")
    safe_name = "".join(c for c in client_name if c.isalnum() or c in " _-").strip()
    filename = f"proposal_{safe_name}.pdf"

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )


@app.delete("/session/{session_id}")
async def session_delete(session_id: str) -> dict:
    """End a session and clean up its PDF."""
    deleted = store.delete(session_id)
    logger.info("Session deleted: %s (found=%s)", session_id, deleted)
    return {"success": deleted}


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "company": config.company.company_name,
        "active_sessions": store.count(),
        "environment": os.environ.get("ENVIRONMENT", "development"),
    }
