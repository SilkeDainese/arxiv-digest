"""
Pure Profile Scraper — extracts keywords and co-authors from a Pure research portal.
Designed for AU Pure (pure.au.dk) but works with most Pure instances.
Fault-tolerant: Pure page structures vary by institution.
"""

import re
from collections import Counter

import requests
from bs4 import BeautifulSoup

# Common stopwords to exclude from keyword extraction
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


def search_pure_profiles(name, base_url="https://pure.au.dk"):
    """
    Search a Pure portal for researcher profiles by name.

    Args:
        name: researcher name to search for (e.g. "Silke Dainese")
        base_url: Pure portal base URL (default: AU Pure)

    Returns:
        list of dicts with keys: name, url, department (may be empty).
        Returns empty list on failure.
    """
    search_url = f"{base_url}/portal/en/searchAll.html"
    params = {"search": name, "uri": "", "pageSize": 10, "type": "/dk/atira/pure/person/Person"}
    headers = {"User-Agent": "arxiv-digest-setup/1.0"}

    try:
        resp = requests.get(search_url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception:
        # Try alternate Pure search URL pattern
        try:
            alt_url = f"{base_url}/en/persons/?search={requests.utils.quote(name)}"
            resp = requests.get(alt_url, headers=headers, timeout=15)
            resp.raise_for_status()
        except Exception:
            return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # Try multiple selectors for search results (Pure layouts vary)
    for selector in [
        ".result-container",
        ".portal_list_item",
        ".list-results .result",
        ".search-result",
    ]:
        containers = soup.select(selector)
        if containers:
            for c in containers:
                # Find the person name + link
                link = c.select_one("h3 a, h2 a, .title a, a.link.person")
                if not link:
                    continue
                person_name = link.get_text(strip=True)
                href = link.get("href", "")
                if not href:
                    continue
                # Make absolute URL
                if href.startswith("/"):
                    href = base_url + href
                elif not href.startswith("http"):
                    href = base_url + "/" + href

                # Try to find department/affiliation
                dept_el = c.select_one(".department, .organisation, .affiliation, .dimmed")
                dept = dept_el.get_text(strip=True) if dept_el else ""

                results.append({
                    "name": person_name,
                    "url": href,
                    "department": dept,
                })
            break

    # Fallback: look for person links in the page
    if not results:
        for link in soup.select("a[href*='/persons/']"):
            person_name = link.get_text(strip=True)
            href = link.get("href", "")
            if person_name and len(person_name) > 3 and href and "/persons/" in href:
                if href.startswith("/"):
                    href = base_url + href
                results.append({"name": person_name, "url": href, "department": ""})

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    return unique[:10]


def scrape_pure_profile(url):
    """
    Scrape a Pure profile page to extract publication keywords and co-authors.

    Args:
        url: Pure profile URL (e.g. https://pure.au.dk/portal/en/persons/silke-dainese)

    Returns:
        (keywords_dict, coauthors_list, error) where keywords_dict maps keyword→weight (1-10),
        coauthors_list is a list of author name strings, and error is None on success
        or an error message string on failure. Returns (None, None, error_str) on failure.
    """
    try:
        headers = {"User-Agent": "arxiv-digest-setup/1.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return None, None, str(e)

    soup = BeautifulSoup(resp.text, "html.parser")

    # ── Extract publication titles ──
    titles = []
    # Try multiple selectors (Pure layouts vary by institution)
    for selector in [
        "h3.title a",           # Common Pure layout
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

    # Fallback: look for any h3 inside result containers
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
        return None, None, "Could not find publication titles on this page. The page structure may differ from expected Pure formats."

    # ── Extract keywords from titles ──
    word_counts = Counter()
    bigram_counts = Counter()

    for title in titles:
        words = re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", title.lower())
        words = [w for w in words if w not in STOPWORDS and len(w) > 2]
        word_counts.update(words)

        # Bigrams (two-word phrases often make better keywords)
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            bigram_counts.update([bigram])

    # Combine: prefer bigrams that appear 2+ times, then single words
    combined = Counter()
    for bigram, count in bigram_counts.items():
        if count >= 2:
            combined[bigram] = count * 2  # Boost bigrams
    for word, count in word_counts.items():
        if count >= 2 and not any(word in bg for bg in combined):
            combined[word] = count

    if not combined:
        combined = word_counts  # Fall back to single words

    # Normalize to 1-10 scale
    if combined:
        max_count = max(combined.values())
        keywords = {}
        for term, count in combined.most_common(20):
            weight = max(1, round(10 * count / max_count))
            keywords[term] = weight
    else:
        keywords = {}

    # ── Extract co-authors ──
    coauthors = set()
    # Navigation / non-person link text to filter out
    NAV_WORDS = {
        "home", "search", "contact", "about", "publications", "projects",
        "activities", "research", "profile", "overview", "back", "next",
        "previous", "more", "show all", "view all", "see all", "login",
        "log in", "sign in", "menu", "navigate", "skip", "department",
    }
    # Try multiple selectors for author lists
    for selector in [
        ".person-list a",
        ".result-container .persons a",
        ".portal_list_item .authors a",
        ".rendering span.person a",
        "a[rel='Person']",
    ]:
        found = soup.select(selector)
        if found:
            for el in found:
                name = el.get_text(strip=True)
                if not name or len(name) < 4:
                    continue
                # Filter out navigation links: must contain a space (first + last name)
                # and must not match known navigation words
                if " " not in name:
                    continue
                if name.lower() in NAV_WORDS:
                    continue
                coauthors.add(name)
            break

    # Remove the profile owner (they appear in their own papers)
    # Try to find profile owner name
    owner_name = None
    for selector in ["h1", ".profile-name", ".person-name", "h2.name"]:
        el = soup.select_one(selector)
        if el:
            owner_name = el.get_text(strip=True)
            break

    if owner_name:
        coauthors.discard(owner_name)

    return keywords, sorted(coauthors), None
