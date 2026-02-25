"""Tests for app/main.py — FastAPI endpoints."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app
from app.session import store


@pytest.fixture(autouse=True)
def clean_store():
    """Clear session store before each test."""
    store._sessions.clear()
    yield
    store._sessions.clear()


@pytest.fixture
def client():
    return TestClient(app)


class TestSessionEndpoints:
    def test_session_start_returns_session_id(self, client):
        resp = client.post("/session/start")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert len(data["session_id"]) == 36  # UUID

    def test_session_delete_returns_success(self, client):
        resp = client.post("/session/start")
        sid = resp.json()["session_id"]
        del_resp = client.delete(f"/session/{sid}")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

    def test_session_delete_nonexistent_returns_false(self, client):
        resp = client.delete("/session/nonexistent-id")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


class TestCORS:
    def test_cors_header_present(self, client):
        resp = client.options(
            "/session/start",
            headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST"},
        )
        # CORS middleware should add the header
        assert resp.headers.get("access-control-allow-origin") == "*"


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["company"] == "Ions Energy"


class TestProposalDownload:
    def test_download_404_before_proposal_generated(self, client):
        resp = client.post("/session/start")
        sid = resp.json()["session_id"]
        dl = client.get(f"/proposal/download/{sid}")
        assert dl.status_code == 404

    def test_download_404_nonexistent_session(self, client):
        dl = client.get("/proposal/download/does-not-exist")
        assert dl.status_code == 404


class TestChatEndpoint:
    def test_chat_returns_event_stream_content_type(self, client):
        resp = client.post("/session/start")
        sid = resp.json()["session_id"]

        async def fake_advance(session, message):
            yield "Hello"

        with patch("app.main.flow_controller.advance", side_effect=fake_advance):
            with patch("app.main.flow_controller.get_done_payload") as mock_done:
                mock_done.return_value = MagicMock(
                    model_dump=lambda: {
                        "flow_state": "init",
                        "proposal_ready": False,
                        "escalated": False,
                        "input_type": None,
                    }
                )
                resp = client.post("/chat", json={"session_id": sid, "message": "hi"})

        assert resp.headers["content-type"].startswith("text/event-stream")

    def test_chat_404_for_unknown_session(self, client):
        resp = client.post("/chat", json={"session_id": "fake", "message": "hi"})
        assert resp.status_code == 404

    def test_chat_stream_contains_token_and_done_events(self, client):
        resp = client.post("/session/start")
        sid = resp.json()["session_id"]

        async def fake_advance(session, message):
            yield "tok1"
            yield "tok2"

        with patch("app.main.flow_controller.advance", side_effect=fake_advance):
            with patch("app.main.flow_controller.get_done_payload") as mock_done:
                mock_done.return_value = MagicMock(
                    model_dump=lambda: {
                        "flow_state": "intent_detection",
                        "proposal_ready": False,
                        "escalated": False,
                        "input_type": None,
                    }
                )
                resp = client.post("/chat", json={"session_id": sid, "message": "hi"})

        body = resp.text
        events = [
            json.loads(line[6:])
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        token_events = [e for e in events if e.get("type") == "token"]
        done_events  = [e for e in events if e.get("type") == "done"]

        assert len(token_events) == 2
        assert token_events[0]["content"] == "tok1"
        assert len(done_events) == 1
        assert done_events[0]["flow_state"] == "intent_detection"
