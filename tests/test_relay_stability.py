"""
tests/test_relay_stability.py — Relay crash-resistance tests.

Covers the malformed-JSON-from-GitHub paths in students.py and feedback.py
where GitHub could theoretically return a JSON list instead of a dict.
All tests mock _github_request so no real network calls are made.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

import pytest


def _b64(obj) -> str:
    """Encode a Python object to the base64-wrapped string GitHub returns."""
    return base64.b64encode(json.dumps(obj).encode()).decode()


# ─────────────────────────────────────────────────────────────
#  relay/api/students — malformed registry (list instead of dict)
# ─────────────────────────────────────────────────────────────


class TestStudentsRegistryMalformed:
    def test_list_registry_does_not_crash(self):
        """GitHub returning a JSON list for the registry must not crash the loader."""
        import relay.api.students as students_mod

        fake_response = {"content": _b64([1, 2, 3]), "sha": "abc123"}
        with patch.object(students_mod, "_github_request", return_value=fake_response):
            registry, sha = students_mod._load_registry()

        assert isinstance(registry, dict)
        assert "students" in registry
        assert sha == "abc123"

    def test_list_registry_returns_empty_students(self):
        """A malformed list registry must produce an empty students dict, not partial data."""
        import relay.api.students as students_mod

        fake_response = {"content": _b64(["garbage", "data"]), "sha": None}
        with patch.object(students_mod, "_github_request", return_value=fake_response):
            registry, _ = students_mod._load_registry()

        assert registry["students"] == {}


# ─────────────────────────────────────────────────────────────
#  relay/api/feedback — malformed store (list instead of dict)
# ─────────────────────────────────────────────────────────────


class TestFeedbackStoreMalformed:
    def test_list_store_does_not_crash(self):
        """GitHub returning a JSON list for the feedback store must not crash the loader."""
        import relay.api.feedback as feedback_mod

        fake_response = {"content": _b64([{"vote": "up"}]), "sha": "def456"}
        with patch.object(feedback_mod, "_github_request", return_value=fake_response):
            store, sha = feedback_mod._load_feedback_store()

        assert isinstance(store, dict)
        assert "votes" in store
        assert "aggregated" in store
        assert sha == "def456"

    def test_list_store_returns_empty_defaults(self):
        """A malformed list store must produce empty votes/aggregated, not partial data."""
        import relay.api.feedback as feedback_mod

        fake_response = {"content": _b64([1, 2, 3]), "sha": None}
        with patch.object(feedback_mod, "_github_request", return_value=fake_response):
            store, _ = feedback_mod._load_feedback_store()

        assert store["votes"] == []
        assert store["aggregated"] == {}


# ─────────────────────────────────────────────────────────────
#  relay/api/students — resend_confirmation action
# ─────────────────────────────────────────────────────────────


class TestResendConfirmation:
    """The resend_confirmation action re-sends the confirmation email for an
    existing active subscription without requiring unsubscribe/resubscribe."""

    def _registry_with_student(self):
        return {
            "students": {
                "au617716@uni.au.dk": {
                    "email": "au617716@uni.au.dk",
                    "package_ids": ["stars---stellar", "exoplanets"],
                    "max_papers_per_week": 6,
                    "active": True,
                    "password_salt": "aabb",
                    "password_hash": "scrypt$n=65536,r=8,p=1$deadbeef",
                    "created_at": "2026-03-20T10:00:00Z",
                    "updated_at": "2026-03-20T10:00:00Z",
                }
            }
        }

    def test_resend_sends_email_for_active_subscription(self):
        import relay.api.students as students_mod

        fake_response = {"content": _b64(self._registry_with_student()), "sha": "abc"}
        with (
            patch.object(students_mod, "_github_request", return_value=fake_response),
            patch.object(students_mod, "verify_password", return_value=True),
            patch.object(
                students_mod,
                "_send_subscription_confirmation",
                return_value=(True, None),
            ) as mock_send,
        ):
            status, result = students_mod._dispatch(
                {"action": "resend_confirmation", "email": "au617716@uni.au.dk", "password": "test"}
            )

        assert status == 200
        assert result["ok"] is True
        assert result["confirmation_email_sent"] is True
        assert result["confirmation_email_error"] is None
        mock_send.assert_called_once()

    def test_resend_rejects_wrong_password(self):
        import relay.api.students as students_mod

        fake_response = {"content": _b64(self._registry_with_student()), "sha": "abc"}
        with (
            patch.object(students_mod, "_github_request", return_value=fake_response),
            patch.object(students_mod, "verify_password", return_value=False),
        ):
            status, result = students_mod._dispatch(
                {"action": "resend_confirmation", "email": "au617716@uni.au.dk", "password": "wrong"}
            )

        assert status == 403

    def test_resend_rejects_inactive_subscription(self):
        import relay.api.students as students_mod

        reg = self._registry_with_student()
        reg["students"]["au617716@uni.au.dk"]["active"] = False
        fake_response = {"content": _b64(reg), "sha": "abc"}
        with (
            patch.object(students_mod, "_github_request", return_value=fake_response),
            patch.object(students_mod, "verify_password", return_value=True),
        ):
            status, result = students_mod._dispatch(
                {"action": "resend_confirmation", "email": "au617716@uni.au.dk", "password": "test"}
            )

        assert status == 400
        assert "inactive" in result["error"].lower()

    def test_resend_returns_404_for_unknown_email(self):
        import relay.api.students as students_mod

        fake_response = {"content": _b64({"students": {}}), "sha": "abc"}
        with patch.object(students_mod, "_github_request", return_value=fake_response):
            status, result = students_mod._dispatch(
                {"action": "resend_confirmation", "email": "nobody@uni.au.dk", "password": "x"}
            )

        assert status == 404
