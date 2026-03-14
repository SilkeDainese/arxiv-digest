"""
Profile Scraper — extracts keywords and co-authors for the arXiv Digest setup wizard.

Search: uses the ORCID public API (free, no authentication required) to find researchers
by name. Returns name, ORCID URL, and department (affiliation).

Primary extract path: fetch_orcid_works() — hits the ORCID /works API to get publication
titles and derive keywords. No authentication, no Cloudflare issues, works for any
ORCID-registered researcher.

Fallback extract path: scrape_pure_profile() — scrapes Pure portal HTML (AU Pure and
compatible instances). Requires a browser-like User-Agent. Many researchers do not have
a Pure page, and pure.au.dk search is Cloudflare-blocked, so Pure is relegated to
optional manual fallback.

All functions are fault-tolerant and return empty results on failure rather than raising.
"""

from __future__ import annotations

import re
from collections import Counter

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────────────

# Browser-like User-Agent required by Cloudflare-protected Pure portals.
# The generic library UA ("arxiv-digest-setup/1.0") triggers 403 on pure.au.dk.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_ORCID_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "arxiv-digest-setup/1.0 (https://github.com/SilkeDainese/arxiv-silke)",
}

# Words to exclude from keyword extraction
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "must",
    "that", "which", "who", "whom", "this", "these", "those", "it", "its",
    "their", "our", "your", "my", "we", "they", "he", "she", "i", "me",
    "him", "her", "us", "them", "not", "no", "nor", "so", "if", "then",
    "than", "too", "very", "just", "about", "above", "after", "again",
    "all", "also", "any", "because", "before", "between", "both", "each",
    "few", "more", "most", "other", "over", "same", "some", "such",
    "through", "under", "until", "up", "what", "when", "where", "while",
    "how", "here", "there", "into", "during", "only", "own", "new",
    "using", "based", "via", "non", "two", "three", "first", "one",
    "well", "however", "high", "low", "large", "small", "study",
    "results", "show", "find", "found", "use", "used", "model", "data",
    "analysis", "method", "methods", "effect", "effects", "properties",
    "measurements", "observations", "paper", "work", "present",
}


# ─────────────────────────────────────────────────────────────
#  Profile Search (ORCID)
# ─────────────────────────────────────────────────────────────

def search_pure_profiles(name: str, institution: str = "", base_url: str = "https://pure.au.dk") -> list[dict]:
    """
    Search for researcher profiles by name using the ORCID public API.

    The Pure portal search endpoint (pure.au.dk/portal/en/searchAll.html) is
    protected by Cloudflare and returns 403 to automated requests. The ORCID
    public API is free, requires no authentication, and is the reliable alternative.

    The `base_url` parameter is accepted for interface compatibility but is not
    used — ORCID search is institution-agnostic.

    Args:
        name: researcher name to search for (e.g. "Silke Dainese")
        base_url: ignored (kept for backward-compatible interface)

    Returns:
        list of dicts with keys: name, url, department.
        url points to the ORCID profile page.
        Returns empty list on any failure.
    """
    if not name or not name.strip():
        return []

    # ── Parse given/family names for a more precise ORCID query ──
    # Use first word as given name and last word as family name so that middle
    # names (e.g. "Silke Sofia Dainese") don't pollute the family-name field.
    parts = name.strip().split()
    if len(parts) >= 2:
        given = parts[0]
        family = parts[-1]
        query = f"given-names:{given} AND family-name:{family}"
    else:
        query = name.strip()

    if institution and institution.strip():
        query += f' AND affiliation-org-name:"{institution.strip()}"'

    def _orcid_search(q: str) -> list:
        try:
            resp = requests.get(
                "https://pub.orcid.org/v3.0/search",
                params={"q": q, "rows": 10},
                headers=_ORCID_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            return [
                r.get("orcid-identifier", {}).get("path", "")
                for r in resp.json().get("result", [])
                if r.get("orcid-identifier", {}).get("path")
            ]
        except Exception:
            return []

    orcid_ids = _orcid_search(query)
    # Broader fallback: drop institution constraint first, then try family name only
    if not orcid_ids and institution and len(parts) >= 2:
        orcid_ids = _orcid_search(f"given-names:{given} AND family-name:{family}")
    if not orcid_ids and len(parts) >= 2:
        orcid_ids = _orcid_search(f"family-name:{family}")

    results = []
    for orcid_id in orcid_ids[:10]:
        try:
            person_resp = requests.get(
                f"https://pub.orcid.org/v3.0/{orcid_id}/person",
                headers=_ORCID_HEADERS,
                timeout=10,
            )
            if person_resp.status_code != 200:
                continue
            person = person_resp.json()

            name_info = person.get("name", {}) or {}
            given_val = (name_info.get("given-names") or {}).get("value", "")
            family_val = (name_info.get("family-name") or {}).get("value", "")
            full_name = f"{given_val} {family_val}".strip()
            if not full_name:
                continue

            # Affiliation from employment summary
            affiliations_resp = requests.get(
                f"https://pub.orcid.org/v3.0/{orcid_id}/employments",
                headers=_ORCID_HEADERS,
                timeout=10,
            )
            dept = ""
            if affiliations_resp.status_code == 200:
                aff_groups = affiliations_resp.json().get("affiliation-group", [])
                if aff_groups:
                    summaries = aff_groups[0].get("summaries", [])
                    if summaries:
                        emp = summaries[0].get("employment-summary", {})
                        org = emp.get("organization", {}) or {}
                        dept = org.get("name", "")

            results.append({
                "name": full_name,
                "url": f"https://orcid.org/{orcid_id}",
                "department": dept,
            })
        except Exception:
            continue

    return results


# ─────────────────────────────────────────────────────────────
#  Profile Scrape (Pure portal HTML)
# ─────────────────────────────────────────────────────────────

def scrape_pure_profile(url: str) -> tuple[dict | None, list | None, str | None]:
    """
    Scrape a Pure profile page to extract publication keywords and co-authors.

    Works with AU Pure (pure.au.dk) and most compatible Pure instances.
    Uses a browser-like User-Agent to pass Cloudflare protection on the profile page.

    Note: this function scrapes the Pure HTML portal, not ORCID. The user must
    supply a direct Pure profile URL (e.g. from the search results or pasted manually).
    ORCID profile URLs (orcid.org) are not scraped here.

    Args:
        url: Pure profile URL

    Returns:
        (keywords_dict, coauthors_list, error) where keywords_dict maps keyword to
        weight (1-10), coauthors_list is a list of author name strings, and error is
        None on success or an error message string on failure.
        Returns (None, None, error_str) on failure.
    """
    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return None, None, str(e)

    soup = BeautifulSoup(resp.text, "html.parser")

    # ── Extract publication titles ──
    titles = []
    for selector in [
        "h3.title a",
        ".result-container h3 a",
        ".portal_list_item h2 a",
        ".rendering_contributiontojournal h3 a",
        ".rendering h3 a",
        "h2.dc_title a",
        ".list-results h3 a",
    ]:
        found = soup.select(selector)
        if found:
            titles = [el.get_text(strip=True) for el in found]
            break

    # Fallback: any h2/h3 inside result containers
    if not titles:
        for container_class in ["result-container", "portal_list_item", "list-results"]:
            containers = soup.find_all(class_=container_class)
            if containers:
                for c in containers:
                    h = c.find(["h2", "h3"])
                    if h:
                        titles.append(h.get_text(strip=True))
                break

    if not titles:
        return None, None, (
            "Could not find publication titles on this page. "
            "The page structure may differ from expected Pure formats, or the page "
            "may be Cloudflare-protected and not returning full content."
        )

    # ── Extract keywords from titles ──
    word_counts: Counter[str] = Counter()
    bigram_counts: Counter[str] = Counter()

    for title in titles:
        words = re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", title.lower())
        words = [w for w in words if w not in STOPWORDS and len(w) > 2]
        word_counts.update(words)
        for i in range(len(words) - 1):
            bigram_counts.update([f"{words[i]} {words[i+1]}"])

    # Prefer bigrams that appear 2+ times, then single words
    combined: Counter[str] = Counter()
    for bigram, count in bigram_counts.items():
        if count >= 2:
            combined[bigram] = count * 2
    for word, count in word_counts.items():
        if count >= 2 and not any(word in bg for bg in combined):
            combined[word] = count

    if not combined:
        combined = word_counts

    keywords: dict[str, int] = {}
    if combined:
        max_count = max(combined.values())
        for term, count in combined.most_common(20):
            keywords[term] = max(1, round(10 * count / max_count))

    # ── Extract co-authors ──
    coauthors: set[str] = set()
    NAV_WORDS = {
        "home", "search", "contact", "about", "publications", "projects",
        "activities", "research", "profile", "overview", "back", "next",
        "previous", "more", "show all", "view all", "see all", "login",
        "log in", "sign in", "menu", "navigate", "skip", "department",
    }
    for selector in [
        "a[rel='Person']",
        ".person-list a",
        ".result-container .persons a",
        ".portal_list_item .authors a",
        ".rendering span.person a",
    ]:
        found = soup.select(selector)
        if found:
            for el in found:
                name = el.get_text(strip=True)
                if not name or len(name) < 4:
                    continue
                if " " not in name and "," not in name:
                    continue
                if name.lower() in NAV_WORDS:
                    continue
                coauthors.add(name)
            break

    # Remove the profile owner from the co-author list
    owner_name = None
    for selector in ["h1", ".profile-name", ".person-name", "h2.name"]:
        el = soup.select_one(selector)
        if el:
            owner_name = el.get_text(strip=True)
            break
    if owner_name:
        coauthors.discard(owner_name)

    return keywords, sorted(coauthors), None


# ─────────────────────────────────────────────────────────────
#  Publication Fetch (ORCID works API)
# ─────────────────────────────────────────────────────────────

def fetch_orcid_works(orcid_id: str) -> tuple[dict | None, list | None, str | None]:
    """
    Fetch publication titles from the ORCID public API and derive keywords.

    Hits the /works summary endpoint, which returns one entry per work group (ORCID
    deduplicates multiple sources of the same paper). Only the first summary per group
    is used — they are equivalent for title extraction purposes.

    Note: the /works summary endpoint does not reliably include full co-author lists.
    Only the work's registered contributors appear, not all paper authors. Co-author
    extraction is not attempted here; an empty list is always returned. For co-authors,
    use scrape_pure_profile() if a Pure URL is available.

    Args:
        orcid_id: bare ORCID identifier (e.g. "0000-0001-7568-6674")

    Returns:
        (keywords_dict, [], error) — keywords_dict maps keyword to weight (1-10),
        co-authors list is always empty, error is None on success or an error string.
        Returns (None, None, error_str) on failure.
    """
    try:
        resp = requests.get(
            f"https://pub.orcid.org/v3.0/{orcid_id}/works",
            headers=_ORCID_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        return None, None, str(e)

    titles: list[str] = []
    for group in resp.json().get("group", []):
        for summary in group.get("work-summary", []):
            title_obj = (summary.get("title") or {}).get("title") or {}
            title_value = title_obj.get("value", "").strip()
            if title_value:
                titles.append(title_value)
                break  # First summary per group is sufficient; ORCID deduplicates

    if not titles:
        return None, None, "No publications found on this ORCID profile."

    # Keyword extraction — same bigram-then-unigram logic as scrape_pure_profile
    word_counts: Counter[str] = Counter()
    bigram_counts: Counter[str] = Counter()

    for title in titles:
        words = re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", title.lower())
        words = [w for w in words if w not in STOPWORDS and len(w) > 2]
        word_counts.update(words)
        for i in range(len(words) - 1):
            bigram_counts.update([f"{words[i]} {words[i+1]}"])

    combined: Counter[str] = Counter()
    for bigram, count in bigram_counts.items():
        if count >= 2:
            combined[bigram] = count * 2
    for word, count in word_counts.items():
        if count >= 2 and not any(word in bg for bg in combined):
            combined[word] = count

    if not combined:
        combined = word_counts

    keywords: dict[str, int] = {}
    if combined:
        max_count = max(combined.values())
        for term, count in combined.most_common(20):
            keywords[term] = max(1, round(10 * count / max_count))

    return keywords, [], None
