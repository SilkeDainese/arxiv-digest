"""Tests for the failure report relay API."""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest


# ─────── Helpers ──────────────────────────────────────────────

VALID_REPORT = {
    "repo": "student-fork/arxiv-digest",
    "run_id": "987654321",
    "error": "SMTP authentication failed",
    "workflow": "digest",
    "timestamp": "2026-03-17T08:00:00+00:00",
}


class _FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler used by handler methods."""

    def __init__(self, body: dict[str, Any] | None = None):
        import io
        raw = json.dumps(body or {}).encode("utf-8")
        self.rfile = io.BytesIO(raw)
        self.headers = {"Content-Length": str(len(raw))}
        self.status = None
        self.response_body = None
        self._headers_sent: list[tuple[str, str]] = []

    def _respond(self, status: int, body: dict[str, Any]):
        self.status = status
        self.response_body = body

    # Stubs for BaseHTTPRequestHandler write methods (used by handler._respond)
    def send_response(self, code: int):
        self.status = code

    def send_header(self, key: str, value: str):
        self._headers_sent.append((key, value))

    def end_headers(self):
        pass

    @property
    def wfile(self):
        import io
        return io.BytesIO()


# ─────── Validation tests ────────────────────────────────────

class TestReportValidation:
    """Missing or empty required fields must return 400."""

    @pytest.mark.parametrize("field", ["repo", "run_id", "error", "timestamp", "workflow"])
    def test_missing_field_returns_400(self, field: str):
        from relay.api.report import _handle_report

        body = {k: v for k, v in VALID_REPORT.items() if k != field}
        status, payload = _handle_report(body)

        assert status == 400
        assert field in payload["error"]

    def test_empty_field_returns_400(self):
        from relay.api.report import _handle_report

        body = {**VALID_REPORT, "repo": "  "}
        status, payload = _handle_report(body)

        assert status == 400
        assert "repo" in payload["error"]


# ─────── Success path ────────────────────────────────────────

class TestReportSuccess:
    """A valid report stores the failure and creates an upstream issue."""

    def test_valid_report_stores_and_creates_issue(self):
        from relay.api.report import _handle_report

        fake_issue = {"html_url": "https://github.com/SilkeDainese/arxiv-digest/issues/42"}

        with (
            mock.patch("relay.api.report._load_report_store", return_value=([], "sha1")),
            mock.patch("relay.api.report._save_report_store") as mock_save,
            mock.patch("relay.api.report._create_issue", return_value=fake_issue["html_url"]) as mock_issue,
        ):
            status, payload = _handle_report(VALID_REPORT)

        assert status == 200
        assert payload["ok"] is True
        assert payload["issue_url"] == fake_issue["html_url"]

        # Verify the failure was appended to the store
        saved_store = mock_save.call_args[0][0]
        assert len(saved_store) == 1
        assert saved_store[0]["repo"] == VALID_REPORT["repo"]
        assert saved_store[0]["run_id"] == VALID_REPORT["run_id"]

        # Verify issue creation received the right arguments
        mock_issue.assert_called_once_with(
            VALID_REPORT["repo"],
            VALID_REPORT["run_id"],
            VALID_REPORT["error"],
            VALID_REPORT["workflow"],
        )

    def test_report_appends_to_existing_store(self):
        from relay.api.report import _handle_report

        existing = [{"repo": "old/repo", "run_id": "111", "error": "x", "workflow": "w", "timestamp": "t"}]

        with (
            mock.patch("relay.api.report._load_report_store", return_value=(existing, "sha2")),
            mock.patch("relay.api.report._save_report_store") as mock_save,
            mock.patch("relay.api.report._create_issue", return_value="https://github.com/issues/1"),
        ):
            status, _ = _handle_report(VALID_REPORT)

        assert status == 200
        saved_store = mock_save.call_args[0][0]
        assert len(saved_store) == 2


# ─────── Handler class tests ─────────────────────────────────

class TestHandlerPost:
    """The Vercel handler class routes POST requests correctly."""

    def test_post_delegates_to_handle_report(self):
        from relay.api.report import handler

        fake = _FakeHandler(VALID_REPORT)
        fake_issue_url = "https://github.com/SilkeDainese/arxiv-digest/issues/99"

        with (
            mock.patch(
                "relay.api.report._handle_report",
                return_value=(200, {"ok": True, "issue_url": fake_issue_url}),
            ) as mock_handle,
        ):
            handler.do_POST(fake)

        mock_handle.assert_called_once()
        assert fake.status == 200

    def test_post_missing_fields_returns_400(self):
        from relay.api.report import handler

        body = {k: v for k, v in VALID_REPORT.items() if k != "repo"}
        fake = _FakeHandler(body)

        with mock.patch(
            "relay.api.report._handle_report",
            return_value=(400, {"error": "Missing required fields: repo"}),
        ):
            handler.do_POST(fake)

        assert fake.status == 400
