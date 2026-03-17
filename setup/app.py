"""
arXiv Digest — Setup Wizard
A Streamlit web app that helps researchers configure their personal arXiv digest.
Generates a config.yaml (+ workflow snippet) ready to use with the arxiv-digest template.

Created by Silke S. Dainese · dainese@phys.au.dk · silkedainese.github.io
"""

import json
import hmac
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import yaml
import streamlit as st

try:
    import anthropic as _anthropic_lib

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

try:
    from google import genai as _genai_lib
    from google.genai import types as _genai_types

    _GEMINI_AVAILABLE = True
except ImportError:
    _GEMINI_AVAILABLE = False

# Allow imports from the project root (one level up from setup/)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brand import ASH_WHITE, CARD_BORDER, GOLD, GOLD_WASH, PINE, WARM_GREY
from data import (
    ASTRO_MINI_TRACKS,
    AU_STUDENT_TRACK_LABELS,
    AU_ASTRONOMY_PEOPLE,
    AU_STUDENT_TELESCOPE_KEYWORDS,
    AU_STUDENT_KEYWORD_ALIASES,
    ARXIV_CATEGORIES,
    ARXIV_GROUPS,
    ARXIV_GROUP_HINTS,
    CATEGORY_HINTS,
)
from setup.student_presets import build_mini_student_config
from student_registry import AVAILABLE_STUDENT_PACKAGES, DEFAULT_MAX_PAPERS
from style import inject_css
from validators import (
    validate_au_email,
    validate_package_selection,
    validate_password,
)
try:
    from pure_scraper import (
        fetch_orcid_person,
        fetch_orcid_works,
        find_au_colleagues,
        scrape_pure_profile,
        search_pure_profiles,
    )
    _PURE_AVAILABLE = True
except Exception:
    _PURE_AVAILABLE = False

# ─────────────────────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="arXiv Digest Setup",
    page_icon="🔭",
    layout="centered",
)

# ── Custom CSS for brand styling ──
inject_css()


_ORCID_ID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
DEFAULT_STUDENT_MANAGE_URL = os.environ.get(
    "STUDENT_MANAGE_URL",
    "https://arxiv-digest-relay.vercel.app/api/students",
).strip()
AU_STUDENT_PACKAGE_DESCRIPTIONS = {
    "stars": "Stellar evolution, atmospheres, activity, binaries, and variable stars.",
    "exoplanets": "Detection, characterisation, atmospheres, habitability, and planetary systems.",
    "galaxies": "Galaxy formation, evolution, morphology, AGN, groups, and clusters.",
    "cosmology": "Dark energy, large-scale structure, the early universe, and inflation.",
}


def _weight_label(w: int) -> str:
    """Return a human-readable label for a keyword weight (1–10)."""
    if w <= 2:
        return "loosely follow"
    if w <= 5:
        return "interested"
    if w <= 8:
        return "main field"
    return "everything"



def _merge_mini_keywords(track_ids: list[str]) -> dict[str, int]:
    """Merge preset keyword weights, keeping the highest weight per term."""
    merged: dict[str, int] = {}
    for track_id in track_ids:
        for keyword, weight in ASTRO_MINI_TRACKS.get(track_id, {}).get(
            "keywords", {}
        ).items():
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


def _dedupe_titles(*title_lists: list[str]) -> list[str]:
    """Deduplicate titles while preserving the first-seen order."""
    seen: set[str] = set()
    merged: list[str] = []
    for title_list in title_lists:
        for title in title_list or []:
            clean = title.strip()
            if clean and clean not in seen:
                seen.add(clean)
                merged.append(clean)
    return merged


def _merge_works_meta(*meta_lists: list[dict]) -> list[dict]:
    """Merge ORCID work metadata and keep the most recent year per title."""
    ordered_titles: list[str] = []
    by_title: dict[str, dict] = {}
    for meta_list in meta_lists:
        for entry in meta_list or []:
            title = str(entry.get("title", "")).strip()
            if not title:
                continue
            if title not in by_title:
                ordered_titles.append(title)
                by_title[title] = {"title": title, "year": entry.get("year")}
                continue
            existing_year = by_title[title].get("year")
            incoming_year = entry.get("year")
            if existing_year is None or (
                incoming_year is not None and incoming_year > existing_year
            ):
                by_title[title]["year"] = incoming_year
    return [by_title[title] for title in ordered_titles]


def _merge_coauthor_maps(*coauthor_maps: dict[str, str]) -> dict[str, str]:
    """Merge co-author maps, keeping the latest non-empty display name per ORCID."""
    merged: dict[str, str] = {}
    for coauthor_map in coauthor_maps:
        for orcid_id, name in (coauthor_map or {}).items():
            clean_name = str(name).strip()
            if not orcid_id or not clean_name:
                continue
            merged[orcid_id] = clean_name
    return merged


def _merge_coauthor_counts(*count_maps: dict[str, int]) -> dict[str, int]:
    """Merge co-author frequency maps by summing counts per display name."""
    counts: Counter[str] = Counter()
    for count_map in count_maps:
        counts.update({name: int(count) for name, count in (count_map or {}).items()})
    return dict(counts)


def _name_match_patterns(full_name: str) -> list[str]:
    """Return arXiv-friendly match patterns for a person name."""
    clean = " ".join(full_name.split()).strip()
    if not clean:
        return []
    patterns = [clean]
    parts = clean.split()
    if len(parts) >= 2:
        patterns.append(f"{parts[-1]}, {parts[0][0]}")
    return list(dict.fromkeys(patterns))


def _group_member_names(extra_name: str = "") -> set[str]:
    """Return the lower-cased imported group member names."""
    names = {
        str(member.get("name", "")).strip().lower()
        for member in st.session_state.get("group_orcid_members", [])
        if str(member.get("name", "")).strip()
    }
    if extra_name.strip():
        names.add(extra_name.strip().lower())
    return names


def _set_selected_papers(titles: list[str]) -> None:
    """Keep the paper multiselect widget and backing state in sync."""
    selection = _dedupe_titles(titles)
    st.session_state.selected_papers = selection
    st.session_state["paper_selector_widget"] = selection


def _render_repo_setup_steps(cron_expr: str, *, recipient_in_config: bool = False) -> None:
    """Show the GitHub-side steps after generating a downloadable config."""
    st.divider()
    st.markdown("## Next Steps")
    st.markdown(
        f"""
<div class="brand-card">
<p class="brand-label" style="margin-bottom: 16px;">After setup</p>

<div style="display: flex; gap: 10px; align-items: flex-start; margin-bottom: 14px;">
<span class="step-number">1</span>
<div>
<p style="margin: 0;"><strong>Fork the repo</strong></p>
<p style="margin: 2px 0 0; color: {WARM_GREY};">
<a href="https://github.com/SilkeDainese/arxiv-digest" target="_blank" style="color: {PINE};">
SilkeDainese/arxiv-digest
</a>
→ Fork
</p>
</div>
</div>

<div style="display: flex; gap: 10px; align-items: flex-start; margin-bottom: 14px;">
<span class="step-number">2</span>
<div>
<p style="margin: 0;"><strong>Upload config.yaml</strong></p>
<p style="margin: 2px 0 0; color: {WARM_GREY};">
Add file → Upload → drop <code>config.yaml</code> → Commit.
</p>
</div>
</div>

<div style="display: flex; gap: 10px; align-items: flex-start; margin-bottom: 4px;">
<span class="step-number">3</span>
<div style="flex: 1;">
<p style="margin: 0;"><strong>Add secrets</strong></p>
<p style="margin: 2px 0 0; color: {WARM_GREY};">Settings → Secrets → Actions</p>
</div>
</div>

<div style="margin: 4px 0 14px 38px; border: 1px solid {CARD_BORDER}; border-radius: 8px; overflow: hidden;">
<table style="width: 100%; border-collapse: collapse; font-size: 12px;">
<thead>
<tr style="border-bottom: 1px solid {CARD_BORDER}; background: {ASH_WHITE};">
<th class="brand-label" style="text-align: left; padding: 8px 10px;">Secret</th>
<th class="brand-label" style="text-align: left; padding: 8px 10px;">Value</th>
<th class="brand-label" style="text-align: center; padding: 8px 10px; width: 86px;">Required</th>
</tr>
</thead>
<tbody>
<tr style="border-bottom: 1px solid {CARD_BORDER};">
<td style="padding: 8px 10px;"><code>RECIPIENT_EMAIL</code></td>
<td style="padding: 8px 10px; color: {WARM_GREY};">Your email address</td>
<td style="padding: 8px 10px; text-align: center; color: {PINE}; font-weight: 600;">Yes</td>
</tr>
<tr style="border-bottom: 1px solid {CARD_BORDER}; background: {GOLD_WASH};">
<td colspan="3" style="padding: 6px 10px; font-weight: 600;">Email delivery — pick one:</td>
</tr>
<tr style="border-bottom: 1px solid {CARD_BORDER};">
<td style="padding: 8px 10px;"><code>RELAY_TOKEN</code></td>
<td style="padding: 8px 10px; color: {WARM_GREY};">From access code — no email setup needed</td>
<td style="padding: 8px 10px; text-align: center; color: {WARM_GREY};">Option A</td>
</tr>
<tr style="border-bottom: 1px solid {CARD_BORDER};">
<td style="padding: 8px 10px;"><code>SMTP_USER</code> + <code>SMTP_PASSWORD</code></td>
<td style="padding: 8px 10px; color: {WARM_GREY};">Gmail/Outlook + App Password</td>
<td style="padding: 8px 10px; text-align: center; color: {WARM_GREY};">Option B</td>
</tr>
<tr style="border-bottom: 1px solid {CARD_BORDER}; background: {GOLD_WASH};">
<td colspan="3" style="padding: 6px 10px; font-weight: 600;">AI scoring — optional:</td>
</tr>
<tr style="border-bottom: 1px solid {CARD_BORDER};">
<td style="padding: 8px 10px;"><code>GEMINI_API_KEY</code></td>
<td style="padding: 8px 10px; color: {WARM_GREY};">
<a href="https://aistudio.google.com" target="_blank" style="color: {PINE};">Free key</a> → aistudio.google.com
</td>
<td style="padding: 8px 10px; text-align: center; color: {WARM_GREY};">Free</td>
</tr>
<tr>
<td style="padding: 8px 10px;"><code>ANTHROPIC_API_KEY</code></td>
<td style="padding: 8px 10px; color: {WARM_GREY};">
<a href="https://console.anthropic.com" target="_blank" style="color: {PINE};">console.anthropic.com</a>
</td>
<td style="padding: 8px 10px; text-align: center; color: {WARM_GREY};">Paid</td>
</tr>
</tbody>
</table>
</div>

<div style="display: flex; gap: 10px; align-items: flex-start;">
<span class="step-number">4</span>
<div>
<p style="margin: 0;"><strong>Allow Actions &amp; run workflow</strong></p>
<p style="margin: 2px 0 0; color: {WARM_GREY};">Actions tab → Enable workflows → Run workflow.</p>
</div>
</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_mini_setup() -> None:
    """Render a separate mini setup flow for students without ORCID."""
    st.markdown("## Mini setup — no ORCID")
    st.markdown(
        "For students who do not have an ORCID yet. Pick a few astronomy interests and get a simple weekly digest of the most important papers in those areas."
    )

    selected_tracks = st.multiselect(
        "Astronomy interests",
        options=list(ASTRO_MINI_TRACKS.keys()),
        default=["general_astronomy"],
        format_func=lambda key: ASTRO_MINI_TRACKS[key]["label"],
        help="Choose one or more areas you want to follow.",
    )
    if not selected_tracks:
        st.info("Pick at least one interest to generate a mini config.")
        return

    if "general_astronomy" in selected_tracks and len(selected_tracks) > 1:
        st.caption(
            "General astronomy overlaps the more specific tracks below, so the digest will stay broad."
        )

    st.markdown("**What this mini setup will do**")
    st.caption(
        "Weekly on Monday, 5-minute skim format, up to 5 papers, and no profile import or name matching."
    )

    with st.expander("Selected tracks", expanded=True):
        for track_id in selected_tracks:
            track = ASTRO_MINI_TRACKS[track_id]
            st.markdown(f"**{track['label']}**")
            st.caption(track["blurb"])

    # Keywords as editable chips (seeded from track presets)
    track_keywords = _merge_mini_keywords(selected_tracks)
    if "mini_keywords" not in st.session_state:
        st.session_state.mini_keywords = dict(track_keywords)

    # Re-seed when tracks change
    _track_key = tuple(sorted(selected_tracks))
    if st.session_state.get("_mini_last_tracks") != _track_key:
        st.session_state.mini_keywords = dict(track_keywords)
        st.session_state["_mini_last_tracks"] = _track_key

    all_kw_options = list(st.session_state.mini_keywords.keys())
    selected_kws = st.multiselect(
        "Keywords",
        options=all_kw_options,
        default=all_kw_options,
        key="mini_kw_chips",
        help="Topics your digest looks for. Each gets a default weight of 7.",
    )

    # Add custom keyword
    kw_col, btn_col = st.columns([4, 1])
    with kw_col:
        new_kw = st.text_input(
            "Add a keyword",
            key="mini_new_kw",
            label_visibility="collapsed",
            placeholder="Add a keyword...",
        )
    with btn_col:
        if st.button("Add", key="mini_add_kw", use_container_width=True) and new_kw.strip():
            st.session_state.mini_keywords[new_kw.strip()] = 7
            st.rerun()

    # Sync chips → keywords dict
    synced_keywords = {}
    for kw in selected_kws:
        synced_keywords[kw] = st.session_state.mini_keywords.get(kw, 7)
    st.session_state.mini_keywords = synced_keywords

    with st.expander("Advanced keyword settings"):
        st.caption(
            "Fine-tune weight (0–10). **0–2** loosely follow · **3–5** interested · **6–8** main interest · **9–10** everything"
        )
        for kw in list(st.session_state.mini_keywords.keys()):
            weight = st.slider(
                kw,
                min_value=0,
                max_value=10,
                value=st.session_state.mini_keywords[kw],
                key=f"mini_kw_w_{kw}",
            )
            st.session_state.mini_keywords[kw] = weight

    smtp_options = {
        "Gmail": ("smtp.gmail.com", 587),
        "Outlook / Office 365": ("smtp.office365.com", 587),
    }
    smtp_choice = st.radio(
        "SMTP provider",
        options=list(smtp_options.keys()),
        horizontal=True,
        label_visibility="collapsed",
    )
    smtp_server, smtp_port = smtp_options[smtp_choice]

    github_repo = st.text_input(
        "GitHub repo (optional)",
        placeholder="username/arxiv-digest",
        help="Enables self-service links in emails",
        key="mini_github_repo",
    )

    config, cron_expr = build_mini_student_config(
        selected_tracks, smtp_server, smtp_port, github_repo
    )
    # Override keywords with user-edited version
    config["keywords"] = dict(st.session_state.mini_keywords)
    config_yaml = yaml.dump(
        config, default_flow_style=False, sort_keys=False, allow_unicode=True
    )

    st.markdown("### Your config.yaml is ready")
    tab1, tab2 = st.tabs(["config.yaml", "Workflow cron"])

    with tab1:
        st.code(config_yaml, language="yaml")

    with tab2:
        st.markdown(
            "Use this cron line in `.github/workflows/digest.yml` for the student mini setup:"
        )
        st.code(
            "    - cron: '0 7 * * 1'  # Once a week (Monday) at 07:00 UTC",
            language="yaml",
        )

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📥 Download config.yaml",
            data=config_yaml,
            file_name="config.yaml",
            mime="text/yaml",
            type="primary",
            use_container_width=True,
        )
    with col2:
        if st.button("📋 Show YAML", use_container_width=True, key="mini_copy"):
            st.code(config_yaml, language="yaml")
            st.info("Select all text above and copy with Ctrl+C (Cmd+C on Mac)")

    _render_repo_setup_steps(cron_expr)


def _post_au_student_subscription(payload: dict) -> dict:
    """Create or update an AU student subscription through the relay endpoint."""
    request = urllib.request.Request(
        DEFAULT_STUDENT_MANAGE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            error_payload = json.loads(body)
        except json.JSONDecodeError:
            error_payload = {}
        message = str(error_payload.get("error") or body or exc.reason)
        raise RuntimeError(message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach the AU student relay at {DEFAULT_STUDENT_MANAGE_URL}: {exc.reason}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("The AU student relay returned invalid JSON.") from exc


def render_au_student_setup() -> None:
    """Render the hidden AU-student setup flow."""
    if "au_student_step" not in st.session_state:
        st.session_state.au_student_step = 1
    if "au_student_api_response" not in st.session_state:
        st.session_state.au_student_api_response = None
    if "au_student_response_email" not in st.session_state:
        st.session_state.au_student_response_email = ""

    st.markdown("## AU astronomy student setup")
    st.markdown(
        "AI scoring and email relay provided courtesy. You just need an AU email and to set a password."
    )
    st.caption(f"relay: {DEFAULT_STUDENT_MANAGE_URL}")

    with st.expander(
        "**1. Your AU Account**",
        expanded=(st.session_state.au_student_step == 1),
    ):
        st.markdown(
            "Log in or create your student subscription. Only `@uni.au.dk` emails are accepted."
        )
        email_cols = st.columns([2, 1])
        with email_cols[0]:
            st.text_input(
                "AU email",
                placeholder="au612345",
                key="au_student_email_local",
            )
        with email_cols[1]:
            st.markdown("")
            st.markdown("`@uni.au.dk`")

        email_ok, email_message = validate_au_email(
            st.session_state.get("au_student_email_local", "")
        )
        if email_ok:
            st.caption(email_message)
        else:
            st.caption("Format: au + 6 digits (for example `au612345@uni.au.dk`).")

        password_cols = st.columns(2)
        with password_cols[0]:
            st.text_input(
                "Password",
                type="password",
                placeholder="choose a password",
                key="au_student_password",
            )
        with password_cols[1]:
            st.text_input(
                "Confirm",
                type="password",
                placeholder="repeat password",
                key="au_student_password_confirm",
            )

        if st.button(
            "Continue ->",
            key="au_student_step1_continue",
            type="primary",
            use_container_width=True,
        ):
            email_ok, email_message = validate_au_email(
                st.session_state.get("au_student_email_local", "")
            )
            if not email_ok:
                st.error(email_message or "Enter your AU email as au + 6 digits.")
            else:
                password_ok, password_message = validate_password(
                    st.session_state.get("au_student_password", ""),
                    st.session_state.get("au_student_password_confirm", ""),
                )
                if not password_ok:
                    st.error(password_message or "Enter and confirm a password.")
                else:
                    st.session_state.au_student_email_full = email_message
                    st.session_state.au_student_step = 2
                    st.session_state.au_student_api_response = None
                    st.session_state.au_student_response_email = ""
                    st.rerun()

    with st.expander(
        "**2. Your Interests**",
        expanded=(st.session_state.au_student_step == 2),
    ):
        if st.session_state.au_student_step < 2:
            st.caption("Complete Step 1 first.")
        else:
            st.markdown(
                "Pick the topic packages you want in your weekly digest. Select at least one."
            )
            selected_packages: list[str] = []
            package_cols = st.columns(2)
            for idx, package_id in enumerate(AVAILABLE_STUDENT_PACKAGES):
                with package_cols[idx % 2]:
                    if st.checkbox(
                        AU_STUDENT_TRACK_LABELS[package_id],
                        key=f"au_student_package_{package_id}",
                    ):
                        selected_packages.append(package_id)
                    st.caption(AU_STUDENT_PACKAGE_DESCRIPTIONS.get(package_id, ""))

            if st.button(
                "Continue ->",
                key="au_student_step2_continue",
                type="primary",
                use_container_width=True,
            ):
                packages_ok, _ = validate_package_selection(selected_packages)
                if not packages_ok:
                    st.error("Select at least one topic")
                else:
                    st.session_state.au_student_selected_packages = selected_packages
                    st.session_state.au_student_step = 3
                    st.session_state.au_student_api_response = None
                    st.session_state.au_student_response_email = ""
                    st.rerun()

    with st.expander(
        "**3. Settings & Subscribe**",
        expanded=(st.session_state.au_student_step == 3),
    ):
        if st.session_state.au_student_step < 3:
            st.caption("Complete Steps 1 and 2 first.")
        else:
            st.markdown("Student digests are sent weekly. Choose how many papers to include.")
            max_papers_per_week = st.radio(
                "How many papers?",
                options=[DEFAULT_MAX_PAPERS, 15],
                format_func=lambda value: (
                    "Highlights (6)"
                    if value == DEFAULT_MAX_PAPERS
                    else "In-depth (15)"
                ),
                horizontal=True,
                key="au_student_max_papers_per_week",
            )

            selected_packages = st.session_state.get("au_student_selected_packages", [])
            full_email = st.session_state.get("au_student_email_full", "")
            if full_email:
                st.caption(
                    f"{full_email} · {len(selected_packages)} topic(s) · Weekly · {max_papers_per_week} papers"
                )

            if st.button(
                "Subscribe",
                key="au_student_subscribe",
                type="primary",
                use_container_width=True,
            ):
                payload = {
                    "action": "upsert",
                    "email": full_email,
                    "password": st.session_state.get("au_student_password", ""),
                    "new_password": "",
                    "package_ids": selected_packages,
                    "max_papers_per_week": int(max_papers_per_week),
                }
                try:
                    response = _post_au_student_subscription(payload)
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    subscription = response.get("subscription", {})
                    st.session_state.au_student_api_response = {
                        "ok": bool(response.get("ok")),
                        "subscription": {
                            "package_ids": list(
                                subscription.get("package_ids", selected_packages)
                            ),
                            "max_papers_per_week": int(
                                subscription.get(
                                    "max_papers_per_week", max_papers_per_week
                                )
                            ),
                        },
                        "confirmation_email_sent": bool(
                            response.get("confirmation_email_sent", False)
                        ),
                    }
                    st.session_state.au_student_response_email = full_email
                    st.rerun()

            response_payload = st.session_state.get("au_student_api_response")
            response_email = st.session_state.get("au_student_response_email", "")
            if response_payload and response_email:
                local_part = response_email.split("@", 1)[0]
                st.success(f"Confirmation email sent to {local_part}@uni.au.dk")
                with st.expander("View API response"):
                    st.json(response_payload)



def suggest_categories(text: str) -> list[str]:
    """Return up to 6 relevant arXiv category codes for the given research description.

    Uses AI when available for field-agnostic suggestions; falls back to keyword
    matching against CATEGORY_HINTS.
    """
    if _ai_available():
        cat_list = "\n".join(
            f"  {code}: {name}" for code, name in ARXIV_CATEGORIES.items()
        )
        prompt = (
            f'A researcher describes their work as:\n"{text}"\n\n'
            f"Here is the full list of arXiv categories:\n{cat_list}\n\n"
            "Return ONLY a JSON array of the 4–6 most relevant category codes "
            '(e.g. ["cond-mat.supr-con", "cond-mat.mes-hall"]). '
            "Pick the best-matching sub-categories — never return a bare top-level code "
            "like 'cond-mat' or 'astro-ph' unless it appears exactly in the list above. "
            "No explanation, no other text."
        )
        raw = _call_ai(prompt)
        if raw:
            try:
                raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
                raw = re.sub(r"\n?```$", "", raw)
                cats = json.loads(raw)
                # Keep only codes that actually exist in our catalogue
                valid = [c for c in cats if c in ARXIV_CATEGORIES]
                if valid:
                    return valid[:6]
            except Exception:
                pass  # fall through to regex fallback

    # Regex fallback — keyword overlap
    text_lower = text.lower()
    scores = {}
    for cat, hints in CATEGORY_HINTS.items():
        if cat not in ARXIV_CATEGORIES:
            continue
        score = sum(1 for h in hints if h.lower() in text_lower)
        if score >= 2:
            scores[cat] = score
    return sorted(scores, key=scores.get, reverse=True)[:6]


def _call_ai(prompt: str, max_tokens: int = 512) -> str | None:
    """Call Gemini (preferred, free tier) or Claude. Returns text or None on failure."""
    # Try Gemini first — free tier available via Google AI Studio
    gemini_key = _get_gemini_key()
    if gemini_key and _GEMINI_AVAILABLE:
        try:
            _client = _genai_lib.Client(api_key=gemini_key)
            response = _client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            return response.text.strip()
        except Exception:
            pass

    # Fall back to Anthropic
    anthropic_key = _get_anthropic_key()
    if anthropic_key and _ANTHROPIC_AVAILABLE:
        try:
            client = _anthropic_lib.Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception:
            pass

    return None


@st.cache_data(show_spinner=False)
def _test_ai_key(gemini_key: str, anthropic_key: str) -> tuple[bool, str, str]:
    """
    Validate that at least one AI key actually works.

    Cached by key values so it only runs once per unique key combination.

    Returns (ok, provider_name, error_message).
    """
    if gemini_key and _GEMINI_AVAILABLE:
        try:
            _client = _genai_lib.Client(api_key=gemini_key)
            _client.models.generate_content(
                model="gemini-2.0-flash",
                contents="Hi",
                config=_genai_types.GenerateContentConfig(max_output_tokens=1),
            )
            return True, "Gemini", ""
        except Exception as e:
            gemini_err = str(e)
    else:
        gemini_err = ""

    if anthropic_key and _ANTHROPIC_AVAILABLE:
        try:
            client = _anthropic_lib.Anthropic(api_key=anthropic_key)
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "Hi"}],
            )
            return True, "Anthropic", ""
        except Exception as e:
            anthropic_err = str(e)
    else:
        anthropic_err = ""

    errors = []
    if gemini_err:
        errors.append(f"Gemini: {gemini_err}")
    if anthropic_err:
        errors.append(f"Anthropic: {anthropic_err}")
    return False, "", "  |  ".join(errors) if errors else "No valid key entered."


def draft_research_description(keywords: dict[str, int]) -> str:
    """Generate a first-person research description from keywords using AI."""
    top_keywords = [k for k, _ in sorted(keywords.items(), key=lambda x: -x[1])[:10]]
    prompt = (
        f"A researcher has these keywords extracted from their publications:\n"
        f"{', '.join(top_keywords)}\n\n"
        "Write a 3-4 sentence research description in first person (starting with 'I') "
        "that this researcher could use to describe their work to a colleague. "
        "Be specific and technical. Return only the description, no other text."
    )
    result = _call_ai(prompt, max_tokens=200)
    return (
        result if result else f"My research focuses on {', '.join(top_keywords[:5])}."
    )


def _summarise_research(titles: list[str]) -> str:
    """Generate a first-person research summary from publication titles using AI."""
    sample = titles[:30]  # Cap to avoid token limits
    titles_block = "\n".join(f"- {t}" for t in sample)
    prompt = (
        "Here are publication titles from a researcher's ORCID profile:\n"
        f"{titles_block}\n\n"
        "Write a 3-4 sentence research description in first person (starting with 'I') "
        "that captures what this researcher works on. Be specific about methods, objects, "
        "or phenomena — avoid generic filler. Return only the description, no other text."
    )
    result = _call_ai(prompt, max_tokens=200)
    return result or ""


def _get_gemini_key() -> str | None:
    """Return Gemini API key: user-provided → invite-unlocked shared key → None."""
    user_key = st.session_state.get("user_gemini_key", "").strip()
    if user_key:
        return user_key

    invite_bundle = st.session_state.get("_invite_bundle", {})
    invite_key = str(invite_bundle.get("gemini_api_key", "")).strip()
    if invite_key:
        return invite_key
    return None


def _get_anthropic_key() -> str | None:
    """Return Anthropic API key: user-provided → invite-unlocked shared key → None."""
    user_key = st.session_state.get("user_anthropic_key", "").strip()
    if user_key:
        return user_key

    invite_bundle = st.session_state.get("_invite_bundle", {})
    invite_key = str(invite_bundle.get("anthropic_api_key", "")).strip()
    if invite_key:
        return invite_key
    return None


def _ai_available() -> bool:
    """True if any AI key is configured."""
    return bool(
        (_get_gemini_key() and _GEMINI_AVAILABLE)
        or (_get_anthropic_key() and _ANTHROPIC_AVAILABLE)
    )


def _keyword_regex_fallback(text: str) -> dict[str, int]:
    """Extract keywords from research description using pattern matching (no API needed)."""
    words = text.split()
    candidates: dict[str, int] = {}
    stopwords = {
        "i",
        "my",
        "me",
        "we",
        "our",
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "was",
        "are",
        "were",
        "been",
        "be",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "that",
        "which",
        "who",
        "this",
        "these",
        "it",
        "its",
        "their",
        "also",
        "using",
        "such",
        "both",
        "between",
        "about",
        "into",
        "through",
        "particularly",
        "specifically",
        "especially",
        "including",
        "focus",
        "work",
        "study",
        "research",
        "currently",
        "mainly",
        "primarily",
    }
    clean_words = [re.sub(r"[.,;:!?()\"']", "", w) for w in words if w]

    for w in clean_words:
        if not w or len(w) < 3:
            continue
        if w.isupper() and len(w) >= 2 and w.isalpha():
            candidates[w] = 8
        elif w[0].isupper() and not w.isupper() and len(w) > 3:
            candidates[w.lower()] = 5

    for i in range(len(clean_words) - 1):
        w1, w2 = clean_words[i].lower(), clean_words[i + 1].lower()
        if w1 not in stopwords and w2 not in stopwords and len(w1) > 2 and len(w2) > 2:
            bigram = f"{w1} {w2}"
            if bigram not in candidates:
                candidates[bigram] = 7

    for i in range(len(clean_words) - 2):
        w1, w2, w3 = (
            clean_words[i].lower(),
            clean_words[i + 1].lower(),
            clean_words[i + 2].lower(),
        )
        if all(w not in stopwords and len(w) > 2 for w in (w1, w2, w3)):
            trigram = f"{w1} {w2} {w3}"
            if len(trigram) > 10:
                candidates[trigram] = 9

    generic = {"et al", "ground based", "non linear"}
    return {
        k: v
        for k, v in sorted(candidates.items(), key=lambda x: -x[1])[:25]
        if k.lower() not in generic
    }


def suggest_keywords_from_context(
    text: str, orcid_keywords: dict | None = None
) -> dict[str, int]:
    """Score research keywords by relevance using Claude if available, regex otherwise.

    When orcid_keywords is provided, Claude re-scores those publication-derived keywords
    against the research description so that frequency in titles doesn't dominate.
    """
    api_key = _get_anthropic_key()

    if not _ai_available():
        return _keyword_regex_fallback(text)

    # Build candidate list: ORCID keywords + regex-derived keywords from description
    regex_kws = _keyword_regex_fallback(text)
    all_candidates = dict(regex_kws)
    if orcid_keywords:
        all_candidates.update(orcid_keywords)

    candidate_list = "\n".join(f"- {kw}" for kw in all_candidates)

    prompt = (
        f'A researcher describes their work as:\n"{text}"\n\n'
        f"These are candidate keywords (some from publication titles, some from the description):\n"
        f"{candidate_list}\n\n"
        "Score each keyword's relevance to this researcher's specific field on a scale of 1–10. "
        "Prefer specific technical terms over generic words. Generic words that happen to appear "
        "in paper titles (like 'water', 'worlds', 'population') should score low unless they are "
        "genuinely central to this specific research. Return at most 25 keywords. "
        "Return ONLY a JSON object mapping each keyword to its integer score. No other text."
    )

    raw = _call_ai(prompt)
    if not raw:
        return _keyword_regex_fallback(text)
    try:
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        scored: dict[str, int] = json.loads(raw)
        return dict(
            sorted(
                {k: max(1, min(10, int(v))) for k, v in scored.items()}.items(),
                key=lambda x: -x[1],
            )[:25]
        )
    except Exception:
        return _keyword_regex_fallback(text)


# ─────────────────────────────────────────────────────────────
#  Profile import helpers
# ─────────────────────────────────────────────────────────────


def _apply_orcid_keywords(keywords: dict, orcid_url: str = "") -> None:
    """Merge ORCID keywords into session state and auto-draft description."""
    if keywords:
        st.session_state.keywords = _merge_keyword_weights(
            st.session_state.keywords, keywords
        )
        if not st.session_state.research_description:
            if _ai_available():
                _drafted = draft_research_description(st.session_state.keywords)
            else:
                _top_kws = [
                    k
                    for k, _ in sorted(
                        st.session_state.keywords.items(), key=lambda x: -x[1]
                    )[:5]
                ]
                _drafted = (
                    f"My research focuses on {', '.join(_top_kws)}." if _top_kws else ""
                )
            if _drafted:
                st.session_state.research_description = _drafted
                st.session_state._research_description_val = _drafted
                st.session_state["research_description_widget"] = _drafted
    st.session_state.pure_scanned = True
    if orcid_url:
        st.session_state.pure_confirmed_url = orcid_url


def _apply_pure_keywords(keywords: dict | None, coauthors: list | None) -> None:
    """Merge Pure-scraped keywords and co-authors into session state."""
    if keywords:
        merged = dict(st.session_state.keywords)
        merged.update(keywords)
        st.session_state.keywords = merged
    if coauthors:
        for name in coauthors[:15]:
            parts = name.split()
            if len(parts) >= 2:
                match_pattern = f"{parts[-1]}, {parts[0][0]}"
                if not any(
                    c["name"] == name for c in st.session_state.colleagues_people
                ):
                    st.session_state.colleagues_people.append(
                        {"name": name, "match": [match_pattern]}
                    )
    st.session_state.pure_scanned = True


def _maybe_seed_research_description(
    research_summary: str = "",
    keywords: dict | None = None,
    titles: list[str] | None = None,
) -> None:
    """Seed the editable research description if the user has not written one yet."""
    if st.session_state.research_description:
        return

    drafted = ""
    if research_summary:
        drafted = research_summary
    elif keywords:
        if _ai_available():
            drafted = draft_research_description(keywords)
        else:
            top_keywords = [k for k, _ in sorted(keywords.items(), key=lambda x: -x[1])[:5]]
            drafted = (
                f"My research focuses on {', '.join(top_keywords)}."
                if top_keywords
                else ""
            )
    elif titles:
        top_titles = list(titles)[:5]
        words: list[str] = []
        stopwords = {
            "a",
            "an",
            "the",
            "of",
            "in",
            "on",
            "at",
            "to",
            "for",
            "and",
            "or",
            "with",
            "from",
            "by",
            "is",
            "are",
            "using",
        }
        for title in top_titles:
            for word in title.split():
                clean = re.sub(r"[^a-zA-Z\\-]", "", word)
                if len(clean) > 4 and clean.lower() not in stopwords:
                    words.append(clean)
        unique_words = list(dict.fromkeys(words))[:6]
        if unique_words:
            drafted = (
                f"My research focuses on {', '.join(unique_words[:-1])}, and {unique_words[-1]}. "
                f"These topics span my recent publications in areas including "
                f"{', '.join(w.lower() for w in unique_words[:3])}."
            )

    if drafted:
        st.session_state.research_description = drafted
        st.session_state._research_description_val = drafted
        st.session_state["research_description_widget"] = drafted


def _import_profile(result: dict) -> None:
    """Full import from a single ORCID search result: fill profile + extract keywords."""
    # Pre-fill profile fields
    st.session_state.profile_name = result["name"]
    if result.get("department"):
        st.session_state.profile_institution = result["department"]
    st.session_state.pure_confirmed_url = result["url"]

    # Extract keywords from publications
    orcid_id = result["url"].rstrip("/").split("/")[-1]
    if not _PURE_AVAILABLE:
        st.info("Pure lookup is temporarily unavailable — using ORCID only.")
        return
    (
        keywords,
        _titles,
        _works_meta,
        _coauthor_map,
        _coauthor_counts,
        error,
    ) = fetch_orcid_works(orcid_id)
    # Persist titles, works meta, and coauthor map for paper selector and suggested colleagues
    st.session_state["_orcid_titles"] = _titles or []
    st.session_state["_orcid_works_meta"] = _works_meta or []
    st.session_state["_orcid_coauthor_map"] = (
        dict(_coauthor_map) if _coauthor_map else {}
    )
    st.session_state["_orcid_coauthor_counts"] = (
        dict(_coauthor_counts) if _coauthor_counts else {}
    )
    if not error and keywords:
        _apply_orcid_keywords(keywords, orcid_url=result["url"])
    else:
        st.session_state.pure_scanned = True
        st.session_state.pure_confirmed_url = result["url"]

    st.rerun()


# ─────────────────────────────────────────────────────────────
#  Server-key mode + rate limiting
# ─────────────────────────────────────────────────────────────


def _has_server_key() -> bool:
    """True if the current invite code unlocked shared AI credentials."""
    invite_bundle = st.session_state.get("_invite_bundle", {})
    return bool(
        str(invite_bundle.get("gemini_api_key", "")).strip()
        or str(invite_bundle.get("anthropic_api_key", "")).strip()
    )


def _normalise_invite_bundles(raw: object) -> dict[str, dict[str, str]]:
    """Return invite-code bundles in a consistent {code: secrets} shape."""
    if not isinstance(raw, Mapping):
        return {}

    bundles: dict[str, dict[str, str]] = {}
    for code, payload in raw.items():
        clean_code = str(code).strip()
        if not clean_code:
            continue

        if isinstance(payload, str):
            token = payload.strip()
            if token:
                bundles[clean_code] = {"relay_token": token}
            continue

        if not isinstance(payload, Mapping):
            continue

        relay_token = str(
            payload.get("relay_token") or payload.get("digest_relay_token") or ""
        ).strip()
        gemini_key = str(payload.get("gemini_api_key") or "").strip()
        anthropic_key = str(payload.get("anthropic_api_key") or "").strip()

        secrets_bundle = {
            key: value
            for key, value in {
                "relay_token": relay_token,
                "gemini_api_key": gemini_key,
                "anthropic_api_key": anthropic_key,
            }.items()
            if value
        }
        if secrets_bundle:
            bundles[clean_code] = secrets_bundle

    return bundles


def _get_invite_bundle(code: str) -> dict[str, str]:
    """Look up an invite code from Streamlit secrets and return its secret bundle."""
    invite_code = code.strip()
    if not invite_code:
        return {}

    raw_sources: list[object] = []
    try:
        json_blob = st.secrets.get("INVITE_CODES_JSON")
        if json_blob:
            raw_sources.append(json.loads(json_blob))
    except Exception:
        pass

    for key in ("invite_codes", "INVITE_CODES"):
        try:
            raw_sources.append(st.secrets.get(key))
        except Exception:
            pass

    bundles: dict[str, dict[str, str]] = {}
    for raw in raw_sources:
        bundles.update(_normalise_invite_bundles(raw))

    for candidate_code, bundle in bundles.items():
        if hmac.compare_digest(invite_code, candidate_code.strip()):
            return bundle
    return {}


# Module-level dict: email (lowercased) → unix timestamp of last use.
# Persists for the lifetime of the Streamlit process (resets on redeploy).
_DAILY_USAGE: dict[str, float] = {}
_RATE_LIMIT_SECONDS = 86400  # 24 hours


def _is_rate_limited(email: str) -> bool:
    last = _DAILY_USAGE.get(email.lower().strip(), 0.0)
    return (time.time() - last) < _RATE_LIMIT_SECONDS


def _record_usage(email: str) -> None:
    _DAILY_USAGE[email.lower().strip()] = time.time()


# ─────────────────────────────────────────────────────────────
#  Session state defaults
# ─────────────────────────────────────────────────────────────

if "keywords" not in st.session_state:
    st.session_state.keywords = {}
if "colleagues_people" not in st.session_state:
    st.session_state.colleagues_people = []
if "colleagues_institutions" not in st.session_state:
    st.session_state.colleagues_institutions = []
if "research_authors" not in st.session_state:
    st.session_state.research_authors = []
if "pure_scanned" not in st.session_state:
    st.session_state.pure_scanned = False
if "self_match" not in st.session_state:
    st.session_state.self_match = []
if "ai_suggested_cats" not in st.session_state:
    st.session_state.ai_suggested_cats = []
if "ai_suggested_kws" not in st.session_state:
    st.session_state.ai_suggested_kws = {}
# Profile prefill from ORCID scan
if "profile_name" not in st.session_state:
    st.session_state.profile_name = ""
if "profile_institution" not in st.session_state:
    st.session_state.profile_institution = ""
if "profile_department" not in st.session_state:
    st.session_state.profile_department = ""
# Research description (editable, can be auto-drafted from publications).
# _research_description_val is the backing store; the text_area widget uses a
# separate key so that programmatic updates (e.g. from ORCID import) are
# reflected on the next render without the widget state shadowing the value.
if "research_description" not in st.session_state:
    st.session_state.research_description = ""
if "_research_description_val" not in st.session_state:
    st.session_state._research_description_val = ""
# Wizard step tracking — 1-indexed, controls which setup steps are revealed
if "current_step" not in st.session_state:
    st.session_state.current_step = 1
else:
    st.session_state.current_step = max(1, min(int(st.session_state.current_step), 4))
if "profile_mode" not in st.session_state:
    st.session_state.profile_mode = "individual"
# Paper selector: subset of fetched ORCID titles to use for keyword/category AI suggestions
if "selected_papers" not in st.session_state:
    st.session_state.selected_papers = []
if "_orcid_coauthor_counts" not in st.session_state:
    st.session_state["_orcid_coauthor_counts"] = {}
if "group_orcid_members" not in st.session_state:
    st.session_state.group_orcid_members = []
if "_invite_bundle" not in st.session_state:
    st.session_state["_invite_bundle"] = {}


# ─────────────────────────────────────────────────────────────
#  Welcome
# ─────────────────────────────────────────────────────────────

st.markdown("# 🔭 arXiv Digest Setup")
st.markdown("""
Set up your personal arXiv digest in 5 minutes. This wizard generates a `config.yaml`
that you drop into your GitHub fork — then you'll get curated papers delivered to your inbox.
""")

st.markdown(
    f"""
<div style="font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.1em;
     text-transform: uppercase; color: {WARM_GREY}; margin-top: -8px; margin-bottom: 24px;">
     Built by <a href="https://silkedainese.github.io" style="color: {PINE};">Silke S. Dainese</a>
</div>
""",
    unsafe_allow_html=True,
)

hidden_setup_mode = str(st.query_params.get("setup", "")).strip().lower()
if hidden_setup_mode == "au_students":
    render_au_student_setup()
    st.stop()

setup_mode = st.radio(
    "Setup mode",
    options=["full_researcher", "mini_no_orcid"],
    format_func=lambda mode: {
        "full_researcher": "Researcher setup — ORCID, profile import, fine control",
        "mini_no_orcid": "Mini setup — no ORCID, just pick astronomy interests",
    }[mode],
    horizontal=True,
    label_visibility="collapsed",
)

if setup_mode == "mini_no_orcid":
    render_mini_setup()
    st.stop()

# ── Invite code (optional) ──
st.markdown("### Invite code")
invite_code = st.text_input(
    "Invite code (optional)",
    key="invite_code_input",
    type="password",
    placeholder="Only if Silke gave you one",
    help="Unlocks shared relay / AI access for invited users.",
)
invite_bundle = _get_invite_bundle(invite_code)
st.session_state["_invite_bundle"] = invite_bundle
if invite_code.strip():
    if invite_bundle:
        unlocked = []
        if invite_bundle.get("relay_token"):
            unlocked.append("relay")
        if invite_bundle.get("gemini_api_key") or _has_server_key():
            unlocked.append("Gemini")
        if invite_bundle.get("anthropic_api_key"):
            unlocked.append("Anthropic")
        st.success(
            "Invite code accepted — shared "
            + ", ".join(unlocked)
            + " access is enabled for this session."
        )
    else:
        st.warning("Invite code not recognised.")

# ── AI setup — invite-unlocked shared key or bring-your-own ──
if _has_server_key():
    # Server has a key — just ask for email for rate limiting
    st.markdown("## Get started")
    st.markdown("AI is included — no API key needed. Enter your email to begin.")
    user_email = st.text_input(
        "Your email",
        placeholder="you@university.edu",
        key="user_email_rl",
    )
    if not user_email.strip():
        st.stop()
    if _is_rate_limited(user_email):
        st.warning(
            "You've already generated a config today. "
            "Come back tomorrow, or [get your own free Gemini key](https://aistudio.google.com/app/apikey) to run without limits."
        )
        st.stop()
    _record_usage(user_email)
    st.success("Ready — AI powered by Gemini.")
else:
    # No server key — user can optionally bring their own for smarter setup
    st.markdown("## AI scoring (optional)")
    st.markdown(
        "Add an AI key to auto-fill your profile, suggest keywords, and score papers more accurately. "
        "Without a key, keyword matching still works — you can always add one later as a repo secret."
    )
    col_g, col_a = st.columns(2)
    with col_g:
        st.markdown("**Gemini** — free tier, no credit card")
        st.text_input(
            "Gemini API key",
            type="password",
            placeholder="AIza...",
            key="user_gemini_key",
            label_visibility="collapsed",
            help="Get a free key at aistudio.google.com",
        )
        st.caption("[Get a free key →](https://aistudio.google.com/app/apikey)")
    with col_a:
        st.markdown("**Anthropic** — Claude")
        st.text_input(
            "Anthropic API key",
            type="password",
            placeholder="sk-ant-...",
            key="user_anthropic_key",
            label_visibility="collapsed",
            help="Get a key at console.anthropic.com",
        )
        st.caption("[Get a key →](https://console.anthropic.com/settings/keys)")

    if _ai_available():
        with st.spinner("Checking key..."):
            _key_ok, _provider, _key_err = _test_ai_key(
                _get_gemini_key() or "", _get_anthropic_key() or ""
            )
        if _key_ok:
            st.success(f"AI ready — using {_provider}.")
        else:
            st.error(f"Key didn't work: {_key_err}")
            st.stop()
    else:
        st.info(
            "No AI key — that's fine! You'll fill in categories and keywords manually. "
            "Add a key later as a repo secret for smarter daily scoring."
        )

ai_assist = _ai_available()

st.divider()

profile_mode = st.radio(
    "Who is this digest for?",
    options=["individual", "group"],
    format_func=lambda mode: {
        "individual": "Individual researcher",
        "group": "Research group / journal club",
    }[mode],
    horizontal=True,
    index=0 if st.session_state.profile_mode == "individual" else 1,
)
st.session_state.profile_mode = profile_mode


# ─────────────────────────────────────────────────────────────
#  Step 1 helpers: ORCID import and preview
# ─────────────────────────────────────────────────────────────

if "pure_confirmed_url" not in st.session_state:
    st.session_state.pure_confirmed_url = ""
if "orcid_preview" not in st.session_state:
    st.session_state.orcid_preview = (
        None  # dict with name/institution/orcid_url/keywords when pending
    )


def _commit_preview() -> None:
    """Write the staged orcid_preview into session state and mark as scanned."""
    p = st.session_state.orcid_preview
    if not p:
        return

    full_name = p.get("name", "").strip()
    member_name_blocklist = _group_member_names(full_name)

    # Add confirmed AU colleagues, excluding imported group members.
    for name in p.get("selected_colleagues", []):
        if name.strip().lower() in member_name_blocklist:
            continue
        parts = name.split()
        if len(parts) >= 2:
            match_pattern = f"{parts[-1]}, {parts[0][0]}"
        else:
            match_pattern = name
        if not any(c["name"] == name for c in st.session_state.colleagues_people):
            st.session_state.colleagues_people.append(
                {"name": name, "match": [match_pattern]}
            )

    if st.session_state.get("profile_mode") == "group":
        imported_members = list(st.session_state.get("group_orcid_members", []))
        if not any(m.get("orcid_url") == p["orcid_url"] for m in imported_members):
            imported_members.append(
                {
                    "name": full_name,
                    "institution": p.get("institution", ""),
                    "orcid_url": p["orcid_url"],
                    "paper_count": len(p.get("titles", [])),
                }
            )
        st.session_state.group_orcid_members = imported_members

        if p["keywords"]:
            st.session_state.keywords = _merge_keyword_weights(
                st.session_state.keywords, p["keywords"]
            )

        for pattern in _name_match_patterns(full_name):
            if pattern not in st.session_state.self_match:
                st.session_state.self_match.append(pattern)

        st.session_state.colleagues_people = [
            colleague
            for colleague in st.session_state.colleagues_people
            if colleague.get("name", "").strip().lower()
            not in _group_member_names()
        ]

        st.session_state["_orcid_titles"] = _dedupe_titles(
            st.session_state.get("_orcid_titles", []), p.get("titles", [])
        )
        st.session_state["_orcid_works_meta"] = _merge_works_meta(
            st.session_state.get("_orcid_works_meta", []), p.get("works_meta", [])
        )
        st.session_state["_orcid_coauthor_map"] = _merge_coauthor_maps(
            st.session_state.get("_orcid_coauthor_map", {}), p.get("coauthor_map", {})
        )
        st.session_state["_orcid_coauthor_counts"] = _merge_coauthor_counts(
            st.session_state.get("_orcid_coauthor_counts", {}),
            p.get("coauthor_counts", {}),
        )
        st.session_state.selected_papers = [
            title
            for title in st.session_state.selected_papers
            if title in st.session_state["_orcid_titles"]
        ]

        if not st.session_state.profile_institution and p.get("institution"):
            st.session_state.profile_institution = p["institution"]
        if not st.session_state.profile_name:
            st.session_state.profile_name = "Research Group"
        st.session_state.pure_confirmed_url = (
            f"{len(imported_members)} ORCID"
            f"{'' if len(imported_members) == 1 else 's'} imported"
        )
        _maybe_seed_research_description(
            research_summary=p.get("research_summary", ""),
            keywords=st.session_state.keywords,
            titles=st.session_state.get("_orcid_titles", []),
        )
        st.session_state.pure_scanned = bool(imported_members)
    else:
        st.session_state.profile_name = full_name
        st.session_state.profile_institution = p["institution"]
        st.session_state.pure_confirmed_url = p["orcid_url"]

        if p["keywords"]:
            st.session_state.keywords = _merge_keyword_weights(
                st.session_state.keywords, p["keywords"]
            )

        for pattern in _name_match_patterns(full_name):
            if pattern not in st.session_state.self_match:
                st.session_state.self_match.append(pattern)

        st.session_state["_orcid_titles"] = p.get("titles", [])
        st.session_state["_orcid_works_meta"] = p.get("works_meta", [])
        st.session_state["_orcid_coauthor_map"] = p.get("coauthor_map", {})
        st.session_state["_orcid_coauthor_counts"] = p.get("coauthor_counts", {})
        _maybe_seed_research_description(
            research_summary=p.get("research_summary", ""),
            keywords=p.get("keywords", {}),
            titles=p.get("titles", []),
        )
        st.session_state.pure_scanned = True

    st.session_state.orcid_preview = None


# ─────────────────────────────────────────────────────────────
#  Step 1: About You
# ─────────────────────────────────────────────────────────────

if st.session_state.current_step >= 1:
    st.markdown(
        '<p><span class="step-number">1</span> <strong>About You</strong></p>',
        unsafe_allow_html=True,
    )

    if profile_mode == "group":
        st.markdown(
            "ORCID import is optional for groups. You can skip this step and configure the group manually, or import up to 8 member ORCIDs to bootstrap shared keywords, categories, and colleague suggestions."
        )
    else:
        st.markdown(
            "Enter your ORCID ID — we'll pull your profile and publications automatically."
        )

    group_members = st.session_state.get("group_orcid_members", [])
    max_group_orcids = 8

    if profile_mode == "group":
        if group_members:
            st.success(
                f"✓ Imported {len(group_members)} member ORCID"
                f"{'' if len(group_members) == 1 else 's'}"
            )
            for member in group_members:
                paper_count = int(member.get("paper_count", 0))
                paper_label = "paper" if paper_count == 1 else "papers"
                st.caption(
                    f"• {member.get('name', 'Unknown member')} · {member.get('institution', 'No institution listed')} · {paper_count} {paper_label}"
                )
            if st.button("↺ Clear imported ORCIDs", type="secondary"):
                st.session_state.pure_scanned = False
                st.session_state.pure_confirmed_url = ""
                st.session_state.orcid_preview = None
                st.session_state.group_orcid_members = []
                st.session_state["_orcid_titles"] = []
                st.session_state["_orcid_works_meta"] = []
                st.session_state["_orcid_coauthor_map"] = {}
                st.session_state["_orcid_coauthor_counts"] = {}
                _set_selected_papers([])
                st.rerun()
        else:
            st.caption(
                "Optional: import a few representative members to seed the group digest automatically."
            )
    elif st.session_state.pure_scanned:
        st.success(f"✓ Profile loaded from {st.session_state.pure_confirmed_url}")
        if st.button("↺ Use a different ORCID", type="secondary"):
            st.session_state.pure_scanned = False
            st.session_state.pure_confirmed_url = ""
            st.session_state.orcid_preview = None
            st.session_state["_orcid_titles"] = []
            st.session_state["_orcid_works_meta"] = []
            st.session_state["_orcid_coauthor_map"] = {}
            st.session_state["_orcid_coauthor_counts"] = {}
            _set_selected_papers([])
            st.rerun()

    can_add_group_member = len(group_members) < max_group_orcids
    show_import_controls = profile_mode == "group" or not st.session_state.pure_scanned

    if show_import_controls:
        col_input, col_btn = st.columns([5, 1])
        with col_input:
            orcid_input = st.text_input(
                "ORCID",
                placeholder="0000-0001-2345-6789  or  https://orcid.org/0000-0001-2345-6789",
                key="orcid_input_field",
                label_visibility="collapsed",
            )
        with col_btn:
            fetch_clicked = st.button(
                "🔍 Fetch" if profile_mode == "individual" else "＋ Add",
                type="primary",
                use_container_width=True,
                disabled=profile_mode == "group" and not can_add_group_member,
            )

        if profile_mode == "group" and not can_add_group_member:
            st.caption(
                f"Imported {max_group_orcids} ORCIDs already. Continue, or clear them and start over."
            )

        if orcid_input and fetch_clicked:
            inp = orcid_input.strip().rstrip("/")
            if inp.startswith("https://orcid.org/"):
                orcid_id = inp.split("/")[-1]
                orcid_url = inp
            elif _ORCID_ID_RE.match(inp):
                orcid_id = inp
                orcid_url = f"https://orcid.org/{inp}"
            else:
                st.error(
                    "That doesn't look like an ORCID. Expected format: 0000-0001-2345-6789"
                )
                orcid_id = ""
                orcid_url = ""

            if orcid_id and not _PURE_AVAILABLE:
                st.info("Pure lookup is temporarily unavailable — using ORCID only.")
            elif orcid_id:
                with st.spinner("Fetching profile and publications from ORCID..."):
                    full_name, institution, person_error = fetch_orcid_person(orcid_id)
                    (
                        keywords,
                        titles,
                        works_meta,
                        coauthor_map,
                        coauthor_counts,
                        works_error,
                    ) = fetch_orcid_works(orcid_id)

                if person_error:
                    st.error(f"Could not fetch profile: {person_error}")
                else:
                    au_colleagues: list[str] = []
                    if _PURE_AVAILABLE and coauthor_map:
                        with st.spinner(
                            "Checking co-authors for Aarhus University affiliation..."
                        ):
                            au_colleagues = find_au_colleagues(
                                coauthor_map,
                                coauthor_counts=coauthor_counts,
                                institution=institution or "Aarhus University",
                            )

                    research_summary = ""
                    if titles and ai_assist:
                        with st.spinner("Summarising your research..."):
                            research_summary = _summarise_research(titles)

                    blocked_names = (
                        _group_member_names(full_name)
                        if profile_mode == "group"
                        else {full_name.strip().lower()}
                    )
                    au_colleagues = [
                        name
                        for name in au_colleagues
                        if name.strip().lower() not in blocked_names
                    ]
                    sorted_coauthors = (
                        [
                            name
                            for name, _ in sorted(
                                (coauthor_counts or {}).items(),
                                key=lambda item: (-item[1], item[0].lower()),
                            )
                            if name.strip().lower() not in blocked_names
                        ]
                        if coauthor_counts
                        else []
                    )

                    if profile_mode == "group" and any(
                        member.get("orcid_url") == orcid_url for member in group_members
                    ):
                        st.info("That ORCID is already imported for this group.")

                    st.session_state.orcid_preview = {
                        "name": full_name,
                        "institution": institution or "Aarhus University",
                        "orcid_url": orcid_url,
                        "keywords": keywords or {},
                        "titles": titles or [],
                        "works_meta": works_meta or [],
                        "au_colleagues": au_colleagues,
                        "all_coauthors": sorted_coauthors,
                        "coauthor_map": dict(coauthor_map) if coauthor_map else {},
                        "coauthor_counts": (
                            dict(coauthor_counts) if coauthor_counts else {}
                        ),
                        "research_summary": research_summary,
                        "selected_colleagues": list(au_colleagues),
                    }
                    if works_error:
                        st.warning(
                            "Profile found but no publications on ORCID — keywords and colleagues will be empty."
                        )

        if st.session_state.orcid_preview:
            p = st.session_state.orcid_preview
            st.markdown(f"**{p['name']}** · {p['institution']}")
            st.caption(f"ORCID: {p['orcid_url']}")

            if p["keywords"]:
                st.markdown("**Keywords from your publications:**")
                kw_display = "  ·  ".join(
                    k
                    for k, _ in sorted(p["keywords"].items(), key=lambda x: -x[1])[:12]
                )
                st.caption(kw_display + "  _(you can adjust these below)_")
            else:
                st.caption("No keywords found — you can add them manually below.")

            st.markdown(
                "**Colleagues to track** — papers by these people always appear in your digest:"
            )
            p.setdefault("selected_colleagues", [])

            if p.get("au_colleagues"):
                st.caption(
                    f"Found {len(p['au_colleagues'])} co-authors at {p['institution']} — uncheck any to exclude, or add more below."
                )
                manual = [
                    c for c in p["selected_colleagues"] if c not in p["au_colleagues"]
                ]
                selected = list(manual)
                for colleague in p["au_colleagues"]:
                    checked = st.checkbox(
                        colleague, value=True, key=f"colleague_{colleague}"
                    )
                    if checked:
                        selected.append(colleague)
                p["selected_colleagues"] = selected
            elif p.get("titles"):
                st.caption(
                    f"No co-authors with confirmed {p['institution']} affiliation found automatically."
                )

            manual_added = [
                c
                for c in p["selected_colleagues"]
                if c not in p.get("au_colleagues", [])
            ]
            if manual_added:
                st.caption("Manually added colleagues:")
                to_remove = []
                for mc in manual_added:
                    mc_col, rm_col = st.columns([6, 1])
                    with mc_col:
                        st.markdown(f"· {mc}")
                    with rm_col:
                        if st.button("✕", key=f"rm_manual_{mc}"):
                            to_remove.append(mc)
                for mc in to_remove:
                    p["selected_colleagues"].remove(mc)
                if to_remove:
                    st.rerun()

            st.caption("Add a colleague by their ORCID:")
            extra_col, extra_btn = st.columns([4, 1])
            with extra_col:
                extra_orcid = st.text_input(
                    "Colleague ORCID",
                    placeholder="0000-0001-2345-6789  or  https://orcid.org/...",
                    key="preview_extra_orcid",
                    label_visibility="collapsed",
                )
            with extra_btn:
                add_clicked = st.button("Look up", key="preview_add_colleague")

            if add_clicked and extra_orcid.strip():
                inp = extra_orcid.strip().rstrip("/")
                if inp.startswith("https://orcid.org/"):
                    lookup_id = inp.split("/")[-1]
                elif _ORCID_ID_RE.match(inp):
                    lookup_id = inp
                else:
                    st.error("Enter a valid ORCID (e.g. 0000-0001-2345-6789).")
                    lookup_id = ""

                if lookup_id and not _PURE_AVAILABLE:
                    st.info("Pure lookup is temporarily unavailable — using ORCID only.")
                elif lookup_id:
                    with st.spinner("Looking up colleague..."):
                        found_name, found_inst, found_err = fetch_orcid_person(
                            lookup_id
                        )
                    if found_err:
                        st.error(f"Could not fetch: {found_err}")
                    elif found_name and found_name not in p["selected_colleagues"]:
                        p["selected_colleagues"].append(found_name)
                        st.success(
                            f"Added {found_name} ({found_inst or 'no institution on ORCID'})"
                        )
                        st.rerun()

            all_coauthors = p.get("all_coauthors", [])
            _coauthor_blocklist = _group_member_names(p.get("name", ""))
            pickable = [
                n
                for n in all_coauthors
                if n not in p["selected_colleagues"]
                and n.strip().lower() not in _coauthor_blocklist
            ]
            if pickable:
                st.markdown(f"**Or pick from your {len(all_coauthors)} ORCID co-authors**")
                pick_filter = st.text_input(
                    "Filter by name",
                    key="coauthor_pick_filter",
                    placeholder="type to filter…",
                )
                filtered = (
                    [n for n in pickable if pick_filter.lower() in n.lower()]
                    if pick_filter
                    else pickable
                )
                for name in filtered[:30]:
                    if st.button(f"+ {name}", key=f"pick_coauthor_{name}"):
                        p["selected_colleagues"].append(name)
                        st.rerun()
                if len(filtered) > 30:
                    st.caption(f"Showing 30 of {len(filtered)} — type more to narrow.")

            import_label = (
                "✓ Add this member"
                if profile_mode == "group"
                else "✓ Looks good — import"
            )
            if st.button(import_label, type="primary"):
                _commit_preview()
                st.rerun()

    orcid_profile_loaded = st.session_state.pure_scanned or bool(group_members)
    show_manual_profile_fields = (
        profile_mode == "group"
        or orcid_profile_loaded
        or st.session_state.get("_show_manual_profile_fields", False)
    )

    if not show_manual_profile_fields:
        if st.button("No ORCID? Fill manually", key="show_manual_profile_fields_btn"):
            st.session_state["_show_manual_profile_fields"] = True
            st.rerun()

    if show_manual_profile_fields:
        col1, col2 = st.columns(2)
        with col1:
            _name_label = "Group / course name" if profile_mode == "group" else "Your name"
            _name_placeholder = (
                "AU Exoplanet Group" if profile_mode == "group" else "Jane Smith"
            )
            researcher_name = st.text_input(
                _name_label, placeholder=_name_placeholder, key="profile_name"
            )
            institution = st.text_input(
                "Institution (optional)",
                placeholder="Aarhus University",
                key="profile_institution",
            )

        if ai_assist and st.session_state.research_description and orcid_profile_loaded:
            st.caption(
                "Auto-generated from your publications. Edit freely — the AI reads this daily to score papers."
            )
        elif profile_mode == "group":
            st.caption(
                "Describe your group's interests in 3-5 sentences. More specific = better AI scoring."
            )
        else:
            st.caption(
                "Describe your research like you'd tell a colleague. More specific = better AI scoring."
            )

        research_context_widget = st.text_area(
            "Research context",
            value=st.session_state._research_description_val,
            height=120,
            placeholder="I study exoplanet atmospheres using transmission spectroscopy with JWST and ground-based instruments. I focus on hot Jupiters and sub-Neptunes, particularly their atmospheric composition and cloud properties.",
            label_visibility="collapsed",
            key="research_description_widget",
        )
        st.session_state.research_description = research_context_widget
        st.session_state._research_description_val = research_context_widget

        with st.expander("Advanced profile settings"):
            col1, col2 = st.columns(2)
            with col1:
                digest_name = st.text_input(
                    "Digest name",
                    value=st.session_state.get("_s2_digest_name", "arXiv Digest"),
                    help="Appears in the email subject line",
                )
                department = st.text_input(
                    "Department (optional)",
                    placeholder="Dept. of Physics & Astronomy",
                    key="profile_department",
                )
            with col2:
                tagline = st.text_input(
                    "Footer tagline (optional)",
                    value=st.session_state.get("_s2_tagline", ""),
                    placeholder="Ad astra per aspera",
                    help="A quote or motto for the email footer",
                )

            if profile_mode == "group":
                st.markdown(
                    "**Group members on arXiv** — optional. Add author patterns if you want the digest to flag and celebrate papers from anyone in the group."
                )
            else:
                st.markdown(
                    "**Your name on arXiv** — if you publish a paper, you'll get a special celebration in your digest!"
                )

            col1, col2 = st.columns([3, 1])
            with col1:
                new_self = st.text_input(
                    "Author match pattern",
                    placeholder="Smith, J",
                    key="self_match_input",
                    label_visibility="collapsed",
                    help=(
                        "How a member name appears in arXiv author lists (e.g. 'Smith, J' or 'Jane Smith')"
                        if profile_mode == "group"
                        else "How your name appears in arXiv author lists (e.g. 'Smith, J' or 'Jane Smith')"
                    ),
                )
            with col2:
                if st.button(
                    "Add pattern" if profile_mode == "group" else "Add",
                    key="add_self_match",
                    use_container_width=True,
                ):
                    if (
                        new_self.strip()
                        and new_self.strip() not in st.session_state.self_match
                    ):
                        st.session_state.self_match.append(new_self.strip())
                        st.rerun()

            if st.session_state.self_match:
                to_remove = []
                for pattern in st.session_state.self_match:
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.markdown(f"- `{pattern}`")
                    with col2:
                        if st.button("✕", key=f"rm_self_{pattern}"):
                            to_remove.append(pattern)
                for pattern in to_remove:
                    st.session_state.self_match.remove(pattern)
                if to_remove:
                    st.rerun()

            st.session_state["_s2_digest_name"] = digest_name
            st.session_state["_s2_tagline"] = tagline

    _s1_label = (
        "Skip ORCID — continue to Step 2 →"
        if profile_mode == "group" and not st.session_state.pure_scanned
        else "Looks good — continue to Step 2 →"
    )
    if st.button(_s1_label, key="s1_continue", type="primary"):
        st.session_state.current_step = 2
        st.rerun()

researcher_name = st.session_state.get("profile_name", "")
institution = st.session_state.get("profile_institution", "")
department = st.session_state.get("profile_department", "")
digest_name = st.session_state.get("_s2_digest_name", "arXiv Digest")
tagline = st.session_state.get("_s2_tagline", "")
research_context = st.session_state.get("research_description", "")


# ─────────────────────────────────────────────────────────────
#  Step 2: What to Follow
# ─────────────────────────────────────────────────────────────

ai_suggested_set = set(st.session_state.ai_suggested_cats) if ai_assist else set()

if "selected_categories" not in st.session_state:
    st.session_state.selected_categories = set(ai_suggested_set)

if ai_suggested_set and not st.session_state.selected_categories.issuperset(
    ai_suggested_set
):
    st.session_state.selected_categories.update(ai_suggested_set)

if st.session_state.current_step >= 2:
    st.markdown(
        '<p><span class="step-number">2</span> <strong>What to Follow</strong></p>',
        unsafe_allow_html=True,
    )
    st.markdown("Which arXiv categories to scan, and which topics to look for.")

    _orcid_titles = st.session_state.get("_orcid_titles", [])
    _works_meta = st.session_state.get("_orcid_works_meta", [])
    _paper_context_limit = 30

    def _sort_titles_by_recency(
        titles: list[str], works_meta: list[dict], cap: int = 10
    ) -> list[str]:
        year_map: dict[str, int | None] = {}
        for entry in works_meta:
            title = entry.get("title", "")
            if title:
                existing = year_map.get(title)
                year = entry.get("year")
                if existing is None or (year is not None and year > existing):
                    year_map[title] = year

        def _sort_key(title: str) -> tuple[int, int]:
            year = year_map.get(title)
            return (0, -(year or 0)) if year is not None else (1, 0)

        return sorted(titles, key=_sort_key)[:cap]

    def _run_context_suggestions(context_text: str) -> None:
        _has_orcid_kws = bool(st.session_state.keywords)
        _api_available = _ai_available()
        st.session_state.ai_suggested_cats = suggest_categories(context_text)
        st.session_state.ai_suggested_kws = suggest_keywords_from_context(
            context_text,
            orcid_keywords=st.session_state.keywords if _has_orcid_kws else None,
        )
        if _api_available and _has_orcid_kws:
            ai_lower = {
                keyword.lower(): weight
                for keyword, weight in st.session_state.ai_suggested_kws.items()
            }
            merged_kws = dict(st.session_state.keywords)
            for keyword in list(merged_kws.keys()):
                ai_score = ai_lower.get(keyword.lower())
                if ai_score is not None:
                    merged_kws[keyword] = ai_score
            st.session_state.keywords = merged_kws

    if _orcid_titles:
        _total_papers = len(_orcid_titles)
        _smart_threshold = 10
        _existing = [t for t in st.session_state.selected_papers if t in _orcid_titles]

        if not _existing:
            if _total_papers >= _smart_threshold:
                _default_selection = _sort_titles_by_recency(
                    _orcid_titles, _works_meta, cap=_smart_threshold
                )
                _selection_note = (
                    f"{_total_papers} papers found — showing smart selection of "
                    f"{len(_default_selection)} most recent"
                )
            else:
                _default_selection = list(_orcid_titles)
                _selection_note = ""
            _set_selected_papers(_default_selection)
        else:
            _default_selection = _existing
            _selection_note = ""
            if st.session_state.get("paper_selector_widget") != _existing:
                st.session_state["paper_selector_widget"] = list(_existing)

        st.markdown(
            f"""
<div style="background: rgba(212, 175, 55, 0.12); border: 1px solid {GOLD}; border-radius: 8px; padding: 12px 14px; margin: 12px 0;">
  <strong>Auto-fill from publications</strong><br>
  <span style="color: {WARM_GREY};">Suggest categories and keywords from your ORCID publications.</span>
</div>
""",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
<div style="background: rgba(212, 175, 55, 0.12); border: 1px solid {GOLD}; border-radius: 8px; padding: 12px 14px; margin: 12px 0;">
  <strong>Auto-fill from publications</strong><br>
  <span style="color: {WARM_GREY};">Use your research description to suggest categories and keywords.</span>
</div>
""",
            unsafe_allow_html=True,
        )

    _api_available = _ai_available()
    _cats_already_suggested = bool(st.session_state.ai_suggested_cats)
    _btn_label = (
        "Auto-fill from publications"
        if not _cats_already_suggested
        else "Re-run auto-fill"
    )
    _can_suggest = bool(research_context and len(research_context) > 30)
    if st.button(
        _btn_label,
        key="step2_autofill_btn",
        type="primary",
        disabled=not _can_suggest,
        help="Write a research description in Step 1 first." if not _can_suggest else None,
    ):
        with st.spinner("Suggesting categories and scoring keywords..."):
            _selected_titles = st.session_state.get("selected_papers", [])
            _effective_titles = _sort_titles_by_recency(
                _selected_titles, _works_meta, cap=_paper_context_limit
            )
            if len(_selected_titles) > _paper_context_limit:
                st.warning(
                    f"You selected {len(_selected_titles)} papers. AI will use the {_paper_context_limit} most recent selected papers."
                )
            if _effective_titles:
                _titles_block = "\n".join(f"- {title}" for title in _effective_titles)
                _ai_context = (
                    research_context + f"\n\nRepresentative publications:\n{_titles_block}"
                )
            else:
                _ai_context = research_context
            _run_context_suggestions(_ai_context)
        st.rerun()

    if _orcid_titles:
        st.markdown(
            "**Which papers should we use to suggest your keywords?** (select the most representative ones)"
        )
        if _total_papers >= _smart_threshold and _selection_note:
            st.caption(_selection_note)
        else:
            st.caption(
                "All fetched from your ORCID profile. Deselect papers from unrelated projects."
            )
        st.caption(
            f"AI uses at most {_paper_context_limit} selected papers for context, prioritising the most recent."
        )

        _current_selection = st.session_state.get("selected_papers", _default_selection)
        _preview_titles = _sort_titles_by_recency(
            _current_selection, _works_meta, cap=5
        )

        st.caption(
            f"Currently using {len(_current_selection)} paper"
            f"{'' if len(_current_selection) == 1 else 's'}."
        )
        if _preview_titles:
            for preview_title in _preview_titles:
                st.caption(f"• {preview_title}")

        st.markdown(
            f"**Edit paper selection ({len(st.session_state.get('selected_papers', []))} selected)**"
        )
        quick_col1, quick_col2, quick_col3, quick_col4 = st.columns(4)
        with quick_col1:
            if st.button("Recent 10", key="paper_recent_10"):
                _set_selected_papers(
                    _sort_titles_by_recency(_orcid_titles, _works_meta, cap=10)
                )
                st.rerun()
        with quick_col2:
            if st.button("Recent 30", key="paper_recent_30"):
                _set_selected_papers(
                    _sort_titles_by_recency(
                        _orcid_titles, _works_meta, cap=min(30, _total_papers)
                    )
                )
                st.rerun()
        with quick_col3:
            if st.button("Select all", key="paper_select_all"):
                _set_selected_papers(_orcid_titles)
                st.rerun()
        with quick_col4:
            if st.button("Clear", key="paper_clear"):
                _set_selected_papers([])
                st.rerun()

        _new_selection = st.multiselect(
            "Papers for keyword suggestions",
            options=_orcid_titles,
            default=_default_selection,
            label_visibility="collapsed",
            key="paper_selector_widget",
        )
        st.session_state.selected_papers = _new_selection
        if len(_new_selection) < _total_papers:
            st.caption(f"{len(_new_selection)} of {_total_papers} papers selected.")

    if (
        ai_assist
        and research_context
        and len(research_context) > 30
        and st.session_state.pure_scanned
        and not st.session_state.ai_suggested_cats
    ):
        _selected_titles = st.session_state.get("selected_papers", [])
        _effective_titles = _sort_titles_by_recency(
            _selected_titles, _works_meta, cap=_paper_context_limit
        )
        if _effective_titles:
            _titles_block = "\n".join(f"- {title}" for title in _effective_titles)
            _ai_context = (
                research_context + f"\n\nRepresentative publications:\n{_titles_block}"
            )
        else:
            _ai_context = research_context
        with st.spinner("Suggesting categories and scoring keywords..."):
            _run_context_suggestions(_ai_context)
        st.rerun()

    ai_suggested_set = set(st.session_state.ai_suggested_cats) if ai_assist else set()
    if ai_suggested_set and not st.session_state.selected_categories.issuperset(
        ai_suggested_set
    ):
        st.session_state.selected_categories.update(ai_suggested_set)

    if ai_assist and ai_suggested_set:
        st.success(
            f"AI suggested {len(ai_suggested_set)} categories and {len(st.session_state.ai_suggested_kws)} keywords — review them below."
        )

    st.markdown("**arXiv categories**")
    st.caption("Papers outside these categories are ignored.")

    to_add = set()
    to_remove = set()
    for group_name, group_cats in ARXIV_GROUPS.items():
        selected_in_group = [
            category
            for category in group_cats
            if category in st.session_state.selected_categories
        ]
        n_selected = len(selected_in_group)
        n_total = len(group_cats)
        hint = ARXIV_GROUP_HINTS.get(group_name, "")

        count_label = f"{n_selected}/{n_total} selected" if n_selected > 0 else ""
        show_group = st.checkbox(
            f"**{group_name}**" + (f" — {count_label}" if count_label else ""),
            value=(n_selected > 0),
            key=f"grp_show_{group_name}",
        )
        if show_group:
            if hint:
                st.caption(f"Include if: {hint}")

            col_all, col_none, _ = st.columns([1, 1, 4])
            with col_all:
                if st.button(
                    "Select all", key=f"grp_all_{group_name}", use_container_width=True
                ):
                    to_add.update(group_cats)
            with col_none:
                if st.button(
                    "Clear", key=f"grp_none_{group_name}", use_container_width=True
                ):
                    to_remove.update(group_cats)

            for cat_id in group_cats:
                label = ARXIV_CATEGORIES.get(cat_id, cat_id)
                is_selected = cat_id in st.session_state.selected_categories
                display_label = (
                    f"{label} \u2726" if cat_id in ai_suggested_set else label
                )
                checked = st.checkbox(
                    display_label,
                    value=is_selected,
                    key=f"cat_{cat_id}",
                    help=f"`{cat_id}`"
                    + (" — AI suggested" if cat_id in ai_suggested_set else ""),
                )
                if checked and not is_selected:
                    to_add.add(cat_id)
                elif not checked and is_selected:
                    to_remove.add(cat_id)

    if to_add or to_remove:
        st.session_state.selected_categories = (
            st.session_state.selected_categories | to_add
        ) - to_remove
        st.rerun()

    _cats_now = sorted(st.session_state.selected_categories)
    if _cats_now:
        st.markdown(
            f"**{len(_cats_now)} categories selected:** "
            + ", ".join(f"`{category}`" for category in _cats_now)
        )
    else:
        st.info("No categories selected yet. Expand a group above to choose.")

    if ai_assist and st.session_state.ai_suggested_kws:
        new_suggestions = {
            keyword: weight
            for keyword, weight in st.session_state.ai_suggested_kws.items()
            if keyword not in st.session_state.keywords
        }
        if new_suggestions:
            st.markdown("**Suggested keywords** — click to add:")
            cols = st.columns(3)
            to_add_keywords = {}
            for i, (keyword, weight) in enumerate(new_suggestions.items()):
                with cols[i % 3]:
                    if st.button(
                        f"+ {keyword} ({weight})",
                        key=f"add_sug_{keyword}",
                        use_container_width=True,
                    ):
                        to_add_keywords[keyword] = weight
            if to_add_keywords:
                st.session_state.keywords.update(to_add_keywords)
                st.rerun()

            if st.button("Add all suggested keywords", key="add_all_suggested_keywords"):
                st.session_state.keywords.update(new_suggestions)
                st.rerun()

    st.markdown("**Keywords**")
    st.caption("Topics your digest looks for. Each gets a default weight of 7.")
    current_kw_list = [
        keyword
        for keyword, _ in sorted(
            st.session_state.keywords.items(), key=lambda item: (-item[1], item[0].lower())
        )
    ]
    selected_kws = st.multiselect(
        "Keywords",
        options=current_kw_list,
        default=current_kw_list,
    )

    new_keywords = {}
    for keyword in selected_kws:
        new_keywords[keyword] = st.session_state.keywords.get(keyword, 7)
    st.session_state.keywords = new_keywords

    new_kw = st.text_input("Add a keyword", key="new_kw_input")
    if st.button("Add", key="add_kw_btn") and new_kw.strip():
        st.session_state.keywords[new_kw.strip()] = 7
        st.rerun()

    with st.expander("Advanced keyword settings"):
        st.caption(
            "0-2 loosely follow · 3-5 interested · 6-8 main interest · 9-10 everything"
        )
        if st.session_state.keywords:
            _kw_col_all, _kw_col_clear, _ = st.columns([1, 1, 4])
            with _kw_col_all:
                if st.button(
                    "Select all",
                    key="kw_select_all",
                    use_container_width=True,
                    help="Set all keyword weights to 10",
                ):
                    st.session_state.keywords = {
                        keyword: 10 for keyword in st.session_state.keywords
                    }
                    st.rerun()
            with _kw_col_clear:
                if st.button(
                    "Clear all",
                    key="kw_clear_all",
                    use_container_width=True,
                    help="Set all keyword weights to 0",
                ):
                    st.session_state.keywords = {
                        keyword: 0 for keyword in st.session_state.keywords
                    }
                    st.rerun()

            to_remove_keywords = []
            for keyword, weight in sorted(
                st.session_state.keywords.items(), key=lambda item: (-item[1], item[0].lower())
            ):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.markdown(f"`{keyword}`")
                with col2:
                    new_weight = st.slider(
                        "weight",
                        0,
                        10,
                        int(weight),
                        key=f"kw_slider_{keyword}",
                        label_visibility="collapsed",
                    )
                    st.caption(f"_{_weight_label(new_weight)}_")
                    st.session_state.keywords[keyword] = new_weight
                with col3:
                    if st.button("✕", key=f"rm_kw_{keyword}", help=f"Remove {keyword}"):
                        to_remove_keywords.append(keyword)

            for keyword in to_remove_keywords:
                del st.session_state.keywords[keyword]
            if to_remove_keywords:
                st.rerun()
        else:
            st.info("No keywords yet. Add some above, scan your ORCID, or use AI suggestions.")

    if st.button(
        "Looks good — continue to Step 3 →", key="s2_continue", type="primary"
    ):
        st.session_state.current_step = 3
        st.rerun()

categories = sorted(st.session_state.selected_categories)


# ─────────────────────────────────────────────────────────────
#  Step 3: People to Follow
# ─────────────────────────────────────────────────────────────

if st.session_state.current_step >= 3:
    st.markdown(
        '<p><span class="step-number">3</span> <strong>People to Follow</strong></p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "People whose papers you always want to see. Labmates, advisors, collaborators, researchers you follow."
    )

    people_index: dict[str, dict[str, object]] = {}
    for colleague in st.session_state.colleagues_people:
        lower_name = colleague.get("name", "").strip().lower()
        if lower_name:
            people_index[lower_name] = {
                "name": colleague["name"],
                "role": "colleague",
                "match": colleague.get("match", []),
            }
    for author in st.session_state.research_authors:
        lower_name = author.strip().lower()
        if lower_name in people_index:
            people_index[lower_name]["role"] = "colleague + research author"
        elif lower_name:
            people_index[lower_name] = {
                "name": author,
                "role": "research author",
                "match": [],
            }

    all_people = sorted(people_index.values(), key=lambda person: person["name"].lower())

    col1, col2 = st.columns([2, 2])
    with col1:
        new_person_name = st.text_input(
            "Person name", placeholder="Jane Smith", key="new_coll_name"
        )
    with col2:
        new_person_match = st.text_input(
            "Match pattern (optional)",
            placeholder="Smith, J",
            key="new_coll_match",
            help="If blank, we'll derive a standard arXiv match from the name.",
        )

    add_col, clear_col = st.columns([1, 1])
    with add_col:
        if st.button("Add person", key="add_person_btn", use_container_width=True):
            if new_person_name.strip():
                person_name = new_person_name.strip()
                if any(
                    person_name.lower() == colleague.get("name", "").strip().lower()
                    for colleague in st.session_state.colleagues_people
                ) or any(
                    person_name.lower() == author.strip().lower()
                    for author in st.session_state.research_authors
                ):
                    st.info(f"{person_name} is already in your list.")
                else:
                    parts = person_name.split()
                    match_pattern = new_person_match.strip() or (
                        f"{parts[-1]}, {parts[0][0]}" if len(parts) >= 2 else person_name
                    )
                    st.session_state.colleagues_people.append(
                        {"name": person_name, "match": [match_pattern]}
                    )
                    st.rerun()
    with clear_col:
        if all_people and st.button(
            "Clear", key="clear_people_btn", use_container_width=True
        ):
            st.session_state.colleagues_people = []
            st.session_state.research_authors = []
            st.rerun()

    if all_people:
        for person in all_people:
            col1, col2, col3 = st.columns([3, 2, 1])
            with col1:
                st.markdown(f"**{person['name']}**")
            with col2:
                role_label = str(person["role"]).replace("_", " ")
                if person["match"]:
                    st.caption(f"{role_label} · `{', '.join(person['match'])}`")
                else:
                    st.caption(role_label)
            with col3:
                if st.button("✕", key=f"rm_person_{person['name']}"):
                    lower_name = person["name"].strip().lower()
                    st.session_state.colleagues_people = [
                        colleague
                        for colleague in st.session_state.colleagues_people
                        if colleague.get("name", "").strip().lower() != lower_name
                    ]
                    st.session_state.research_authors = [
                        author
                        for author in st.session_state.research_authors
                        if author.strip().lower() != lower_name
                    ]
                    st.rerun()

    _coauthor_counts = st.session_state.get("_orcid_coauthor_counts", {})
    suggest_col, _ = st.columns([1, 4])
    with suggest_col:
        if _coauthor_counts and st.button(
            "Suggest from co-authors", key="show_coauthor_suggestions", use_container_width=True
        ):
            st.session_state["_show_coauthor_suggestions"] = True

    if _coauthor_counts and st.session_state.get("_show_coauthor_suggestions", False):
        _user_name = st.session_state.get("profile_name", "").strip().lower()
        _group_member_blocklist = _group_member_names()
        _already_tracked = {
            colleague.get("name", "").strip().lower()
            for colleague in st.session_state.colleagues_people
        } | {author.strip().lower() for author in st.session_state.research_authors}
        _candidates = [
            (name, count)
            for name, count in sorted(
                _coauthor_counts.items(), key=lambda item: (-item[1], item[0].lower())
            )[:20]
            if name.strip()
            and count >= 2
            and name.strip().lower() not in _already_tracked
            and name.strip().lower() != _user_name
            and name.strip().lower() not in _group_member_blocklist
        ]

        if _candidates:
            st.markdown("**Co-authors from your publications**")
            st.caption("Click to add them to the digest.")
            for coauthor_name, coauthor_count in _candidates[:10]:
                count_label = "paper" if coauthor_count == 1 else "papers"
                col_name, col_count, col_btn = st.columns([4, 2, 2])
                with col_name:
                    st.markdown(f"**{coauthor_name}**")
                with col_count:
                    st.caption(f"{coauthor_count} shared {count_label}")
                with col_btn:
                    if st.button(
                        "+ Add",
                        key=f"suggest_coll_{coauthor_name}",
                        use_container_width=True,
                    ):
                        parts = coauthor_name.split()
                        match_pattern = (
                            f"{parts[-1]}, {parts[0][0]}"
                            if len(parts) >= 2
                            else coauthor_name
                        )
                        st.session_state.colleagues_people.append(
                            {"name": coauthor_name, "match": [match_pattern]}
                        )
                        st.rerun()

    st.caption(
        "Everyone you add gets their own section in the digest, even if their papers are off-topic for you."
    )

    with st.expander("Advanced: colleague vs. research author"):
        st.markdown(
            "By default, everyone is a colleague (always shown). Reclassify as research author to give a scoring boost instead — they may be filtered if too off-topic."
        )

        if st.session_state.colleagues_people:
            st.markdown("**Currently colleagues**")
            for idx, colleague in enumerate(st.session_state.colleagues_people):
                col1, col2, col3 = st.columns([3, 2, 2])
                with col1:
                    st.markdown(f"**{colleague['name']}**")
                with col2:
                    st.caption(f"`{', '.join(colleague.get('match', []))}`")
                with col3:
                    if st.button(
                        "Make research author",
                        key=f"move_to_author_{idx}",
                        use_container_width=True,
                    ):
                        if colleague["name"] not in st.session_state.research_authors:
                            st.session_state.research_authors.append(colleague["name"])
                        st.session_state.colleagues_people.pop(idx)
                        st.rerun()

        if st.session_state.research_authors:
            st.markdown("**Currently research authors**")
            for author in list(st.session_state.research_authors):
                col1, col2 = st.columns([4, 2])
                with col1:
                    st.markdown(f"**{author}**")
                with col2:
                    if st.button(
                        "Move to colleagues",
                        key=f"move_to_colleague_{author}",
                        use_container_width=True,
                    ):
                        st.session_state.research_authors = [
                            existing
                            for existing in st.session_state.research_authors
                            if existing != author
                        ]
                        if not any(
                            colleague.get("name", "").strip().lower()
                            == author.strip().lower()
                            for colleague in st.session_state.colleagues_people
                        ):
                            parts = author.split()
                            match_pattern = (
                                f"{parts[-1]}, {parts[0][0]}"
                                if len(parts) >= 2
                                else author
                            )
                            st.session_state.colleagues_people.append(
                                {"name": author, "match": [match_pattern]}
                            )
                        st.rerun()

        st.markdown("**Institutions** (match against abstract text):")
        new_inst = st.text_input(
            "Add institution", placeholder="Aarhus University", key="new_inst_input"
        )
        if st.button("Add institution", key="add_institution_btn") and new_inst.strip():
            if new_inst.strip() not in st.session_state.colleagues_institutions:
                st.session_state.colleagues_institutions.append(new_inst.strip())
                st.rerun()

        if st.session_state.colleagues_institutions:
            to_remove = []
            for inst in st.session_state.colleagues_institutions:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"- {inst}")
                with col2:
                    if st.button("✕", key=f"rm_inst_{inst}"):
                        to_remove.append(inst)
            for inst in to_remove:
                st.session_state.colleagues_institutions.remove(inst)
            if to_remove:
                st.rerun()

    if st.button(
        "Looks good — continue to Step 4 →", key="s3_continue", type="primary"
    ):
        st.session_state.current_step = 4
        st.rerun()


# ─────────────────────────────────────────────────────────────
#  Step 4: Delivery & Download
# ─────────────────────────────────────────────────────────────

if st.session_state.current_step >= 4:
    st.markdown(
        '<p><span class="step-number">4</span> <strong>Delivery & Download</strong></p>',
        unsafe_allow_html=True,
    )
    st.markdown("How your digest is delivered. Most people can just download here.")

    digest_mode = st.session_state.get("_s8_digest_mode", "highlights")
    schedule = st.session_state.get("_s8_schedule", "mon_wed_fri")
    if schedule == "daily":
        schedule = "weekdays"

    schedule_options = {
        "mon_wed_fri": "Mon / Wed / Fri",
        "weekdays": "Every weekday",
        "weekly": "Weekly (Monday)",
    }
    schedule_summary = {
        "mon_wed_fri": "Mon, Wed, Fri",
        "weekdays": "every weekday",
        "weekly": "Monday",
    }

    st.markdown("**Schedule**")
    schedule_col, change_col = st.columns([5, 1])
    schedule_summary_slot = schedule_col.empty()
    with schedule_col:
        pass
    with change_col:
        if st.button("Change →", key="toggle_schedule_picker", use_container_width=True):
            st.session_state["_show_schedule_picker"] = not st.session_state.get(
                "_show_schedule_picker", False
            )

    if st.session_state.get("_show_schedule_picker", False):
        schedule = st.radio(
            "Frequency",
            options=list(schedule_options.keys()),
            index=list(schedule_options.keys()).index(schedule),
            format_func=lambda value: {
                "mon_wed_fri": "Mon / Wed / Fri — Best balance",
                "weekdays": "Every weekday — Never miss a day",
                "weekly": "Weekly — Monday round-up",
            }[value],
            label_visibility="collapsed",
        )

    schedule_summary_slot.markdown(
        f"Your digest arrives **{schedule_summary.get(schedule, schedule)}**."
    )

    st.markdown("**Digest size**")
    digest_mode = st.radio(
        "Digest mode",
        options=["highlights", "in_depth"],
        index=0 if digest_mode == "highlights" else 1,
        format_func=lambda value: {
            "highlights": "Highlights — Top papers only (up to 6). For busy people.",
            "in_depth": "In-depth — Wider net (up to 15). For browsers.",
        }[value],
        label_visibility="collapsed",
    )

    with st.expander("Customize card layout"):
        current_view = st.session_state.get("_s8_recipient_view_mode", "deep_read")
        recipient_view_mode = st.radio(
            "Card layout",
            options=["deep_read", "5_min_skim"],
            index=0 if current_view == "deep_read" else 1,
            format_func=lambda value: {
                "deep_read": "Deep read — full cards with expanded context",
                "5_min_skim": "Skim — top 3 papers, one-line summaries",
            }[value],
            label_visibility="collapsed",
        )
        st.caption("Card element reordering is not configurable in this build.")

    with st.expander("Self-hosting options"):
        st.caption(
            "Only relevant if you're running your own email. Most users can skip this."
        )

        smtp_options = {
            "Gmail": ("smtp.gmail.com", 587),
            "Outlook / Office 365": ("smtp.office365.com", 587),
        }
        current_smtp_server = st.session_state.get("_s9_smtp_server", "smtp.gmail.com")
        current_smtp_choice = (
            "Outlook / Office 365"
            if current_smtp_server == "smtp.office365.com"
            else "Gmail"
        )
        smtp_choice = st.radio(
            "SMTP provider",
            options=list(smtp_options.keys()),
            index=list(smtp_options.keys()).index(current_smtp_choice),
            horizontal=True,
            label_visibility="collapsed",
        )
        smtp_server, smtp_port = smtp_options[smtp_choice]

        send_hour_utc = st.slider(
            "Send hour (UTC)",
            min_value=0,
            max_value=23,
            value=int(st.session_state.get("_s8_send_hour_utc", 7)),
            help="Default is 7 UTC = 9am Danish time (CET). Adjust for your timezone.",
        )

        tz_examples = []
        cet = (send_hour_utc + 1) % 24
        cest = (send_hour_utc + 2) % 24
        est = (send_hour_utc - 5) % 24
        pst = (send_hour_utc - 8) % 24
        tz_examples = [
            f"CET: {cet}:00",
            f"CEST: {cest}:00",
            f"EST: {est}:00",
            f"PST: {pst}:00",
        ]
        st.caption(" · ".join(tz_examples))

        mode_defaults = {"highlights": (6, 5), "in_depth": (15, 2)}
        default_max, default_min = mode_defaults[digest_mode]
        max_papers = st.number_input(
            "Max papers per digest",
            min_value=1,
            max_value=30,
            value=int(
                st.session_state.get("_s8_max_papers", default_max)
                if st.session_state.get("_s8_override_max", False)
                else default_max
            ),
            key=f"max_papers_input_{digest_mode}",
        )
        min_score = st.number_input(
            "Min relevance score (1-10)",
            min_value=1,
            max_value=10,
            value=int(
                st.session_state.get("_s8_min_score", default_min)
                if st.session_state.get("_s8_override_min", False)
                else default_min
            ),
            key=f"min_score_input_{digest_mode}",
        )
        override_max = max_papers != default_max
        override_min = min_score != default_min

        github_repo = st.text_input(
            "GitHub repo (optional)",
            value=st.session_state.get("_s9_github_repo", ""),
            placeholder="username/arxiv-digest",
            help="Enables self-service links in emails",
        )

    if "recipient_view_mode" not in locals():
        recipient_view_mode = st.session_state.get("_s8_recipient_view_mode", "deep_read")
    if "smtp_server" not in locals():
        smtp_server = st.session_state.get("_s9_smtp_server", "smtp.gmail.com")
        smtp_port = st.session_state.get("_s9_smtp_port", 587)
        github_repo = st.session_state.get("_s9_github_repo", "")
        send_hour_utc = int(st.session_state.get("_s8_send_hour_utc", 7))
        mode_defaults = {"highlights": (6, 5), "in_depth": (15, 2)}
        default_max, default_min = mode_defaults[digest_mode]
        max_papers = int(st.session_state.get("_s8_max_papers", default_max))
        min_score = int(st.session_state.get("_s8_min_score", default_min))
        override_max = bool(st.session_state.get("_s8_override_max", False))
        override_min = bool(st.session_state.get("_s8_override_min", False))

    schedule_days_back = {"mon_wed_fri": 4, "weekdays": 2, "weekly": 7}
    cron_map = {
        "mon_wed_fri": f"0 {send_hour_utc} * * 1,3,5",
        "weekdays": f"0 {send_hour_utc} * * 1-5",
        "weekly": f"0 {send_hour_utc} * * 1",
    }
    days_back = schedule_days_back[schedule]
    cron_expr = cron_map[schedule]

    st.session_state["_s8_digest_mode"] = digest_mode
    st.session_state["_s8_schedule"] = schedule
    st.session_state["_s8_schedule_options"] = schedule_options
    st.session_state["_s8_send_hour_utc"] = send_hour_utc
    st.session_state["_s8_days_back"] = days_back
    st.session_state["_s8_cron_expr"] = cron_expr
    st.session_state["_s8_override_max"] = override_max
    st.session_state["_s8_override_min"] = override_min
    st.session_state["_s8_max_papers"] = max_papers
    st.session_state["_s8_min_score"] = min_score
    st.session_state["_s8_recipient_view_mode"] = recipient_view_mode
    st.session_state["_s9_smtp_server"] = smtp_server
    st.session_state["_s9_smtp_port"] = smtp_port
    st.session_state["_s9_github_repo"] = github_repo

    st.markdown("### Your config.yaml is ready")

    config = {
        "digest_name": digest_name or "arXiv Digest",
        "researcher_name": researcher_name
        or ("Research Group" if profile_mode == "group" else "Reader"),
        "research_context": research_context or "",
        "categories": categories
        if categories
        else [
            "astro-ph.EP",
            "astro-ph.SR",
            "astro-ph.GA",
            "astro-ph.HE",
            "astro-ph.IM",
        ],
        "keywords": dict(st.session_state.keywords)
        if st.session_state.keywords
        else {"example keyword": 5},
        "self_match": list(st.session_state.self_match),
        "research_authors": list(st.session_state.research_authors),
        "colleagues": {
            "people": list(st.session_state.colleagues_people),
            "institutions": list(st.session_state.colleagues_institutions),
        },
        "digest_mode": digest_mode,
        "recipient_view_mode": recipient_view_mode,
        "days_back": days_back,
        "schedule": schedule,
        "send_hour_utc": send_hour_utc,
        "institution": institution or "",
        "department": department or "",
        "tagline": tagline or "",
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "github_repo": github_repo or "",
    }

    if override_max:
        config["max_papers"] = max_papers
    if override_min:
        config["min_score"] = min_score
    if profile_mode == "group" and st.session_state.get("group_orcid_members"):
        config["group_members"] = [
            {
                "name": member.get("name", ""),
                "institution": member.get("institution", ""),
                "orcid_url": member.get("orcid_url", ""),
            }
            for member in st.session_state.group_orcid_members
        ]

    config_yaml = yaml.dump(
        config, default_flow_style=False, sort_keys=False, allow_unicode=True
    )

    tab1, tab2 = st.tabs(["config.yaml", "Workflow cron"])
    with tab1:
        st.code(config_yaml, language="yaml")

    with tab2:
        st.markdown(
            "If you change the schedule from the default (Mon/Wed/Fri 7am UTC), update this line in `.github/workflows/digest.yml`:"
        )
        st.code(
            f"    - cron: '{cron_expr}'  # {schedule_options.get(schedule, schedule)} at {send_hour_utc}:00 UTC",
            language="yaml",
        )
        if schedule != "mon_wed_fri" or send_hour_utc != 7:
            st.warning(
                "Your schedule differs from the default. Remember to update the cron line in your workflow file after forking!"
            )

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📥 Download config.yaml",
            data=config_yaml,
            file_name="config.yaml",
            mime="text/yaml",
            type="primary",
            use_container_width=True,
        )
    with col2:
        if st.button("📋 Show YAML", use_container_width=True):
            st.code(config_yaml, language="yaml")
            st.info("Select all text above and copy with Ctrl+C (Cmd+C on Mac)")

digest_mode = st.session_state.get("_s8_digest_mode", "highlights")
schedule = st.session_state.get("_s8_schedule", "mon_wed_fri")
if schedule == "daily":
    schedule = "weekdays"
schedule_options = st.session_state.get(
    "_s8_schedule_options",
    {
        "mon_wed_fri": "Mon / Wed / Fri",
        "weekdays": "Every weekday",
        "weekly": "Weekly (Monday)",
    },
)
if "daily" in schedule_options and "weekdays" not in schedule_options:
    schedule_options = {
        ("weekdays" if key == "daily" else key): value
        for key, value in schedule_options.items()
    }
send_hour_utc = st.session_state.get("_s8_send_hour_utc", 7)
days_back = st.session_state.get(
    "_s8_days_back", {"mon_wed_fri": 4, "weekdays": 2, "weekly": 7}[schedule]
)
cron_expr = st.session_state.get(
    "_s8_cron_expr",
    {
        "mon_wed_fri": f"0 {send_hour_utc} * * 1,3,5",
        "weekdays": f"0 {send_hour_utc} * * 1-5",
        "weekly": f"0 {send_hour_utc} * * 1",
    }[schedule],
)
override_max = st.session_state.get("_s8_override_max", False)
override_min = st.session_state.get("_s8_override_min", False)
_def_max, _def_min = {"highlights": (6, 5), "in_depth": (15, 2)}.get(
    digest_mode, (6, 5)
)
max_papers = st.session_state.get("_s8_max_papers", _def_max)
min_score_val = st.session_state.get("_s8_min_score", _def_min)
recipient_view_mode = st.session_state.get("_s8_recipient_view_mode", "deep_read")
smtp_server = st.session_state.get("_s9_smtp_server", "smtp.gmail.com")
smtp_port = st.session_state.get("_s9_smtp_port", 587)
github_repo = st.session_state.get("_s9_github_repo", "")


# ─────────────────────────────────────────────────────────────
#  Next Steps (always visible — outside accordion)
# ─────────────────────────────────────────────────────────────

st.divider()

st.markdown("## Next Steps")

# Custom schedule note
schedule_note = ""
if schedule != "mon_wed_fri" or send_hour_utc != 7:
    schedule_note = f"""
<div class="brand-card" style="border-left: 4px solid {GOLD};">
<p>⚠️ <strong>Update your schedule</strong></p>
<p style="margin-left: 36px;">
Since you chose <strong>{schedule_options.get(schedule, schedule)} at {send_hour_utc}:00 UTC</strong>, open
<code>.github/workflows/digest.yml</code> in your fork and change the cron line to:<br>
<code>- cron: '{cron_expr}'</code>
</p>
</div>
"""

st.markdown(
    f"""
<div class="brand-card">
<p><span class="step-number">1</span> <strong>Fork the template repo</strong></p>
<p style="margin-left: 36px;">
Go to <a href="https://github.com/SilkeDainese/arxiv-digest" style="color: {PINE};">github.com/SilkeDainese/arxiv-digest</a>
and click <strong>Fork</strong>.
</p>
</div>

<div class="brand-card">
<p><span class="step-number">2</span> <strong>Upload your config.yaml</strong></p>
<p style="margin-left: 36px;">
In your fork, click <strong>Add file → Upload files</strong> and upload the <code>config.yaml</code>
you just downloaded. It will replace the example config.
</p>
</div>

<div class="brand-card">
<p><span class="step-number">3</span> <strong>Add secrets to your fork</strong></p>
<p style="margin-left: 36px;">
Go to your fork's <strong>Settings → Secrets and variables → Actions</strong> and add the secrets shown below.
</p>
</div>

{schedule_note}
""",
    unsafe_allow_html=True,
)

_server_gemini = _has_server_key()
_invite_bundle = st.session_state.get("_invite_bundle", {})

st.markdown(
    "**Add these secrets to your fork** (Settings → Secrets and variables → Actions):"
)
if _invite_bundle:
    st.markdown("**Easy mode — your invite code unlocked shared secrets**")
    _shared_secret_lines = [
        "RECIPIENT_EMAIL    = your-email@example.com  ← or alice@example.com, bob@example.com"
    ]
    if _invite_bundle.get("relay_token"):
        _shared_secret_lines.append(
            f"DIGEST_RELAY_TOKEN = {_invite_bundle['relay_token']}"
        )
    if _invite_bundle.get("gemini_api_key"):
        _shared_secret_lines.append(
            f"GEMINI_API_KEY    = {_invite_bundle['gemini_api_key']}"
        )
    if _invite_bundle.get("anthropic_api_key"):
        _shared_secret_lines.append(
            f"ANTHROPIC_API_KEY = {_invite_bundle['anthropic_api_key']}"
        )
    st.code("\n".join(_shared_secret_lines), language="ini")
    st.caption(
        "Paste these into your fork's GitHub Actions secrets. Do not commit them to the repo."
    )
else:
    st.markdown("**Option A — maintainer-managed relay**")
    st.code(
        "RECIPIENT_EMAIL    = your-email@example.com  ← or alice@example.com, bob@example.com\n"
        "DIGEST_RELAY_TOKEN = paste-token-here        ← only if the maintainer gave you one",
        language="ini",
    )
    st.caption("Use this option only if you were given a private relay token.")

    st.markdown("**Option B — send from your own mailbox**")
    st.code(
        "RECIPIENT_EMAIL = your-email@example.com  ← or alice@example.com, bob@example.com\n"
        "SMTP_USER       = your-gmail@gmail.com\n"
        "SMTP_PASSWORD   = your-app-password  ← Gmail App Password, not your login password",
        language="ini",
    )
    st.caption(
        "Gmail app password: Google Account → Security → 2-Step Verification → "
        "[App passwords](https://myaccount.google.com/apppasswords)"
    )

    if not _server_gemini:
        st.markdown("**Optional AI key for better scoring**")
        st.code(
            "GEMINI_API_KEY    = AIza...      ← free at aistudio.google.com\n"
            "ANTHROPIC_API_KEY = sk-ant-...   ← optional alternative",
            language="ini",
        )

st.success(
    f"That's it! Your digest will run {schedule_options.get(schedule, schedule).lower()} at {send_hour_utc}:00 UTC. 🎉"
)

st.divider()

# ── Footer ──
st.markdown(
    f"""
<div style="text-align: center; font-family: 'DM Mono', monospace; font-size: 10px;
     letter-spacing: 0.1em; color: {WARM_GREY}; margin-top: 24px; margin-bottom: 24px;">
     Built by <a href="https://silkedainese.github.io" style="color: {PINE};">Silke S. Dainese</a> ·
     <a href="mailto:dainese@phys.au.dk" style="color: {WARM_GREY};">dainese@phys.au.dk</a> ·
     <a href="https://github.com/SilkeDainese" style="color: {WARM_GREY};">GitHub</a>
</div>
""",
    unsafe_allow_html=True,
)
