"""
tests/test_subscriber_api.py — Tests for the subscriber management API.

Covers GET /api/subscribers, POST /api/subscribers, and
DELETE /api/subscribers/<email>.  All file I/O is patched so no real
filesystem writes occur.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))

import server  # noqa: E402


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


@pytest.fixture
def empty_store(tmp_path, monkeypatch):
    """Point the server at an empty temporary subscribers file."""
    p = tmp_path / "subscribers.json"
    monkeypatch.setattr(server, "_SUBSCRIBERS_PATH", p)
    return p


@pytest.fixture
def seeded_store(tmp_path, monkeypatch):
    """Provide a pre-populated subscribers file with two records."""
    p = tmp_path / "subscribers.json"
    records = [
        {
            "email": "alice@example.com",
            "keywords": ["stellar evolution", "TESS"],
            "active": True,
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        },
        {
            "email": "bob@example.com",
            "keywords": ["cosmology"],
            "active": True,
            "created_at": "2024-02-01T00:00:00+00:00",
            "updated_at": "2024-02-01T00:00:00+00:00",
        },
    ]
    p.write_text(json.dumps(records), encoding="utf-8")
    monkeypatch.setattr(server, "_SUBSCRIBERS_PATH", p)
    return p


# ─────────────────────────────────────────────────────────────
#  GET /api/subscribers
# ─────────────────────────────────────────────────────────────


class TestSubscribersList:
    def test_empty_store_returns_empty_list(self, client, empty_store):
        resp = client.get("/api/subscribers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["subscribers"] == []
        assert data["count"] == 0

    def test_seeded_store_returns_all_subscribers(self, client, seeded_store):
        resp = client.get("/api/subscribers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 2
        emails = [s["email"] for s in data["subscribers"]]
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails

    def test_missing_file_returns_empty_list(self, client, tmp_path, monkeypatch):
        missing = tmp_path / "no_file.json"
        monkeypatch.setattr(server, "_SUBSCRIBERS_PATH", missing)
        resp = client.get("/api/subscribers")
        assert resp.status_code == 200
        assert resp.get_json()["subscribers"] == []

    def test_corrupt_file_returns_empty_list(self, client, tmp_path, monkeypatch):
        p = tmp_path / "subscribers.json"
        p.write_text("not-valid-json", encoding="utf-8")
        monkeypatch.setattr(server, "_SUBSCRIBERS_PATH", p)
        resp = client.get("/api/subscribers")
        assert resp.status_code == 200
        assert resp.get_json()["subscribers"] == []


# ─────────────────────────────────────────────────────────────
#  POST /api/subscribers
# ─────────────────────────────────────────────────────────────


class TestSubscribersAdd:
    def test_valid_payload_returns_201(self, client, empty_store):
        resp = client.post(
            "/api/subscribers",
            json={"email": "new@example.com", "keywords": ["machine learning"]},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True
        assert data["subscriber"]["email"] == "new@example.com"
        assert data["subscriber"]["keywords"] == ["machine learning"]
        assert data["subscriber"]["active"] is True
        assert "created_at" in data["subscriber"]

    def test_subscriber_is_persisted(self, client, empty_store):
        client.post(
            "/api/subscribers",
            json={"email": "persist@example.com", "keywords": ["quasars"]},
        )
        stored = json.loads(empty_store.read_text(encoding="utf-8"))
        assert len(stored) == 1
        assert stored[0]["email"] == "persist@example.com"

    def test_email_is_normalised_to_lowercase(self, client, empty_store):
        resp = client.post(
            "/api/subscribers",
            json={"email": "User@Example.COM", "keywords": ["neutrinos"]},
        )
        assert resp.status_code == 201
        assert resp.get_json()["subscriber"]["email"] == "user@example.com"

    def test_missing_email_returns_400(self, client, empty_store):
        resp = client.post("/api/subscribers", json={"keywords": ["k1"]})
        assert resp.status_code == 400
        assert "email" in resp.get_json()["error"].lower()

    def test_invalid_email_returns_400(self, client, empty_store):
        resp = client.post(
            "/api/subscribers",
            json={"email": "not-an-email", "keywords": ["k1"]},
        )
        assert resp.status_code == 400
        assert "email" in resp.get_json()["error"].lower()

    def test_missing_keywords_returns_400(self, client, empty_store):
        resp = client.post(
            "/api/subscribers",
            json={"email": "a@b.com"},
        )
        assert resp.status_code == 400
        assert "keywords" in resp.get_json()["error"].lower()

    def test_empty_keywords_list_returns_400(self, client, empty_store):
        resp = client.post(
            "/api/subscribers",
            json={"email": "a@b.com", "keywords": []},
        )
        assert resp.status_code == 400

    def test_keywords_with_only_blank_strings_returns_400(self, client, empty_store):
        resp = client.post(
            "/api/subscribers",
            json={"email": "a@b.com", "keywords": ["   ", ""]},
        )
        assert resp.status_code == 400

    def test_duplicate_email_returns_409(self, client, seeded_store):
        resp = client.post(
            "/api/subscribers",
            json={"email": "alice@example.com", "keywords": ["dark matter"]},
        )
        assert resp.status_code == 409
        assert "already" in resp.get_json()["error"].lower()

    def test_keywords_not_a_list_returns_400(self, client, empty_store):
        resp = client.post(
            "/api/subscribers",
            json={"email": "a@b.com", "keywords": "not a list"},
        )
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────
#  DELETE /api/subscribers/<email>
# ─────────────────────────────────────────────────────────────


class TestSubscribersDelete:
    def test_existing_subscriber_is_removed(self, client, seeded_store):
        resp = client.delete("/api/subscribers/alice@example.com")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["email"] == "alice@example.com"
        remaining = json.loads(seeded_store.read_text(encoding="utf-8"))
        assert len(remaining) == 1
        assert remaining[0]["email"] == "bob@example.com"

    def test_nonexistent_email_returns_404(self, client, seeded_store):
        resp = client.delete("/api/subscribers/nobody@example.com")
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"].lower()

    def test_case_insensitive_email_match(self, client, seeded_store):
        resp = client.delete("/api/subscribers/ALICE@example.com")
        assert resp.status_code == 200
        remaining = json.loads(seeded_store.read_text(encoding="utf-8"))
        assert not any(s["email"] == "alice@example.com" for s in remaining)

    def test_delete_from_empty_store_returns_404(self, client, empty_store):
        resp = client.delete("/api/subscribers/nobody@example.com")
        assert resp.status_code == 404

    def test_deleting_second_subscriber_leaves_first(self, client, seeded_store):
        client.delete("/api/subscribers/bob@example.com")
        remaining = json.loads(seeded_store.read_text(encoding="utf-8"))
        assert len(remaining) == 1
        assert remaining[0]["email"] == "alice@example.com"
