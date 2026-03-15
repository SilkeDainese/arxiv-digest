"""Pure helpers for student-focused setup presets."""

from __future__ import annotations

from setup.data import (
    ASTRO_MINI_TRACKS,
    AU_ASTRONOMY_PEOPLE,
    AU_STUDENT_ALWAYS_TAG,
    AU_STUDENT_KEYWORD_ALIASES,
    AU_STUDENT_TELESCOPE_KEYWORDS,
    AU_STUDENT_TRACK_LABELS,
)


def _au_student_optional_track_ids() -> list[str]:
    """Return the selectable AU-student tracks, excluding the always-on baseline."""
    return [
        track_id
        for track_id in AU_STUDENT_TRACK_LABELS
        if track_id != "au_astronomy"
    ]


def _merge_mini_keywords(track_ids: list[str]) -> dict[str, int]:
    """Merge preset keyword weights, keeping the highest weight per term."""
    merged: dict[str, int] = {}
    for track_id in track_ids:
        for keyword, weight in ASTRO_MINI_TRACKS.get(track_id, {}).get("keywords", {}).items():
            merged[keyword] = max(merged.get(keyword, 0), weight)
    return dict(sorted(merged.items(), key=lambda item: (-item[1], item[0].lower())))


def _merge_keyword_weights(*keyword_maps: dict[str, int]) -> dict[str, int]:
    """Merge weighted keywords, keeping the highest weight per term."""
    merged: dict[str, int] = {}
    for keyword_map in keyword_maps:
        for keyword, weight in (keyword_map or {}).items():
            clean = str(keyword).strip()
            if not clean:
                continue
            merged[clean] = max(merged.get(clean, 0), int(weight))
    return dict(sorted(merged.items(), key=lambda item: (-item[1], item[0].lower())))


def build_mini_research_context(track_ids: list[str]) -> str:
    """Return a simple weekly student-facing research context from selected tracks."""
    labels = [ASTRO_MINI_TRACKS[t]["label"] for t in track_ids if t in ASTRO_MINI_TRACKS]
    if not labels:
        labels = [ASTRO_MINI_TRACKS["general_astronomy"]["label"]]
    if len(labels) == 1:
        focus = labels[0]
        return (
            f"I am a student following {focus.lower()}. "
            "Please prioritise the most important and readable new astronomy papers in this area each week. "
            "Favour major discoveries, strong review-style papers, landmark observations, and papers likely to matter for learning the field."
        )
    focus = ", ".join(labels[:-1]) + f", and {labels[-1]}"
    return (
        f"I am a student following astronomy topics including {focus.lower()}. "
        "Please prioritise the most important and readable new papers each week. "
        "Favour major discoveries, strong review-style papers, landmark observations, and papers likely to matter for learning the field."
    )


def build_mini_student_config(
    track_ids: list[str], smtp_server: str, smtp_port: int, github_repo: str
) -> tuple[dict, str]:
    """Build a minimal weekly astronomy-student config and matching cron expression."""
    selected = track_ids or ["general_astronomy"]
    categories: list[str] = []
    for track_id in selected:
        for category in ASTRO_MINI_TRACKS.get(track_id, {}).get("categories", []):
            if category not in categories:
                categories.append(category)

    keywords = _merge_mini_keywords(selected)
    labels = [ASTRO_MINI_TRACKS[t]["label"] for t in selected if t in ASTRO_MINI_TRACKS]
    display_name = labels[0] if len(labels) == 1 else "Astronomy"
    digest_name = f"{display_name} Weekly"

    config = {
        "digest_name": digest_name,
        "researcher_name": display_name,
        "research_context": build_mini_research_context(selected),
        "categories": categories,
        "keywords": keywords,
        "self_match": [],
        "research_authors": [],
        "colleagues": {"people": [], "institutions": []},
        "digest_mode": "highlights",
        "recipient_view_mode": "5_min_skim",
        "days_back": 8,
        "schedule": "weekly",
        "send_hour_utc": 7,
        "institution": "",
        "department": "",
        "tagline": "",
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "github_repo": github_repo or "",
        "max_papers": 5,
        "min_score": 5,
    }
    return config, "0 7 * * 1"


def build_au_student_research_context(track_ids: list[str], reading_mode: str) -> str:
    """Return the AU-student weekly research context used for AI scoring."""
    labels = [
        AU_STUDENT_TRACK_LABELS[track_id]
        for track_id in track_ids
        if track_id in AU_STUDENT_TRACK_LABELS and track_id != "au_astronomy"
    ]
    if not labels:
        labels = [
            label
            for track_id, label in AU_STUDENT_TRACK_LABELS.items()
            if track_id != "au_astronomy"
        ]
    focus = ", ".join(labels[:-1]) + f", and {labels[-1]}" if len(labels) > 1 else labels[0]
    if reading_mode == "biggest_only":
        return (
            f"I am an Aarhus University astronomy student following {focus.lower()}. "
            "Prioritise only the most important new papers each week: landmark observations, major theory advances, major surveys or data releases, and strong review-style papers that help build intuition quickly. "
            "Also surface papers connected to Aarhus astronomy, AU-run telescopes, or AU student space projects."
        )
    return (
        f"I am an Aarhus University astronomy student following {focus.lower()}. "
        "Prioritise readable and important papers each week: clear observational results, strong review-style papers, major surveys or data releases, and discoveries that are useful for learning the field. "
        "Also surface papers connected to Aarhus astronomy, AU-run telescopes, or AU student space projects."
    )


def build_au_student_config(
    student_name: str, student_email: str, track_ids: list[str], reading_mode: str
) -> dict:
    """Build a hidden AU-student digest config with AU astronomy defaults."""
    selected = [
        track_id
        for track_id in track_ids
        if track_id in AU_STUDENT_TRACK_LABELS and track_id != "au_astronomy"
    ] or _au_student_optional_track_ids()
    categories: list[str] = []
    for track_id in selected:
        for category in ASTRO_MINI_TRACKS.get(track_id, {}).get("categories", []):
            if category not in categories:
                categories.append(category)

    keywords = _merge_keyword_weights(
        _merge_mini_keywords(selected),
        AU_STUDENT_TELESCOPE_KEYWORDS,
    )

    return {
        "digest_name": "AU Astronomy Student Weekly",
        "researcher_name": student_name.strip() or "AU Astronomy Student",
        "recipient_email": student_email.strip(),
        "student_tracks": list(
            dict.fromkeys(
                [AU_STUDENT_ALWAYS_TAG]
                + [
                    AU_STUDENT_TRACK_LABELS[track_id]
                    for track_id in selected
                    if track_id in AU_STUDENT_TRACK_LABELS
                ]
            )
        ),
        "research_context": build_au_student_research_context(selected, reading_mode),
        "categories": categories,
        "keywords": keywords,
        "keyword_aliases": dict(AU_STUDENT_KEYWORD_ALIASES),
        "self_match": [],
        "research_authors": [person["name"] for person in AU_ASTRONOMY_PEOPLE],
        "colleagues": {"people": list(AU_ASTRONOMY_PEOPLE), "institutions": []},
        "digest_mode": "highlights",
        "recipient_view_mode": "5_min_skim",
        "days_back": 8,
        "schedule": "weekly",
        "send_hour_utc": 7,
        "institution": "Aarhus University",
        "department": "Department of Physics and Astronomy",
        "tagline": "Weekly astronomy reading for AU students",
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "github_repo": "",
        "max_papers": 4 if reading_mode == "biggest_only" else 6,
        "min_score": 6 if reading_mode == "biggest_only" else 4,
    }
