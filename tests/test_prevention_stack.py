"""
tests/test_prevention_stack.py — Prevention stack verification tests.

Verifies the credential-leak prevention measures installed on 2026-04-10:
  1. Global gitignore blocks subscriptions.json from being tracked
  2. No password/hash/salt fields exist in any tracked JSON file in the repo
  3. No auth code (password_hash, password_salt, hash_password, verify_password,
     scrypt, bcrypt, pbkdf2) remains in the current codebase
  4. gitleaks pre-commit hook is installed and executable
  5. Global gitignore contains the required sensitive-file patterns

These are regression tests. If any of them fail, a credential leak is either
present or a prevention layer has been silently removed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────────────
#  1. No credential fields in any tracked JSON file
# ─────────────────────────────────────────────────────────────────────

def _tracked_json_files() -> list[Path]:
    """Return all JSON files currently tracked by git in this repo."""
    result = subprocess.run(
        ["git", "ls-files", "*.json", "**/*.json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    paths = [REPO_ROOT / p.strip() for p in result.stdout.splitlines() if p.strip()]
    return [p for p in paths if p.exists()]


BANNED_CREDENTIAL_FIELDS = {
    "password_hash",
    "password_salt",
    "hash",
    "salt",
    "password",
    "secret",
    "private_key",
    "api_key",
}


class TestNoCredentialsInTrackedJSON:
    def test_no_credential_fields_in_tracked_json_files(self):
        """No tracked JSON file may contain password/hash/salt credential fields."""
        violations: list[str] = []
        for path in _tracked_json_files():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            self._scan_for_credentials(data, str(path.relative_to(REPO_ROOT)), violations)
        assert not violations, (
            "Credential fields found in tracked JSON files:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def _scan_for_credentials(
        self, obj: object, path: str, violations: list[str], depth: int = 0
    ) -> None:
        if depth > 10:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_lower = key.lower()
                if key_lower in BANNED_CREDENTIAL_FIELDS and isinstance(value, str) and len(value) > 8:
                    violations.append(f"{path}: key '{key}' with value of length {len(value)}")
                else:
                    self._scan_for_credentials(value, path, violations, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._scan_for_credentials(item, path, violations, depth + 1)


# ─────────────────────────────────────────────────────────────────────
#  2. No auth code in tracked Python source files
# ─────────────────────────────────────────────────────────────────────

AUTH_CODE_PATTERNS = [
    "password_hash",
    "password_salt",
    "hash_password",
    "verify_password",
    "hashlib.scrypt",
    "hashlib.pbkdf2_hmac",
    "bcrypt.hashpw",
    "bcrypt.checkpw",
]

# Files that contain these patterns for legitimate reasons:
# - This test file (pattern strings appear in assertions)
# - Test files that assert the patterns are ABSENT (they reference the strings
#   in `assert "password_hash" not in ...` — testing for absence, not implementing auth)
# - Legacy test file that verified the removed password system
AUTH_CODE_ALLOWLIST = {
    "tests/test_prevention_stack.py",
    "tests/test_password_security.py",  # legacy test, may be deleted
    "tests/test_student_system.py",     # asserts password_hash/salt NOT in public records
    "tests/test_token_system.py",       # asserts password_hash/salt NOT in public records
}


class TestNoAuthCodeInSource:
    def test_no_password_hashing_in_source(self):
        """No production Python source file may contain password hashing code."""
        result = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        py_files = [
            REPO_ROOT / p.strip()
            for p in result.stdout.splitlines()
            if p.strip()
        ]

        violations: list[str] = []
        for path in py_files:
            rel = str(path.relative_to(REPO_ROOT))
            if rel in AUTH_CODE_ALLOWLIST:
                continue
            if not path.exists():
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in AUTH_CODE_PATTERNS:
                if pattern in source:
                    # Find the line number
                    for i, line in enumerate(source.splitlines(), 1):
                        if pattern in line and not line.strip().startswith("#"):
                            violations.append(f"{rel}:{i}: found '{pattern}'")
                            break
        assert not violations, (
            "Password/auth code found in tracked Python source:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ─────────────────────────────────────────────────────────────────────
#  3. subscriptions.json is gitignored
# ─────────────────────────────────────────────────────────────────────

class TestSubscriptionsFileIsGitignored:
    def test_subscriptions_json_is_gitignored(self):
        """subscriptions.json must be gitignored — never trackable."""
        result = subprocess.run(
            ["git", "check-ignore", "-v", "subscriptions.json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "subscriptions.json is NOT gitignored in this repo. "
            "Add 'subscriptions.json' to .gitignore immediately."
        )

    def test_subscribers_json_is_gitignored(self):
        """subscribers.json must also be gitignored."""
        result = subprocess.run(
            ["git", "check-ignore", "-v", "subscribers.json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "subscribers.json is NOT gitignored in this repo. "
            "Add 'subscribers.json' to .gitignore."
        )

    def test_env_file_is_gitignored(self):
        """.env must be gitignored."""
        result = subprocess.run(
            ["git", "check-ignore", "-v", ".env"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            ".env is NOT gitignored in this repo. Add '.env' to .gitignore."
        )


# ─────────────────────────────────────────────────────────────────────
#  4. gitleaks pre-commit hook is installed and executable
# ─────────────────────────────────────────────────────────────────────

class TestGitleaksHookInstalled:
    def _global_hooks_path(self) -> Path | None:
        result = subprocess.run(
            ["git", "config", "--global", "core.hooksPath"],
            capture_output=True,
            text=True,
        )
        raw = result.stdout.strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        return p if p.exists() else None

    def _local_hooks_path(self) -> Path:
        return REPO_ROOT / ".git" / "hooks"

    def test_pre_commit_hook_exists(self):
        """A pre-commit hook must exist (either global or local)."""
        global_path = self._global_hooks_path()
        if global_path:
            hook = global_path / "pre-commit"
            assert hook.exists(), (
                f"Global hooks path is set to {global_path} but pre-commit hook is missing. "
                "Install with: cp /path/to/pre-commit ~/.config/git/hooks/pre-commit"
            )
            return
        # Fall back to local
        local_hook = self._local_hooks_path() / "pre-commit"
        assert local_hook.exists(), (
            "No pre-commit hook found (checked global hooksPath and .git/hooks/). "
            "Install gitleaks pre-commit hook to prevent credential commits."
        )

    def test_pre_commit_hook_is_executable(self):
        """The pre-commit hook must be executable."""
        global_path = self._global_hooks_path()
        if global_path:
            hook = global_path / "pre-commit"
        else:
            hook = self._local_hooks_path() / "pre-commit"
        if not hook.exists():
            pytest.skip("pre-commit hook not found — covered by test_pre_commit_hook_exists")
        assert os.access(hook, os.X_OK), (
            f"pre-commit hook at {hook} is not executable. "
            "Run: chmod +x {hook}"
        )

    def test_pre_commit_hook_references_gitleaks(self):
        """The pre-commit hook must reference gitleaks."""
        global_path = self._global_hooks_path()
        if global_path:
            hook = global_path / "pre-commit"
        else:
            hook = self._local_hooks_path() / "pre-commit"
        if not hook.exists():
            pytest.skip("pre-commit hook not found — covered by test_pre_commit_hook_exists")
        content = hook.read_text(encoding="utf-8", errors="ignore")
        assert "gitleaks" in content.lower(), (
            f"pre-commit hook at {hook} does not reference gitleaks. "
            "The hook may not be scanning for secrets."
        )


# ─────────────────────────────────────────────────────────────────────
#  5. Global gitignore contains required patterns
# ─────────────────────────────────────────────────────────────────────

REQUIRED_GITIGNORE_PATTERNS = [
    "subscriptions.json",
    "subscribers.json",
    ".env",
]


class TestGlobalGitignorePatterns:
    def _global_gitignore_path(self) -> Path | None:
        result = subprocess.run(
            ["git", "config", "--global", "core.excludesfile"],
            capture_output=True,
            text=True,
        )
        raw = result.stdout.strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        return p if p.exists() else None

    def test_global_gitignore_exists(self):
        """A global gitignore (core.excludesfile) must be configured."""
        path = self._global_gitignore_path()
        assert path is not None, (
            "No global gitignore configured. "
            "Set one with: git config --global core.excludesfile ~/.config/git/ignore"
        )

    def test_global_gitignore_has_required_patterns(self):
        """Global gitignore must block subscriptions.json, subscribers.json, and .env."""
        path = self._global_gitignore_path()
        if path is None:
            pytest.skip("Global gitignore not configured — covered by test_global_gitignore_exists")
        content = path.read_text(encoding="utf-8")
        missing = [p for p in REQUIRED_GITIGNORE_PATTERNS if p not in content]
        assert not missing, (
            "Global gitignore is missing required patterns:\n"
            + "\n".join(f"  {p}" for p in missing)
            + f"\n\nAdd them to {path}"
        )
