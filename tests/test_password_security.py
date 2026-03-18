"""
tests/test_password_security.py — Password hashing security tests.

Verifies that:
  - New hashes use param-in-hash format (scheme$params$hex — 3 parts)
  - Upgraded parameters: scrypt N≥2^15, pbkdf2 ≥400k iterations
  - Old-format hashes (2-part: scrypt$hex) still verify correctly
  - relay/api/_registry.py is in sync with student_registry.py
"""

from __future__ import annotations

import hashlib
import os

import pytest

import student_registry as sr
import relay.api._registry as relay_reg

SCRYPT_AVAILABLE = hasattr(hashlib, "scrypt")


# ─────────────────────────────────────────────────────────────
#  New hash format: params always embedded (3 parts)
# ─────────────────────────────────────────────────────────────


class TestHashFormat:
    def test_new_hash_has_three_parts(self):
        """Any new hash must be scheme$params$hex — not the old 2-part scheme$hex."""
        _, hash_str = sr.hash_password("test-pass")
        parts = hash_str.split("$")
        assert len(parts) == 3, (
            f"Expected scheme$params$hex (3 parts), got {len(parts)}: {hash_str!r}\n"
            "Params must be encoded in the hash string for future-proof upgrades."
        )

    def test_scrypt_hash_encodes_n_param(self):
        """scrypt hashes must include n= in the params section."""
        if not SCRYPT_AVAILABLE:
            pytest.skip("scrypt not available in this runtime")
        _, hash_str = sr.hash_password("test-pass")
        assert hash_str.startswith("scrypt$")
        params_str = hash_str.split("$")[1]
        assert "n=" in params_str, f"scrypt params must include n=, got: {params_str!r}"

    def test_pbkdf2_hash_encodes_iter_param(self):
        """pbkdf2 hashes must include iter= in the params section."""
        if SCRYPT_AVAILABLE:
            pytest.skip("scrypt available; pbkdf2 is only used as fallback")
        _, hash_str = sr.hash_password("test-pass")
        assert hash_str.startswith("pbkdf2_sha256$")
        params_str = hash_str.split("$")[1]
        assert "iter=" in params_str, f"pbkdf2 params must include iter=, got: {params_str!r}"


# ─────────────────────────────────────────────────────────────
#  Upgraded parameters
# ─────────────────────────────────────────────────────────────


class TestUpgradedParams:
    def _parse_params(self, hash_str: str) -> dict[str, str]:
        """Extract the params dict from a 3-part hash string."""
        parts = hash_str.split("$")
        assert len(parts) == 3, f"Cannot parse params from {hash_str!r}"
        return dict(kv.split("=") for kv in parts[1].split(","))

    def test_scrypt_n_is_at_least_32768(self):
        """scrypt N must be ≥2^15 (32768). Floor is conservative — OWASP says 2^17."""
        if not SCRYPT_AVAILABLE:
            pytest.skip("scrypt not available in this runtime")
        _, hash_str = sr.hash_password("test-pass")
        params = self._parse_params(hash_str)
        n = int(params["n"])
        assert n >= 2**15, f"scrypt N={n} is below the minimum safe value 2^15 (32768)"

    def test_pbkdf2_iterations_at_least_400000(self):
        """pbkdf2 iterations must be ≥400,000 (OWASP recommends 600,000 for SHA-256)."""
        if SCRYPT_AVAILABLE:
            pytest.skip("pbkdf2 is only used as fallback")
        _, hash_str = sr.hash_password("test-pass")
        params = self._parse_params(hash_str)
        iters = int(params["iter"])
        assert iters >= 400_000, (
            f"pbkdf2 iter={iters} is below minimum. OWASP recommendation: 600,000"
        )


# ─────────────────────────────────────────────────────────────
#  Verify — new format round-trips correctly
# ─────────────────────────────────────────────────────────────


class TestVerifyNewFormat:
    def test_hash_and_verify_roundtrip(self):
        """A newly hashed password must verify correctly and reject wrong passwords."""
        salt, hash_str = sr.hash_password("my-password")
        assert sr.verify_password("my-password", salt, hash_str)
        assert not sr.verify_password("wrong-password", salt, hash_str)

    def test_empty_inputs_return_false(self):
        """verify_password must return False for any empty argument."""
        salt, hash_str = sr.hash_password("my-password")
        assert not sr.verify_password("", salt, hash_str)
        assert not sr.verify_password("my-password", "", hash_str)
        assert not sr.verify_password("my-password", salt, "")


# ─────────────────────────────────────────────────────────────
#  Backward compat: old 2-part hashes still verify
# ─────────────────────────────────────────────────────────────


class TestBackwardCompat:
    def test_old_scrypt_hash_still_verifies(self):
        """Old-format scrypt hashes (scheme$hex, N=2^14) must still verify after upgrade."""
        if not SCRYPT_AVAILABLE:
            pytest.skip("scrypt not available in this runtime")
        salt_bytes = os.urandom(16)
        digest = hashlib.scrypt(b"old-password", salt=salt_bytes, n=2**14, r=8, p=1)
        old_hash = f"scrypt${digest.hex()}"
        assert sr.verify_password("old-password", salt_bytes.hex(), old_hash), (
            "Old-format scrypt hash (pre-upgrade) must still verify"
        )
        assert not sr.verify_password("wrong", salt_bytes.hex(), old_hash)

    def test_old_pbkdf2_hash_still_verifies(self):
        """Old-format pbkdf2 hashes (scheme$hex, 200k) must still verify after upgrade."""
        salt_bytes = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", b"old-password", salt_bytes, 200_000)
        old_hash = f"pbkdf2_sha256${digest.hex()}"
        assert sr.verify_password("old-password", salt_bytes.hex(), old_hash), (
            "Old-format pbkdf2 hash (pre-upgrade) must still verify"
        )
        assert not sr.verify_password("wrong", salt_bytes.hex(), old_hash)


# ─────────────────────────────────────────────────────────────
#  Relay copy must be in sync with root registry
# ─────────────────────────────────────────────────────────────


class TestRelayCopyInSync:
    def test_relay_hash_format_matches_root(self):
        """relay/_registry.py must produce same 3-part format as student_registry.py."""
        _, hash_sr = sr.hash_password("test")
        _, hash_rr = relay_reg.hash_password("test")
        sr_parts = hash_sr.count("$")
        rr_parts = hash_rr.count("$")
        assert sr_parts == rr_parts == 2, (
            f"Both modules must produce 3-part hashes (2 '$' separators). "
            f"Root: {sr_parts}, Relay: {rr_parts}"
        )

    def test_relay_verify_accepts_root_hash(self):
        """A hash from the root module must verify correctly in the relay module."""
        salt, hash_str = sr.hash_password("cross-check")
        assert relay_reg.verify_password("cross-check", salt, hash_str)

    def test_root_verify_accepts_relay_hash(self):
        """A hash from the relay module must verify correctly in the root module."""
        salt, hash_str = relay_reg.hash_password("cross-check")
        assert sr.verify_password("cross-check", salt, hash_str)
