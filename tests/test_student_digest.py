"""
tests/test_student_digest.py — Edge-case and guard tests for student_digest.py.

Covers failure modes identified in Round 4 QA:
  - 0-paper guard: arXiv down → no email sent, exit non-zero
  - Package ordering: category match must outrank keyword-only match
"""

from __future__ import annotations

from unittest.mock import call, patch, MagicMock

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


# ─────────────────────────────────────────────────────────────
#  annotate_student_packages — category match must take priority
# ─────────────────────────────────────────────────────────────


class TestAnnotateStudentPackagesOrdering:
    """Category matches must rank before keyword-only matches in student_package_ids.

    Regression: galaxy papers that also mention "stellar" were being labelled
    "Stars" because AVAILABLE_STUDENT_PACKAGES is iterated in fixed order and
    "stars" appears before "galaxies".
    """

    def test_galaxy_paper_with_stellar_keyword_has_galaxies_first(self):
        """A paper in astro-ph.GA that also matches 'stellar' must list 'galaxies' first."""
        # This paper lives in the Galaxies category but its abstract mentions "stellar"
        # so it matches the "stars" keyword set as well.
        paper = {
            "id": "2501.00001",
            "title": "Stellar populations in nearby galaxies",
            "category": "astro-ph.GA",
            "matched_keywords": ["stellar", "galaxy"],
        }
        sd.annotate_student_packages([paper])

        pkg_ids = paper["student_package_ids"]
        assert "galaxies" in pkg_ids, "Expected 'galaxies' to be in matched packages"
        assert pkg_ids[0] == "galaxies", (
            f"Expected 'galaxies' as first package (category match) but got '{pkg_ids[0]}'"
        )


# ─────────────────────────────────────────────────────────────
#  --send-preview flag
# ─────────────────────────────────────────────────────────────


class TestSendPreviewFlag:
    """Verify --send-preview sends one email to RECIPIENT_EMAIL with [PREVIEW] prefix."""

    _FAKE_SUBSCRIPTION = {
        "email": "student@example.com",
        "active": True,
        "package_ids": ["exoplanets"],
        "max_papers_per_week": 6,
        "created_at": "2025-01-01",
        "manage_url": "https://example.com",
    }

    _FAKE_PAPER = {
        "id": "2501.99999",
        "title": "A fake paper about exoplanets",
        "category": "astro-ph.EP",
        "abstract": "Exoplanet detection methods.",
        "authors": ["A. Test"],
        "published": "2025-01-01T00:00:00Z",
        "matched_keywords": ["exoplanet"],
        "relevance_score": 8,
        "student_package_ids": ["exoplanets"],
        "student_au_priority": 0,
        "expert_net": 0,
    }

    def _run_send_preview(self, env_overrides=None):
        """Helper: run main(["--send-preview"]) with standard mocks.

        Returns (exit_code, mock_send_email).
        """
        env = {"RECIPIENT_EMAIL": "silke@example.com", "STUDENT_ADMIN_TOKEN": "tok"}
        if env_overrides:
            env.update(env_overrides)
        with (
            patch.dict("os.environ", env, clear=False),
            patch.object(sd, "fetch_student_subscriptions", return_value=[self._FAKE_SUBSCRIPTION]),
            patch.object(sd, "fetch_arxiv_papers", return_value=[self._FAKE_PAPER]),
            patch.object(sd, "ingest_feedback_from_github", return_value={}),
            patch.object(sd, "pre_filter", return_value=[self._FAKE_PAPER]),
            patch.object(sd, "fetch_aggregate_feedback", return_value={}),
            patch.object(sd, "analyse_papers", return_value=([self._FAKE_PAPER], "keyword")),
            patch.object(sd, "annotate_student_packages"),
            patch.object(sd, "detect_au_researchers"),
            patch.object(sd, "detect_delights"),
            patch.object(sd, "render_html", return_value="<html>preview</html>"),
            patch.object(sd, "send_email", return_value=True) as mock_send,
        ):
            result = sd.main(["--send-preview"])
        return result, mock_send

    def test_send_preview_flag_uses_recipient_email(self):
        """--send-preview sends to RECIPIENT_EMAIL, not the student's email."""
        result, mock_send = self._run_send_preview()
        assert result == 0
        mock_send.assert_called_once()
        config_arg = mock_send.call_args[0][3]
        assert config_arg["recipient_email"] == "silke@example.com"

    def test_send_preview_adds_subject_prefix(self):
        """--send-preview passes '[PREVIEW] ' as subject_prefix to send_email."""
        result, mock_send = self._run_send_preview()
        assert result == 0
        mock_send.assert_called_once()
        kwargs = mock_send.call_args
        assert kwargs.kwargs.get("subject_prefix") == "[PREVIEW] " or (
            len(kwargs.args) > 5 and kwargs.args[5] == "[PREVIEW] "
        )

    def test_send_preview_mutually_exclusive_with_preview(self):
        """--send-preview and --preview cannot be used together."""
        with pytest.raises(SystemExit):
            sd.build_parser().parse_args(["--preview", "--send-preview"])


# ─────────────────────────────────────────────────────────────
#  Welcome header — first digest only
# ─────────────────────────────────────────────────────────────


class TestWelcomeHeader:
    """First digest must show a welcome block; subsequent ones must not."""

    def test_make_student_digest_config_sets_show_welcome_when_not_sent(self):
        """Config gets show_welcome=True when welcome_sent is False."""
        base = sd.build_student_base_config()
        subscription = {
            "email": "student@example.com",
            "package_ids": ["exoplanets"],
            "max_papers_per_week": 6,
            "welcome_sent": False,
        }
        config = sd.make_student_digest_config(base, subscription)
        assert config.get("show_welcome") is True

    def test_make_student_digest_config_no_welcome_when_already_sent(self):
        """Config must NOT have show_welcome when welcome_sent is True."""
        base = sd.build_student_base_config()
        subscription = {
            "email": "student@example.com",
            "package_ids": ["exoplanets"],
            "max_papers_per_week": 6,
            "welcome_sent": True,
        }
        config = sd.make_student_digest_config(base, subscription)
        assert not config.get("show_welcome")

    def test_make_student_digest_config_no_welcome_when_field_absent(self):
        """Config must NOT have show_welcome when welcome_sent key is missing (backward compat)."""
        base = sd.build_student_base_config()
        subscription = {
            "email": "student@example.com",
            "package_ids": ["exoplanets"],
            "max_papers_per_week": 6,
        }
        config = sd.make_student_digest_config(base, subscription)
        assert not config.get("show_welcome")

    def test_first_digest_has_welcome_header(self):
        """Rendered HTML with show_welcome=True must contain the welcome heading."""
        from digest import render_html
        config = {
            "digest_name": "AU Astronomy Student Weekly",
            "researcher_name": "Student",
            "research_context": "",
            "institution": "",
            "department": "",
            "tagline": "Your categories: Exoplanets",
            "github_repo": "",
            "recipient_view_mode": "deep_read",
            "subscription_manage_url": "https://example.com/manage",
            "subscription_unsubscribe_url": "https://example.com/unsub",
            "show_welcome": True,
        }
        paper = {
            "id": "2501.00001",
            "title": "Exoplanet atmospheres",
            "abstract": "We study atmospheres.",
            "authors": ["A. Test"],
            "published": "2025-01-01",
            "category": "astro-ph.EP",
            "url": "https://arxiv.org/abs/2501.00001",
            "matched_keywords": ["exoplanet"],
            "relevance_score": 7,
            "student_package_ids": ["exoplanets"],
            "student_au_priority": 0,
            "expert_net": 0,
            "colleague_matches": [],
        }
        html = render_html([paper], [], config, "January 01, 2025", own_papers=[], scoring_method="keyword")
        assert "Welcome to the AU student digest" in html

    def test_second_digest_has_no_welcome_header(self):
        """Rendered HTML without show_welcome must NOT contain the welcome block."""
        from digest import render_html
        config = {
            "digest_name": "AU Astronomy Student Weekly",
            "researcher_name": "Student",
            "research_context": "",
            "institution": "",
            "department": "",
            "tagline": "Your categories: Exoplanets",
            "github_repo": "",
            "recipient_view_mode": "deep_read",
            "subscription_manage_url": "https://example.com/manage",
            "subscription_unsubscribe_url": "https://example.com/unsub",
        }
        paper = {
            "id": "2501.00001",
            "title": "Exoplanet atmospheres",
            "abstract": "We study atmospheres.",
            "authors": ["A. Test"],
            "published": "2025-01-01",
            "category": "astro-ph.EP",
            "url": "https://arxiv.org/abs/2501.00001",
            "matched_keywords": ["exoplanet"],
            "relevance_score": 7,
            "student_package_ids": ["exoplanets"],
            "student_au_priority": 0,
            "expert_net": 0,
            "colleague_matches": [],
        }
        html = render_html([paper], [], config, "January 01, 2025", own_papers=[], scoring_method="keyword")
        assert "Welcome to the AU student digest" not in html


# ─────────────────────────────────────────────────────────────
#  rewrite_summaries_for_students()
# ─────────────────────────────────────────────────────────────


class TestStudentSummaryRewrite:
    """Student summaries should be rewritten to avoid jargon."""

    def _make_papers(self):
        return [
            {
                "title": "Black hole superradiance from ultralight axions",
                "plain_summary": "Black hole superradiance is a powerful probe of ultralight axions.",
                "abstract": "We constrain ultralight axion masses using superradiant instabilities.",
            },
            {
                "title": "TOI-1232 b: A warm Neptune",
                "plain_summary": "TOI-1232 is a G-dwarf with $1.06 M_\\odot$.",
                "abstract": "We report two planets transiting TOI-1232.",
            },
        ]

    def test_rewrite_replaces_plain_summary(self):
        """Successful rewrite replaces plain_summary with student-friendly version."""
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text='[{"summary": "Spinning black holes can reveal invisible particles."}, {"summary": "Two warm planets found orbiting a Sun-like star."}]')]
        )

        papers = self._make_papers()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            sd.rewrite_summaries_for_students(papers, "fake-key")

        assert papers[0]["plain_summary"] == "Spinning black holes can reveal invisible particles."
        assert papers[1]["plain_summary"] == "Two warm planets found orbiting a Sun-like star."

    def test_rewrite_keeps_original_on_failure(self):
        """If the API call fails, original summaries are preserved."""
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API error")

        papers = self._make_papers()
        original_0 = papers[0]["plain_summary"]
        original_1 = papers[1]["plain_summary"]
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            sd.rewrite_summaries_for_students(papers, "fake-key")

        assert papers[0]["plain_summary"] == original_0
        assert papers[1]["plain_summary"] == original_1

    def test_rewrite_skipped_without_api_key(self):
        """No API key means no rewrite — originals preserved."""
        papers = self._make_papers()
        original = papers[0]["plain_summary"]
        sd.rewrite_summaries_for_students(papers, "")
        assert papers[0]["plain_summary"] == original
