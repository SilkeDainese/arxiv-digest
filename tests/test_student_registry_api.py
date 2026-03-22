"""
tests/test_student_registry_api.py — Passwordless subscription lifecycle tests.

Covers the relay /api/students endpoint with token-based confirmation flow:
  subscribe request → confirmation email → token confirm → active subscription.
"""

import copy
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "relay" / "api" / "students.py"
SPEC = importlib.util.spec_from_file_location("student_registry_api_test", MODULE_PATH)
students_api = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(students_api)


TOKEN_SECRET = "test-token-secret"


def test_passwordless_lifecycle(monkeypatch):
    """Full subscribe → confirm → admin_list → unsubscribe → confirm lifecycle."""
    state = {"students": {}, "pending_tokens": {}}
    saved = {}
    email_calls = []

    def load_registry():
        return copy.deepcopy(state), "sha-1"

    def save_registry(registry, sha, message):
        state.update(copy.deepcopy(registry))
        saved["sha"] = sha
        saved["message"] = message

    monkeypatch.setattr(students_api, "_load_registry", load_registry)
    monkeypatch.setattr(students_api, "_save_registry", save_registry)
    monkeypatch.setattr(students_api, "STUDENT_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setattr(students_api, "STUDENT_TOKEN_SECRET", TOKEN_SECRET)
    monkeypatch.setattr(
        students_api,
        "_send_subscribe_confirmation",
        lambda email, token, package_ids: email_calls.append(("subscribe", email)) or (True, None),
    )
    monkeypatch.setattr(
        students_api,
        "_send_unsubscribe_confirmation",
        lambda email, token: email_calls.append(("unsubscribe", email)) or (True, None),
    )

    # Step 1: Request subscribe
    status, payload = students_api._dispatch({
        "action": "request_subscribe",
        "email": "AU612345@UNI.AU.DK",
        "package_ids": ["exoplanets"],
        "max_papers_per_week": 4,
    })

    assert status == 200
    assert payload["ok"] is True
    assert payload["confirmation_sent"] is True
    assert email_calls == [("subscribe", "au612345@uni.au.dk")]
    # Student NOT yet in registry
    assert "au612345@uni.au.dk" not in state["students"]
    # Pending token stored
    assert "au612345@uni.au.dk:subscribe" in state["pending_tokens"]

    # Step 2: Simulate clicking the confirmation link
    pending_entry = state["pending_tokens"]["au612345@uni.au.dk:subscribe"]
    token = pending_entry["token"]
    page_html, _ = students_api._handle_confirm(token)

    assert "You're subscribed!" in page_html
    assert "au612345@uni.au.dk" in state["students"]
    assert state["students"]["au612345@uni.au.dk"]["active"] is True
    assert state["students"]["au612345@uni.au.dk"]["package_ids"] == ["exoplanets"]
    assert state["students"]["au612345@uni.au.dk"]["max_papers_per_week"] == 4

    # Step 3: Admin list shows active student
    status, payload = students_api._dispatch({
        "action": "admin_list",
        "admin_token": "admin-secret",
    })
    assert status == 200
    assert len(payload["subscriptions"]) == 1
    assert payload["subscriptions"][0]["email"] == "au612345@uni.au.dk"

    # Step 4: Request unsubscribe
    # Reset rate limit for unsubscribe (separate action, shouldn't be limited)
    status, payload = students_api._dispatch({
        "action": "request_unsubscribe",
        "email": "au612345@uni.au.dk",
    })
    assert status == 200
    assert payload["confirmation_sent"] is True
    assert email_calls[-1] == ("unsubscribe", "au612345@uni.au.dk")

    # Step 5: Confirm unsubscribe
    unsub_entry = state["pending_tokens"]["au612345@uni.au.dk:unsubscribe"]
    page_html, _ = students_api._handle_confirm(unsub_entry["token"])

    assert "You've been unsubscribed" in page_html
    assert state["students"]["au612345@uni.au.dk"]["active"] is False

    # Step 6: Admin list (active only) is now empty
    status, payload = students_api._dispatch({
        "action": "admin_list",
        "admin_token": "admin-secret",
    })
    assert status == 200
    assert payload["subscriptions"] == []


def test_manage_page_has_no_password_fields():
    """Passwordless settings page must not have password inputs."""
    page = students_api._manage_page(
        "au612345@uni.au.dk",
        "",
        ["stars", "galaxies"],
        4,
    )

    # Has AU ID input
    assert "612345" in page
    assert "@uni.au.dk" in page
    # Has package checkboxes
    assert "Stars" in page
    assert "Galaxies" in page
    # Has subscribe button
    assert "Subscribe" in page
    # Has confirmation note
    assert "confirmation link" in page.lower() or "confirmation" in page.lower()
    # Has unsubscribe info note (not a button — unsubscribe moved to digest email)
    assert "unsubscribe" in page.lower()
    # NO password fields
    assert 'type="password"' not in page
    assert "New password" not in page
    # Has correct initial values
    assert 'const initialPackages = ["stars", "galaxies"]' in page


def test_manage_page_uses_brand_fonts():
    """Settings page uses DM Serif Display for headings and IBM Plex Sans for body."""
    page = students_api._manage_page("", "", [], 6)
    assert "DM Serif Display" in page
    assert "IBM Plex Sans" in page


def test_manage_page_has_stepper():
    """Max papers uses a stepper control, not a plain number input."""
    page = students_api._manage_page("", "", [], 8)
    assert "stepper" in page.lower()
    assert "adjustMax" in page


def test_manage_page_single_column_packages():
    """Package checkboxes are in a single column (flex-direction: column)."""
    page = students_api._manage_page("", "", [], 6)
    assert "flex-direction: column" in page


def test_expired_token_shows_error_page(monkeypatch):
    """Clicking an expired confirmation link shows a helpful error page."""
    monkeypatch.setattr(students_api, "STUDENT_TOKEN_SECRET", TOKEN_SECRET)
    import relay.api._registry as reg
    token = reg.generate_confirmation_token(
        "au612345@uni.au.dk", "subscribe", {}, TOKEN_SECRET, ttl_seconds=0,
    )
    import time
    time.sleep(0.1)

    state = {"students": {}, "pending_tokens": {}}
    monkeypatch.setattr(students_api, "_load_registry", lambda: (copy.deepcopy(state), "sha"))
    monkeypatch.setattr(students_api, "_save_registry", lambda *a: None)

    page_html, _ = students_api._handle_confirm(token)
    assert "expired" in page_html.lower() or "went wrong" in page_html.lower()
    assert "settings" in page_html.lower()


def test_rate_limit_rejects_rapid_requests(monkeypatch):
    """Second subscribe request within 15 min is rejected."""
    state = {"students": {}, "pending_tokens": {}}
    monkeypatch.setattr(students_api, "_load_registry", lambda: (copy.deepcopy(state), "sha"))
    monkeypatch.setattr(students_api, "_save_registry", lambda reg, sha, msg: state.update(copy.deepcopy(reg)))
    monkeypatch.setattr(students_api, "STUDENT_TOKEN_SECRET", TOKEN_SECRET)
    monkeypatch.setattr(students_api, "_send_subscribe_confirmation", lambda *a: (True, None))

    # First request succeeds
    status, _ = students_api._dispatch({
        "action": "request_subscribe",
        "email": "au612345@uni.au.dk",
        "package_ids": ["stars"],
    })
    assert status == 200

    # Second request within 15 min rejected (ValueError → 400)
    with pytest.raises(ValueError, match="[Rr]ecent"):
        students_api._dispatch({
            "action": "request_subscribe",
            "email": "au612345@uni.au.dk",
            "package_ids": ["galaxies"],
        })


# ─────── Email validation tests ──────────────────────────────

class TestNormaliseEmail:
    """normalise_email now validates format."""

    def test_valid_email_is_normalised(self):
        assert students_api.normalise_email("AU612345@UNI.AU.DK") == "au612345@uni.au.dk"

    def test_email_without_at_raises(self):
        with pytest.raises(ValueError, match="Invalid email"):
            students_api.normalise_email("notanemail")

    def test_email_without_domain_tld_raises(self):
        with pytest.raises(ValueError, match="Invalid email"):
            students_api.normalise_email("user@nodot")

    def test_empty_string_returns_empty(self):
        assert students_api.normalise_email("") == ""

    def test_request_subscribe_with_invalid_email_raises(self, monkeypatch):
        monkeypatch.setattr(students_api, "_load_registry", lambda: ({"students": {}, "pending_tokens": {}}, None))
        monkeypatch.setattr(students_api, "_save_registry", lambda *a: None)
        monkeypatch.setattr(students_api, "STUDENT_TOKEN_SECRET", TOKEN_SECRET)
        monkeypatch.setattr(students_api, "_send_subscribe_confirmation", lambda *a: (False, None))
        with pytest.raises(ValueError, match="Invalid email"):
            students_api._dispatch({
                "action": "request_subscribe",
                "email": "notanemail",
                "package_ids": ["stars"],
            })


# ─────── Phase 1 UX redesign: terminology ────────────────────

def test_manage_page_says_categories_not_packages():
    """Manage page must use 'categories' instead of 'packages' in user-facing text."""
    page = students_api._manage_page("au612345@uni.au.dk", "", ["stars"], 6)
    page_lower = page.lower()
    assert "categories" in page_lower, "Manage page should say 'categories'"
    # "packages" must not appear in user-visible text (HTML content),
    # but may appear in code (variable names, CSS class names, JS identifiers).
    # Strip out <script> and <style> blocks, then check.
    import re
    visible = re.sub(r"<script[\s\S]*?</script>", "", page, flags=re.IGNORECASE)
    visible = re.sub(r"<style[\s\S]*?</style>", "", visible, flags=re.IGNORECASE)
    visible = re.sub(r"<!--[\s\S]*?-->", "", visible)
    # Also strip HTML tag attributes (class names, ids, etc.)
    visible = re.sub(r"<[^>]+>", " ", visible)
    assert "package" not in visible.lower(), (
        f"Found 'package' in user-visible text on manage page"
    )


def test_subscribe_confirmation_email_says_categories(monkeypatch):
    """Subscribe confirmation email must say 'categories', not 'packages'."""
    email_calls = []

    def capture_send_email(to, subject, plain_text, html_body):
        email_calls.append({"plain": plain_text, "html": html_body})
        return True, None

    monkeypatch.setattr(students_api, "_send_email", capture_send_email)
    monkeypatch.setattr(students_api, "SMTP_USER", "test@example.com")
    monkeypatch.setattr(students_api, "SMTP_PASSWORD", "password")

    students_api._send_subscribe_confirmation(
        "au612345@uni.au.dk", "fake-token", ["stars", "galaxies"],
    )

    assert len(email_calls) == 1
    html_body = email_calls[0]["html"]
    plain_body = email_calls[0]["plain"]
    assert "categories" in html_body.lower(), "Confirmation HTML should say 'categories'"
    assert "categories" in plain_body.lower(), "Confirmation plaintext should say 'categories'"
    # "PACKAGES" must not appear in user-visible labels
    assert "YOUR PACKAGES" not in html_body, "Confirmation HTML should not say 'YOUR PACKAGES'"
    assert "Your packages:" not in plain_body, "Confirmation plain should not say 'Your packages:'"


# ─────── Phase 2 UX redesign: visual consistency ──────────────

def test_unsubscribe_email_uses_terracotta(monkeypatch):
    """Unsubscribe confirmation email button must use TERRACOTTA (#9E5544), not ALERT_RED."""
    email_calls = []

    def capture_send_email(to, subject, plain_text, html_body):
        email_calls.append({"html": html_body})
        return True, None

    monkeypatch.setattr(students_api, "_send_email", capture_send_email)
    monkeypatch.setattr(students_api, "SMTP_USER", "test@example.com")
    monkeypatch.setattr(students_api, "SMTP_PASSWORD", "password")

    students_api._send_unsubscribe_confirmation("au612345@uni.au.dk", "fake-token")

    assert len(email_calls) == 1
    html_body = email_calls[0]["html"]
    assert "#9E5544" in html_body, "Unsubscribe button must use TERRACOTTA (#9E5544)"
    assert "#C0392B" not in html_body, "Unsubscribe button must not use ALERT_RED (#C0392B)"


def test_signup_page_has_no_unsubscribe_button():
    """Manage page in default mode must not show an Unsubscribe button."""
    import re
    page = students_api._manage_page("au612345@uni.au.dk", "", ["stars"], 6)
    # The word "unsubscribe" may appear in info text, but not as a clickable button
    # Find all <button> elements and check none contain "unsubscribe"
    buttons = re.findall(r"<button[^>]*>.*?</button>", page, flags=re.DOTALL | re.IGNORECASE)
    for btn in buttons:
        assert "unsubscribe" not in btn.lower(), (
            f"Found Unsubscribe button on signup page: {btn[:80]}"
        )


# ─────── mark_welcome_sent action ─────────────────────────────

def test_mark_welcome_sent_sets_flag(monkeypatch):
    """mark_welcome_sent must set welcome_sent=True for the given email."""
    state = {
        "students": {
            "au612345@uni.au.dk": {
                "email": "au612345@uni.au.dk",
                "package_ids": ["stars"],
                "max_papers_per_week": 6,
                "active": True,
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
                "welcome_sent": False,
            },
        },
        "pending_tokens": {},
    }

    monkeypatch.setattr(students_api, "_load_registry", lambda: (copy.deepcopy(state), "sha-1"))
    monkeypatch.setattr(
        students_api, "_save_registry",
        lambda reg, sha, msg: state.update(copy.deepcopy(reg)),
    )
    monkeypatch.setattr(students_api, "STUDENT_ADMIN_TOKEN", "admin-secret")

    status, payload = students_api._dispatch({
        "action": "mark_welcome_sent",
        "admin_token": "admin-secret",
        "email": "au612345@uni.au.dk",
    })

    assert status == 200
    assert payload["ok"] is True
    assert state["students"]["au612345@uni.au.dk"]["welcome_sent"] is True


def test_mark_welcome_sent_requires_admin(monkeypatch):
    """mark_welcome_sent must reject requests without valid admin token."""
    monkeypatch.setattr(students_api, "STUDENT_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setattr(
        students_api, "_load_registry",
        lambda: ({"students": {}, "pending_tokens": {}}, None),
    )

    with pytest.raises(PermissionError):
        students_api._dispatch({
            "action": "mark_welcome_sent",
            "admin_token": "wrong-token",
            "email": "au612345@uni.au.dk",
        })


# ─────── admin_stats action ──────────────────────────────────

def test_admin_stats_returns_counts(monkeypatch):
    """admin_stats must return correct total_active and total_inactive counts."""
    state = {
        "students": {
            "a@uni.au.dk": {
                "email": "a@uni.au.dk", "package_ids": ["stars"],
                "max_papers_per_week": 6, "active": True,
                "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
                "welcome_sent": True,
            },
            "b@uni.au.dk": {
                "email": "b@uni.au.dk", "package_ids": ["exoplanets"],
                "max_papers_per_week": 4, "active": True,
                "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
                "welcome_sent": False,
            },
            "c@uni.au.dk": {
                "email": "c@uni.au.dk", "package_ids": ["galaxies"],
                "max_papers_per_week": 8, "active": False,
                "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
                "welcome_sent": True,
            },
        },
        "pending_tokens": {},
    }
    monkeypatch.setattr(students_api, "_load_registry", lambda: (copy.deepcopy(state), "sha"))
    monkeypatch.setattr(students_api, "STUDENT_ADMIN_TOKEN", "admin-secret")

    status, payload = students_api._dispatch({
        "action": "admin_stats",
        "admin_token": "admin-secret",
    })

    assert status == 200
    assert payload["ok"] is True
    assert payload["total_active"] == 2
    assert payload["total_inactive"] == 1
    assert payload["welcome_pending"] == 1


def test_admin_stats_category_distribution(monkeypatch):
    """admin_stats must return correct category_distribution from active subscriptions."""
    state = {
        "students": {
            "a@uni.au.dk": {
                "email": "a@uni.au.dk", "package_ids": ["stars", "exoplanets"],
                "max_papers_per_week": 6, "active": True,
                "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
                "welcome_sent": True,
            },
            "b@uni.au.dk": {
                "email": "b@uni.au.dk", "package_ids": ["exoplanets"],
                "max_papers_per_week": 4, "active": True,
                "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
                "welcome_sent": False,
            },
            "c@uni.au.dk": {
                "email": "c@uni.au.dk", "package_ids": ["galaxies"],
                "max_papers_per_week": 8, "active": False,
                "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
                "welcome_sent": True,
            },
        },
        "pending_tokens": {},
    }
    monkeypatch.setattr(students_api, "_load_registry", lambda: (copy.deepcopy(state), "sha"))
    monkeypatch.setattr(students_api, "STUDENT_ADMIN_TOKEN", "admin-secret")

    status, payload = students_api._dispatch({
        "action": "admin_stats",
        "admin_token": "admin-secret",
    })

    assert status == 200
    # Only active subscriptions count
    assert payload["category_distribution"]["exoplanets"] == 2
    assert payload["category_distribution"]["stars"] == 1
    assert "galaxies" not in payload["category_distribution"]
    # max_papers distribution (active only)
    assert payload["max_papers_distribution"]["6"] == 1
    assert payload["max_papers_distribution"]["4"] == 1


# ─────── Settings token flow (Phase 3) ────────────────────────

def test_settings_token_renders_settings_mode(monkeypatch):
    """GET with a valid change_settings token renders settings mode with readonly email."""
    import relay.api._registry as reg
    monkeypatch.setattr(students_api, "STUDENT_TOKEN_SECRET", TOKEN_SECRET)

    state = {
        "students": {
            "au612345@uni.au.dk": {
                "email": "au612345@uni.au.dk",
                "package_ids": ["stars", "galaxies"],
                "max_papers_per_week": 6,
                "active": True,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
        "pending_tokens": {},
    }
    monkeypatch.setattr(students_api, "_load_registry", lambda: (state, "sha"))
    monkeypatch.setattr(students_api, "_save_registry", lambda *a: None)

    token = reg.generate_confirmation_token(
        "au612345@uni.au.dk", "change_settings", {}, TOKEN_SECRET,
        ttl_seconds=7 * 86400,
    )

    page_html, content_type = students_api._handle_settings_get(token)
    assert content_type == "text/html"
    assert "Update settings" in page_html
    assert "readonly" in page_html.lower()
    assert "au612345@uni.au.dk" in page_html


def test_update_settings_applies_directly(monkeypatch):
    """POST with valid settings token updates subscription without confirmation email."""
    import copy
    import relay.api._registry as reg
    monkeypatch.setattr(students_api, "STUDENT_TOKEN_SECRET", TOKEN_SECRET)

    state = {
        "students": {
            "au612345@uni.au.dk": {
                "email": "au612345@uni.au.dk",
                "package_ids": ["stars"],
                "max_papers_per_week": 6,
                "active": True,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
        "pending_tokens": {},
    }
    saved_registries = []

    def load_registry():
        return copy.deepcopy(state), "sha-1"

    def save_registry(registry, sha, message):
        saved_registries.append(copy.deepcopy(registry))
        state.update(copy.deepcopy(registry))

    monkeypatch.setattr(students_api, "_load_registry", load_registry)
    monkeypatch.setattr(students_api, "_save_registry", save_registry)

    email_calls = []
    monkeypatch.setattr(
        students_api,
        "_send_subscribe_confirmation",
        lambda *a: email_calls.append("subscribe") or (True, None),
    )

    token = reg.generate_confirmation_token(
        "au612345@uni.au.dk", "change_settings", {}, TOKEN_SECRET,
        ttl_seconds=7 * 86400,
    )

    page_html, content_type = students_api._handle_settings_post(
        token, ["galaxies", "cosmology"], 10,
    )

    # Subscription updated directly
    assert state["students"]["au612345@uni.au.dk"]["package_ids"] == ["galaxies", "cosmology"]
    assert state["students"]["au612345@uni.au.dk"]["max_papers_per_week"] == 10
    # No confirmation email sent
    assert email_calls == []
    # Returns success page
    assert "Settings updated" in page_html


def test_settings_updated_landing_page(monkeypatch):
    """After successful settings update, response shows categories."""
    import copy
    import relay.api._registry as reg
    monkeypatch.setattr(students_api, "STUDENT_TOKEN_SECRET", TOKEN_SECRET)

    state = {
        "students": {
            "au612345@uni.au.dk": {
                "email": "au612345@uni.au.dk",
                "package_ids": ["stars"],
                "max_papers_per_week": 6,
                "active": True,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
        "pending_tokens": {},
    }
    monkeypatch.setattr(students_api, "_load_registry", lambda: (copy.deepcopy(state), "sha"))
    monkeypatch.setattr(students_api, "_save_registry", lambda *a: state.update(copy.deepcopy(a[0])))

    token = reg.generate_confirmation_token(
        "au612345@uni.au.dk", "change_settings", {}, TOKEN_SECRET,
        ttl_seconds=7 * 86400,
    )

    page_html, _ = students_api._handle_settings_post(token, ["galaxies"], 8)
    assert "Settings updated" in page_html
    assert "Galaxies" in page_html
    assert "au612345@uni.au.dk" in page_html


def test_signup_page_says_subscribe_not_update():
    """Default manage page (no token) shows 'Subscribe', not 'Update settings'."""
    page = students_api._manage_page("", "", [], 6)
    assert "Subscribe" in page
    assert "Update settings" not in page
