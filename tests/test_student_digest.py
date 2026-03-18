"""
tests/test_student_digest.py — Edge-case and guard tests for student_digest.py.

Covers failure modes identified in Round 4 QA:
  - 0-paper guard: arXiv down → no email sent, exit non-zero
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import student_digest as sd


# ─────────────────────────────────────────────────────────────
#  main() — 0-paper early exit (all arXiv fetches failed)
# ─────────────────────────────────────────────────────────────


class TestStudentZeroPaperGuard:
    """When fetch_arxiv_papers returns [], main() must return 1 and never call send_email."""

    _FAKE_SUBSCRIPTION = {
        "email": "student@example.com",
        "active": True,
        "package_ids": ["exoplanets"],
        "max_papers_per_week": 6,
        "password_hash": "x",
        "password_salt": "y",
        "created_at": "2025-01-01",
        "manage_url": "https://example.com",
    }

    def test_zero_papers_skips_all_students_and_exits_nonzero(self):
        """When arXiv returns no papers, main() returns 1 and never sends email."""
        with (
            patch.object(sd, "fetch_student_subscriptions", return_value=[self._FAKE_SUBSCRIPTION]),
            patch.object(sd, "fetch_arxiv_papers", return_value=[]),
            patch.object(sd, "send_email") as mock_send,
            patch.object(sd, "ingest_feedback_from_github", return_value={}),
        ):
            result = sd.main(["--preview"])
        assert result == 1, "Expected exit code 1 when no papers fetched"
        mock_send.assert_not_called()
