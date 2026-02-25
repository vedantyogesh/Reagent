"""Tests for app/session.py — in-memory session store."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.session import SessionStore
from app.models.session_state import FlowState


@pytest.fixture
def fresh_store():
    return SessionStore()


class TestSessionStore:
    def test_create_returns_session_with_uuid(self, fresh_store):
        s = fresh_store.create()
        assert s.session_id
        assert len(s.session_id) == 36  # UUID format

    def test_create_initial_flow_state_is_init(self, fresh_store):
        s = fresh_store.create()
        assert s.flow_state == FlowState.INIT

    def test_get_existing_session(self, fresh_store):
        s = fresh_store.create()
        found = fresh_store.get(s.session_id)
        assert found is s

    def test_get_nonexistent_returns_none(self, fresh_store):
        assert fresh_store.get("nonexistent") is None

    def test_get_or_raise_raises_on_missing(self, fresh_store):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            fresh_store.get_or_raise("not-a-real-id")
        assert exc_info.value.status_code == 404

    def test_delete_removes_session(self, fresh_store):
        s = fresh_store.create()
        assert fresh_store.delete(s.session_id) is True
        assert fresh_store.get(s.session_id) is None

    def test_delete_nonexistent_returns_false(self, fresh_store):
        assert fresh_store.delete("ghost") is False

    def test_count(self, fresh_store):
        assert fresh_store.count() == 0
        fresh_store.create()
        fresh_store.create()
        assert fresh_store.count() == 2

    def test_cleanup_expired_removes_old_sessions(self, fresh_store):
        s = fresh_store.create()
        # Backdate created_at to exceed timeout
        s.created_at = datetime.utcnow() - timedelta(minutes=100)
        removed = fresh_store.cleanup_expired()
        assert removed == 1
        assert fresh_store.get(s.session_id) is None

    def test_cleanup_expired_keeps_fresh_sessions(self, fresh_store):
        fresh_store.create()
        removed = fresh_store.cleanup_expired()
        assert removed == 0
        assert fresh_store.count() == 1

    def test_multiple_sessions_independent(self, fresh_store):
        s1 = fresh_store.create()
        s2 = fresh_store.create()
        assert s1.session_id != s2.session_id
        s1.user_type = "enterprise"
        assert s2.user_type is None
