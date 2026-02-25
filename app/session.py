"""
In-memory session store. No persistence — session state is destroyed on end or timeout.
PDF files in tmp/proposals/ are deleted when the session is cleaned up.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from fastapi import HTTPException

from app.config_loader import config
from app.models.session_state import SessionState


class SessionStore:
    def __init__(self) -> None:
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
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    def delete(self, session_id: str) -> bool:
        """Remove session and delete its PDF if it exists."""
        pdf_path = Path(f"tmp/proposals/{session_id}.pdf")
        if pdf_path.exists():
            pdf_path.unlink()
        return bool(self._sessions.pop(session_id, None))

    def cleanup_expired(self) -> int:
        """
        Remove sessions that have exceeded session_timeout_minutes.
        Returns the number of sessions cleaned up.
        Called by the background task in main.py.
        """
        timeout_minutes = config.company.session_timeout_minutes
        cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)
        expired = [
            sid
            for sid, session in self._sessions.items()
            if session.created_at < cutoff
        ]
        for sid in expired:
            self.delete(sid)
        return len(expired)

    def count(self) -> int:
        return len(self._sessions)


# Module-level singleton — imported by main.py and all layers that need session access.
store = SessionStore()
