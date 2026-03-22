"""Shared helpers for central student subscriptions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from setup.data import AU_STUDENT_TRACK_LABELS

DEFAULT_MAX_PAPERS = 6
MIN_MAX_PAPERS = 1
MAX_MAX_PAPERS = 20
AVAILABLE_STUDENT_PACKAGES = [
    track_id
    for track_id in [
        "stars", "exoplanets", "galaxies", "cosmology",
        "high_energy", "instrumentation", "solar_helio", "methods_ml",
    ]
    if track_id in AU_STUDENT_TRACK_LABELS
]


def now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalise_email(email: str) -> str:
    """Return a canonical lower-cased email string."""
    return " ".join(str(email).split()).strip().lower()


def package_labels() -> dict[str, str]:
    """Return the supported student package label map."""
    return {key: AU_STUDENT_TRACK_LABELS[key] for key in AVAILABLE_STUDENT_PACKAGES}


def normalise_package_ids(package_ids: Any) -> list[str]:
    """Validate and de-duplicate selected package ids."""
    cleaned: list[str] = []
    for package_id in package_ids or []:
        key = str(package_id).strip()
        if key in AVAILABLE_STUDENT_PACKAGES and key not in cleaned:
            cleaned.append(key)
    if not cleaned:
        raise ValueError("Pick at least one student category.")
    return cleaned


def clamp_max_papers(value: Any) -> int:
    """Clamp max-papers settings into the supported student range."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_MAX_PAPERS
    return max(MIN_MAX_PAPERS, min(MAX_MAX_PAPERS, parsed))



def public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return the non-sensitive fields of a student record."""
    normalized = normalise_public_subscription(record)
    return {
        "email": normalized["email"],
        "package_ids": normalized["package_ids"],
        "max_papers_per_week": normalized["max_papers_per_week"],
        "active": normalized["active"],
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def normalise_public_subscription(record: dict[str, Any]) -> dict[str, Any]:
    """Return a validated public subscription record."""
    email = normalise_email(record.get("email", ""))
    if not email:
        raise ValueError("Subscription record is missing an email.")
    return {
        "email": email,
        "package_ids": normalise_package_ids(record.get("package_ids", [])),
        "max_papers_per_week": clamp_max_papers(record.get("max_papers_per_week")),
        "active": bool(record.get("active", True)),
    }


def build_student_record(
    *,
    email: str,
    package_ids: Any,
    max_papers_per_week: Any,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or update a student subscription record (passwordless)."""
    clean_email = normalise_email(email)
    if not clean_email:
        raise ValueError("Email is required.")
    packages = normalise_package_ids(package_ids)
    max_papers = clamp_max_papers(max_papers_per_week)
    timestamp = now_iso()
    created_at = (existing.get("created_at") or timestamp) if existing else timestamp

    return {
        "email": clean_email,
        "package_ids": packages,
        "max_papers_per_week": max_papers,
        "active": True,
        "created_at": created_at,
        "updated_at": timestamp,
    }
