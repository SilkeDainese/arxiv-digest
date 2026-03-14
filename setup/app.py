"""
arXiv Digest — Setup Wizard
A Streamlit web app that helps researchers configure their personal arXiv digest.
Generates a config.yaml (+ workflow snippet) ready to use with the arxiv-digest template.

Created by Silke S. Dainese · dainese@phys.au.dk · silkedainese.github.io
"""

import re

import yaml
import streamlit as st

from pure_scraper import scrape_pure_profile, search_pure_profiles

# ─────────────────────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="arXiv Digest Setup",
    page_icon="🔭",
    layout="centered",
)

# ── Custom CSS for brand styling ──
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=IBM+Plex+Sans:wght@300;400;600&family=DM+Mono:wght@400&display=swap');

    h1, h2, h3 { font-family: 'DM Serif Display', Georgia, serif !important; }
    .stMarkdown p, .stMarkdown li { font-family: 'IBM Plex Sans', sans-serif; }
    code, .stCode { font-family: 'DM Mono', monospace !important; }

    /* Brand card styling */
    .brand-card {
        background: white;
        border: 1px solid #D8D6D0;
        border-radius: 6px;
        padding: 24px;
        margin: 12px 0;
    }
    .brand-label {
        font-family: 'DM Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #6A6A66;
    }
    .step-number {
        display: inline-block;
        background: #2F4F3E;
        color: white;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        text-align: center;
        line-height: 28px;
        font-family: 'DM Mono', monospace;
        font-size: 14px;
        margin-right: 8px;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
#  arXiv categories + AI suggestion hints
# ─────────────────────────────────────────────────────────────

ARXIV_CATEGORIES = {
    "astro-ph.EP": "Earth and Planetary Astrophysics",
    "astro-ph.SR": "Solar and Stellar Astrophysics",
    "astro-ph.GA": "Astrophysics of Galaxies",
    "astro-ph.CO": "Cosmology and Nongalactic Astrophysics",
    "astro-ph.HE": "High Energy Astrophysical Phenomena",
    "astro-ph.IM": "Instrumentation and Methods",
    "hep-th": "High Energy Physics — Theory",
    "hep-ph": "High Energy Physics — Phenomenology",
    "hep-ex": "High Energy Physics — Experiment",
    "gr-qc": "General Relativity and Quantum Cosmology",
    "cond-mat": "Condensed Matter",
    "cond-mat.str-el": "Strongly Correlated Electrons",
    "cond-mat.mtrl-sci": "Materials Science",
    "cond-mat.stat-mech": "Statistical Mechanics",
    "quant-ph": "Quantum Physics",
    "nucl-th": "Nuclear Theory",
    "physics.optics": "Optics",
    "physics.atom-ph": "Atomic Physics",
    "physics.bio-ph": "Biological Physics",
    "physics.flu-dyn": "Fluid Dynamics",
    "physics.plasm-ph": "Plasma Physics",
    "physics.geo-ph": "Geophysics",
    "physics.comp-ph": "Computational Physics",
    "physics.data-an": "Data Analysis, Statistics and Probability",
    "cs.AI": "Artificial Intelligence",
    "cs.LG": "Machine Learning",
    "cs.CV": "Computer Vision",
    "cs.CL": "Computation and Language (NLP)",
    "cs.RO": "Robotics",
    "math.AP": "Analysis of PDEs",
    "math.AG": "Algebraic Geometry",
    "math.DG": "Differential Geometry",
    "math.PR": "Probability",
    "stat.ML": "Machine Learning (Statistics)",
    "stat.ME": "Methodology (Statistics)",
    "eess.SP": "Signal Processing",
    "q-bio": "Quantitative Biology",
}

# Terms that hint at which arXiv categories to suggest
CATEGORY_HINTS = {
    "astro-ph.EP": [
        "exoplanet", "planet formation", "transit", "radial velocity", "habitable",
        "atmosphere", "JWST", "Kepler", "TESS", "circumbinary", "hot jupiter",
        "sub-neptune", "super-earth", "protoplanetary", "protoplanetary disk",
        "planetary system", "planet formation", "transmission spectroscopy",
        "radial-velocity", "earth-like", "biosignature", "accretion disk",
    ],
    "astro-ph.SR": [
        "stellar", "stellar rotation", "binary star", "spectroscopy", "magnetic",
        "angular momentum", "obliquity", "spin-orbit", "vsini", "vbroad", "Gaia",
        "gyrochronology", "asteroseismology", "variable star", "pulsation",
        "white dwarf", "red giant", "main sequence", "chromosphere",
        "flare", "metallicity", "abundance", "spectral type", "eclipsing binary",
        "Rossiter-McLaughlin", "Doppler tomography", "Kraft break",
    ],
    "astro-ph.GA": [
        "galaxy", "galaxies", "galactic", "Milky Way", "dark matter",
        "interstellar", "ISM", "star formation", "AGN", "quasar",
        "merger", "cluster", "halo", "bulge", "spiral", "elliptical",
        "HII region", "nebula", "chemical evolution", "stellar population",
    ],
    "astro-ph.CO": [
        "cosmolog", "CMB", "dark energy", "inflation", "baryon",
        "large-scale structure", "BAO", "Hubble", "redshift", "gravitational lensing",
        "cosmic microwave", "primordial", "Big Bang", "expansion",
    ],
    "astro-ph.HE": [
        "black hole", "neutron star", "pulsar", "magnetar", "GRB",
        "gamma-ray", "X-ray", "accretion", "relativistic jet", "relativistic",
        "gravitational wave", "LIGO", "compact object", "supernova",
    ],
    "astro-ph.IM": [
        "instrument", "detector", "telescope", "survey", "pipeline",
        "calibration", "photometry", "astrometry", "spectrograph",
        "adaptive optics", "CCD", "coronagraph", "interferometry",
    ],
    "hep-th": [
        "string theory", "quantum field theory", "supersymmetry", "AdS/CFT",
        "holograph", "conformal field", "gauge theory", "brane",
    ],
    "hep-ph": [
        "particle physics", "Standard Model", "Higgs", "collider", "LHC",
        "neutrino", "dark matter candidate", "beyond Standard Model",
    ],
    "gr-qc": [
        "general relativity", "gravitational wave", "black hole", "spacetime",
        "metric", "Einstein", "curvature", "singularity", "LIGO",
    ],
    "cond-mat": [
        "condensed matter", "solid state", "lattice", "phonon", "electron",
        "superconductor", "topological", "Fermi surface", "Bose-Einstein", "crystal",
        "semiconductor", "magnetism", "spin chain", "band structure", "insulator",
    ],
    "quant-ph": [
        "quantum computing", "qubit", "entanglement", "quantum information",
        "quantum optics", "decoherence", "quantum error", "quantum algorithm",
    ],
    "physics.optics": [
        "optical", "laser", "photon", "waveguide", "fiber", "lens",
        "diffraction", "nonlinear optics", "ultrafast",
    ],
    "physics.bio-ph": [
        "biophysics", "protein", "membrane", "DNA", "RNA", "cell",
        "molecular dynamics", "biological", "enzyme",
    ],
    "physics.flu-dyn": [
        "fluid", "turbulence", "Navier-Stokes", "flow", "viscous",
        "Reynolds", "boundary layer", "vortex",
    ],
    "cs.AI": [
        "artificial intelligence", "reasoning", "planning", "knowledge",
        "agent", "reinforcement learning", "multi-agent",
    ],
    "cs.LG": [
        "machine learning", "deep learning", "neural network", "transformer",
        "GPT", "training", "gradient", "optimization", "generalization",
    ],
    "cs.CV": [
        "computer vision", "image", "object detection", "segmentation",
        "convolutional", "CNN", "visual", "recognition",
    ],
    "cs.CL": [
        "natural language", "NLP", "language model", "text", "translation",
        "sentiment", "parsing", "BERT", "tokeniz",
    ],
    "stat.ML": [
        "statistical learning", "Bayesian", "inference", "regression",
        "classification", "kernel", "non-parametric", "MCMC",
    ],
}


def suggest_categories(text):
    """Score arXiv categories by keyword overlap with research description."""
    text_lower = text.lower()
    scores = {}
    for cat, hints in CATEGORY_HINTS.items():
        score = sum(1 for h in hints if h.lower() in text_lower)
        if score > 0:
            scores[cat] = score
    # Return categories sorted by score, top 5
    return sorted(scores, key=scores.get, reverse=True)[:5]


def suggest_keywords_from_context(text):
    """Extract likely research keywords from a research description."""
    # Split into candidate phrases (2-3 word chunks that look technical)
    words = text.split()
    candidates = {}

    # Single significant words (capitalized terms, acronyms, technical terms)
    for w in words:
        clean = re.sub(r"[.,;:!?()\"']", "", w)
        if not clean or len(clean) < 3:
            continue
        # Acronyms (all caps, 2+ chars)
        if clean.isupper() and len(clean) >= 2 and clean.isalpha():
            candidates[clean] = 8
        # Capitalized terms mid-sentence (likely proper nouns / technical terms)
        elif clean[0].isupper() and not clean.isupper() and len(clean) > 3:
            candidates[clean.lower()] = 5

    # Bigrams and trigrams
    clean_words = [re.sub(r"[.,;:!?()\"']", "", w) for w in words]
    clean_words = [w for w in clean_words if w]
    stopwords = {
        "i", "my", "me", "we", "our", "the", "a", "an", "and", "or", "but",
        "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
        "is", "was", "are", "were", "been", "be", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should", "that",
        "which", "who", "this", "these", "it", "its", "their", "also",
        "using", "such", "both", "between", "about", "into", "through",
        "particularly", "specifically", "especially", "including", "focus",
        "work", "study", "research", "currently", "mainly", "primarily",
    }

    for i in range(len(clean_words) - 1):
        w1, w2 = clean_words[i].lower(), clean_words[i + 1].lower()
        if w1 not in stopwords and w2 not in stopwords and len(w1) > 2 and len(w2) > 2:
            bigram = f"{w1} {w2}"
            if bigram not in candidates:
                candidates[bigram] = 7

    for i in range(len(clean_words) - 2):
        w1, w2, w3 = clean_words[i].lower(), clean_words[i + 1].lower(), clean_words[i + 2].lower()
        if w1 not in stopwords and w2 not in stopwords and w3 not in stopwords and len(w1) > 2 and len(w3) > 2:
            trigram = f"{w1} {w2} {w3}"
            if len(trigram) > 10:  # meaningful length
                candidates[trigram] = 9

    # Filter out very generic terms
    generic = {"et al", "ground based", "non linear"}
    return {k: v for k, v in sorted(candidates.items(), key=lambda x: -x[1])[:15]
            if k.lower() not in generic}


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


# ─────────────────────────────────────────────────────────────
#  Welcome
# ─────────────────────────────────────────────────────────────

st.markdown("# 🔭 arXiv Digest Setup")
st.markdown("""
Set up your personal arXiv digest in 5 minutes. This wizard generates a `config.yaml`
that you drop into your GitHub fork — then you'll get curated papers delivered to your inbox.
""")

st.markdown("""
<div style="font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.1em;
     text-transform: uppercase; color: #6A6A66; margin-top: -8px; margin-bottom: 24px;">
     Built by <a href="https://silkedainese.github.io" style="color: #2F4F3E;">Silke S. Dainese</a>
</div>
""", unsafe_allow_html=True)

# ── AI assist toggle ──
ai_assist = st.toggle(
    "✨ AI-assisted setup",
    value=True,
    help="When on, we'll suggest arXiv categories and keywords based on your research description. Turn off to pick everything manually.",
)

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 1: Your Profile
# ─────────────────────────────────────────────────────────────

st.markdown("## 1. Your Profile")

col1, col2 = st.columns(2)
with col1:
    researcher_name = st.text_input("Your name", placeholder="Jane Smith")
    institution = st.text_input("Institution (optional)", placeholder="Aarhus University")
with col2:
    digest_name = st.text_input("Digest name", value="arXiv Digest", help="Appears in the email subject line")
    department = st.text_input("Department (optional)", placeholder="Dept. of Physics & Astronomy")

tagline = st.text_input("Footer tagline (optional)", placeholder="Ad astra per aspera", help="A quote or motto for the email footer")

# ── Self-match (your own name on arXiv) ──
st.markdown("**Your name on arXiv** — if you publish a paper, you'll get a special celebration in your digest!")
col1, col2 = st.columns([3, 1])
with col1:
    new_self = st.text_input("Author match pattern", placeholder="Smith, J", key="self_match_input", label_visibility="collapsed",
                              help="How your name appears in arXiv author lists (e.g. 'Smith, J' or 'Jane Smith')")
with col2:
    if st.button("Add", key="add_self_match", use_container_width=True):
        if new_self.strip() and new_self.strip() not in st.session_state.self_match:
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
    for p in to_remove:
        st.session_state.self_match.remove(p)
        st.rerun()

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 2: Research Context
# ─────────────────────────────────────────────────────────────

st.markdown("## 2. Your Research")

if ai_assist:
    st.markdown(
        "Describe your research in 3-5 sentences, like you'd tell a colleague. "
        "We'll use this to **suggest arXiv categories and keywords** for you."
    )
else:
    st.markdown("Describe your research in 3-5 sentences. This is what the AI uses to score papers.")

research_context = st.text_area(
    "Research context",
    height=120,
    placeholder="I study exoplanet atmospheres using transmission spectroscopy with JWST and ground-based instruments. I focus on hot Jupiters and sub-Neptunes, particularly their atmospheric composition and cloud properties.",
    label_visibility="collapsed",
)

# ── AI suggestions trigger ──
if ai_assist and research_context and len(research_context) > 30:
    if st.button("🤖 Suggest categories & keywords from my description", type="primary"):
        st.session_state.ai_suggested_cats = suggest_categories(research_context)
        st.session_state.ai_suggested_kws = suggest_keywords_from_context(research_context)

    if st.session_state.ai_suggested_cats:
        st.success(f"Suggested {len(st.session_state.ai_suggested_cats)} categories and {len(st.session_state.ai_suggested_kws)} keywords — review them below.")

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 3: Pure Profile Scan (optional)
# ─────────────────────────────────────────────────────────────

st.markdown("## 3. Pure Profile Scan (optional)")
st.markdown("We can extract keywords and co-authors from your Pure research profile.")

if "pure_search_results" not in st.session_state:
    st.session_state.pure_search_results = []
if "pure_confirmed_url" not in st.session_state:
    st.session_state.pure_confirmed_url = ""

if ai_assist:
    # ── AI mode: search by name ──
    st.markdown("**Just type your name** — we'll find your profile.")
    col1, col2 = st.columns([3, 1])
    with col1:
        pure_search_name = st.text_input(
            "Your name",
            value=researcher_name or "",
            placeholder="Jane Smith",
            key="pure_search_name",
            label_visibility="collapsed",
        )
    with col2:
        pure_base = st.text_input(
            "Pure portal",
            value="https://pure.au.dk",
            help="Change if your institution uses a different Pure URL",
            key="pure_base_url",
            label_visibility="collapsed",
        )

    if pure_search_name and st.button("🔍 Search Pure", type="primary"):
        with st.spinner(f"Searching for '{pure_search_name}'..."):
            st.session_state.pure_search_results = search_pure_profiles(pure_search_name, pure_base)
            st.session_state.pure_confirmed_url = ""

        if not st.session_state.pure_search_results:
            st.warning("No profiles found. Try a different spelling, or paste your Pure URL directly below.")

    # Show search results as selectable options
    if st.session_state.pure_search_results:
        st.markdown("**Is this you?** Click to confirm:")
        for i, result in enumerate(st.session_state.pure_search_results):
            dept_label = f" — {result['department']}" if result['department'] else ""
            if st.button(
                f"✅ {result['name']}{dept_label}",
                key=f"confirm_pure_{i}",
                help=result['url'],
                use_container_width=True,
            ):
                st.session_state.pure_confirmed_url = result["url"]
                st.rerun()

        st.caption("Not in the list? Paste your Pure URL directly below.")

    # Fallback: manual URL entry
    with st.expander("Or paste your Pure URL directly"):
        pure_url_manual = st.text_input(
            "Pure profile URL",
            placeholder="https://pure.au.dk/portal/en/persons/your-name",
            key="pure_url_manual",
        )
        if pure_url_manual:
            st.session_state.pure_confirmed_url = pure_url_manual

else:
    # ── Manual mode: just URL ──
    pure_url_direct = st.text_input(
        "Pure profile URL (optional)",
        placeholder="https://pure.au.dk/portal/en/persons/your-name",
        help="Works with most Pure research portal instances",
        key="pure_url_direct",
    )
    if pure_url_direct:
        st.session_state.pure_confirmed_url = pure_url_direct

# ── Scan the confirmed profile ──
if st.session_state.pure_confirmed_url and not st.session_state.pure_scanned:
    st.info(f"Profile: `{st.session_state.pure_confirmed_url}`")
    if st.button("📥 Extract keywords & co-authors", type="primary"):
        with st.spinner("Scanning profile..."):
            keywords, coauthors, error = scrape_pure_profile(st.session_state.pure_confirmed_url)

        if error:
            st.error(f"Could not scan profile: {error}")
            st.info("No worries — you can add keywords manually below.")
        else:
            st.session_state.pure_scanned = True
            if keywords:
                merged = dict(st.session_state.keywords)
                merged.update(keywords)
                st.session_state.keywords = merged
                st.success(f"Found {len(keywords)} keywords from your publications!")
            if coauthors:
                for name in coauthors[:15]:
                    parts = name.split()
                    if len(parts) >= 2:
                        match_pattern = f"{parts[-1]}, {parts[0][0]}"
                        if not any(c["name"] == name for c in st.session_state.colleagues_people):
                            st.session_state.colleagues_people.append({
                                "name": name,
                                "match": [match_pattern],
                            })
                st.success(f"Found {len(coauthors)} co-authors!")
            st.rerun()

elif st.session_state.pure_scanned:
    st.success(f"✅ Profile scanned: {st.session_state.pure_confirmed_url}")

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 4: arXiv Categories
# ─────────────────────────────────────────────────────────────

st.markdown("## 4. arXiv Categories")

category_options = [f"{k} — {v}" for k, v in ARXIV_CATEGORIES.items()]

if ai_assist and st.session_state.ai_suggested_cats:
    st.markdown("**Suggested based on your research description** — edit as needed:")
    # Pre-select the AI-suggested categories
    suggested_defaults = [
        f"{cat} — {ARXIV_CATEGORIES[cat]}"
        for cat in st.session_state.ai_suggested_cats
        if cat in ARXIV_CATEGORIES
    ]
    selected_cats = st.multiselect(
        "Categories",
        options=category_options,
        default=suggested_defaults,
        label_visibility="collapsed",
    )
else:
    st.markdown("Which arXiv categories should the digest monitor? Pick the ones relevant to your field.")
    selected_cats = st.multiselect(
        "Categories",
        options=category_options,
        default=[],
        label_visibility="collapsed",
    )

categories = [c.split(" — ")[0] for c in selected_cats]

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 5: Keywords
# ─────────────────────────────────────────────────────────────

st.markdown("## 5. Keywords")
st.markdown("Papers matching these keywords get pre-filtered before AI scoring. Higher weight = more important.")

# If AI suggested keywords, offer to add them
if ai_assist and st.session_state.ai_suggested_kws:
    new_suggestions = {k: v for k, v in st.session_state.ai_suggested_kws.items()
                       if k not in st.session_state.keywords}
    if new_suggestions:
        st.markdown("**Suggested keywords** — click to add:")
        cols = st.columns(3)
        to_add = {}
        for i, (kw, weight) in enumerate(new_suggestions.items()):
            with cols[i % 3]:
                if st.button(f"+ {kw} ({weight})", key=f"add_sug_{kw}", use_container_width=True):
                    to_add[kw] = weight
        if to_add:
            st.session_state.keywords.update(to_add)
            st.rerun()

        if st.button("Add all suggested keywords"):
            st.session_state.keywords.update(new_suggestions)
            st.rerun()

# Manual keyword entry
st.markdown("**Add keyword manually:**")
col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    new_kw = st.text_input("Keyword", placeholder="transmission spectroscopy", label_visibility="collapsed", key="new_kw_input")
with col2:
    new_weight = st.slider("Weight", 1, 10, 7, label_visibility="collapsed", key="new_kw_weight")
with col3:
    if st.button("Add", use_container_width=True, key="add_kw_btn"):
        if new_kw.strip():
            st.session_state.keywords[new_kw.strip()] = new_weight
            st.rerun()

# Display existing keywords
if st.session_state.keywords:
    st.markdown("**Your keywords:**")
    to_remove = []
    for kw, weight in sorted(st.session_state.keywords.items(), key=lambda x: -x[1]):
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown(f"`{kw}`")
        with col2:
            st.markdown(f"weight: **{weight}**/10")
        with col3:
            if st.button("✕", key=f"rm_kw_{kw}", help=f"Remove {kw}"):
                to_remove.append(kw)
    for kw in to_remove:
        del st.session_state.keywords[kw]
        st.rerun()
else:
    st.info("No keywords yet. Add some above, scan your Pure profile, or use AI suggestions.")

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 6: Research Authors
# ─────────────────────────────────────────────────────────────

st.markdown("## 6. Research Authors")
st.markdown("Papers by these people get a relevance boost. Use partial name strings (e.g. 'Madhusudhan').")

new_author = st.text_input("Add research author", placeholder="Madhusudhan", key="new_ra_input")
if st.button("Add author") and new_author.strip():
    if new_author.strip() not in st.session_state.research_authors:
        st.session_state.research_authors.append(new_author.strip())
        st.rerun()

if st.session_state.research_authors:
    to_remove = []
    for author in st.session_state.research_authors:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"- {author}")
        with col2:
            if st.button("✕", key=f"rm_ra_{author}"):
                to_remove.append(author)
    for a in to_remove:
        st.session_state.research_authors.remove(a)
        st.rerun()

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 7: Colleagues
# ─────────────────────────────────────────────────────────────

st.markdown("## 7. Colleagues")
st.markdown("Papers by colleagues always appear in a special section, even if off-topic. Great for staying social!")

st.markdown("**People:**")
col1, col2 = st.columns([2, 2])
with col1:
    new_coll_name = st.text_input("Colleague name", placeholder="Jane Smith", key="new_coll_name")
with col2:
    new_coll_match = st.text_input("Match pattern", placeholder="Smith, J", key="new_coll_match", help="How their name appears in arXiv author lists")

if st.button("Add colleague") and new_coll_name.strip() and new_coll_match.strip():
    st.session_state.colleagues_people.append({
        "name": new_coll_name.strip(),
        "match": [new_coll_match.strip()],
    })
    st.rerun()

if st.session_state.colleagues_people:
    to_remove = []
    for i, coll in enumerate(st.session_state.colleagues_people):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.markdown(f"**{coll['name']}**")
        with col2:
            st.markdown(f"match: `{', '.join(coll['match'])}`")
        with col3:
            if st.button("✕", key=f"rm_coll_{i}"):
                to_remove.append(i)
    for idx in sorted(to_remove, reverse=True):
        st.session_state.colleagues_people.pop(idx)
    if to_remove:
        st.rerun()

st.markdown("**Institutions** (match against abstract text):")
new_inst = st.text_input("Add institution", placeholder="Aarhus University", key="new_inst_input")
if st.button("Add institution") and new_inst.strip():
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

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 8: Digest Mode & Schedule
# ─────────────────────────────────────────────────────────────

st.markdown("## 8. Digest Mode & Schedule")

# ── Digest mode ──
st.markdown("**How much do you want to read?**")
digest_mode = st.radio(
    "Digest mode",
    options=["highlights", "in_depth"],
    format_func=lambda x: {
        "highlights": "🎯 Highlights — just the top papers (fewer, higher quality)",
        "in_depth": "📚 In-depth — wider net, more papers to browse",
    }[x],
    horizontal=True,
    label_visibility="collapsed",
)

# Show what the mode means
if digest_mode == "highlights":
    st.caption("Default: up to 6 papers, min score 5/10. Only the most relevant papers make it through.")
else:
    st.caption("Default: up to 15 papers, min score 2/10. Casts a wider net — great for staying broadly informed.")

# ── Advanced overrides ──
mode_defaults = {"highlights": (6, 5), "in_depth": (15, 2)}
default_max, default_min = mode_defaults[digest_mode]
override_max = False
override_min = False

with st.expander("Fine-tune (optional)"):
    col1, col2 = st.columns(2)
    with col1:
        max_papers = st.number_input("Max papers per digest", min_value=1, max_value=30, value=default_max)
    with col2:
        min_score = st.number_input("Min relevance score (1-10)", min_value=1, max_value=10, value=default_min)

    override_max = max_papers != default_max
    override_min = min_score != default_min

st.markdown("---")

# ── Schedule ──
st.markdown("**How often should the digest arrive?**")
schedule_options = {
    "mon_wed_fri": "Mon / Wed / Fri",
    "daily": "Every weekday (Mon–Fri)",
    "weekly": "Once a week (Monday)",
}
schedule = st.radio(
    "Frequency",
    options=list(schedule_options.keys()),
    format_func=lambda x: schedule_options[x],
    horizontal=True,
    label_visibility="collapsed",
)

# ── Days back (auto-set based on schedule, with override) ──
schedule_days_back = {"daily": 2, "mon_wed_fri": 4, "weekly": 8}
days_back = schedule_days_back[schedule]

with st.expander("Override days back"):
    days_back = st.number_input("Days to look back", min_value=1, max_value=14, value=days_back)

st.caption(f"Will look back **{days_back} days** for new papers.")

# ── Send time ──
st.markdown("**What time should it arrive?** (UTC)")
send_hour_utc = st.slider(
    "Send hour (UTC)",
    min_value=0, max_value=23, value=7,
    help="Default is 7 UTC = 9am Danish time (CET). Adjust for your timezone.",
    label_visibility="collapsed",
)

# Show common timezone equivalents
tz_examples = []
if 0 <= send_hour_utc <= 23:
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

# ── Generate cron expression ──
CRON_MAP = {
    "daily": f"0 {send_hour_utc} * * 1-5",
    "mon_wed_fri": f"0 {send_hour_utc} * * 1,3,5",
    "weekly": f"0 {send_hour_utc} * * 1",
}
cron_expr = CRON_MAP[schedule]

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 9: Email Provider
# ─────────────────────────────────────────────────────────────

st.markdown("## 9. Email Provider")
smtp_options = {"Gmail": ("smtp.gmail.com", 587), "Outlook / Office 365": ("smtp.office365.com", 587)}
smtp_choice = st.radio("SMTP provider", options=list(smtp_options.keys()), horizontal=True, label_visibility="collapsed")
smtp_server, smtp_port = smtp_options[smtp_choice]

github_repo = st.text_input("GitHub repo (optional)", placeholder="username/arxiv-digest", help="Enables self-service links in emails")

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 10: Preview & Download
# ─────────────────────────────────────────────────────────────

st.markdown("## 10. Preview & Download")

# Build config dict
config = {
    "digest_name": digest_name or "arXiv Digest",
    "researcher_name": researcher_name or "Reader",
    "research_context": research_context or "",
    "categories": categories if categories else ["astro-ph.EP"],
    "keywords": dict(st.session_state.keywords) if st.session_state.keywords else {"example keyword": 5},
    "self_match": list(st.session_state.self_match),
    "research_authors": list(st.session_state.research_authors),
    "colleagues": {
        "people": list(st.session_state.colleagues_people),
        "institutions": list(st.session_state.colleagues_institutions),
    },
    "digest_mode": digest_mode,
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

# Only include overrides if user changed them from mode defaults
if override_max:
    config["max_papers"] = max_papers
if override_min:
    config["min_score"] = min_score

config_yaml = yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)

tab1, tab2 = st.tabs(["config.yaml", "Workflow cron"])

with tab1:
    st.code(config_yaml, language="yaml")

with tab2:
    st.markdown("If you change the schedule from the default (Mon/Wed/Fri 7am UTC), update this line in `.github/workflows/digest.yml`:")
    st.code(f"    - cron: '{cron_expr}'  # {schedule_options[schedule]} at {send_hour_utc}:00 UTC", language="yaml")
    if schedule != "mon_wed_fri" or send_hour_utc != 7:
        st.warning("Your schedule differs from the default. Remember to update the cron line in your workflow file after forking!")

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
    if st.button("📋 Copy to clipboard", use_container_width=True):
        st.code(config_yaml, language="yaml")
        st.info("Select all text above and copy (Ctrl/Cmd+C)")

st.divider()


# ─────────────────────────────────────────────────────────────
#  Section 11: Next Steps
# ─────────────────────────────────────────────────────────────

st.markdown("## Next Steps")

# Custom schedule note
schedule_note = ""
if schedule != "mon_wed_fri" or send_hour_utc != 7:
    schedule_note = f"""
<div class="brand-card" style="border-left: 4px solid #EBC944;">
<p>⚠️ <strong>Update your schedule</strong></p>
<p style="margin-left: 36px;">
Since you chose <strong>{schedule_options[schedule]} at {send_hour_utc}:00 UTC</strong>, open
<code>.github/workflows/digest.yml</code> in your fork and change the cron line to:<br>
<code>- cron: '{cron_expr}'</code>
</p>
</div>
"""

st.markdown(f"""
<div class="brand-card">
<p><span class="step-number">1</span> <strong>Fork the template repo</strong></p>
<p style="margin-left: 36px;">
Go to <a href="https://github.com/SilkeDainese/arxiv-digest" style="color: #2F4F3E;">github.com/SilkeDainese/arxiv-digest</a>
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
<p><span class="step-number">3</span> <strong>Add email secrets</strong></p>
<p style="margin-left: 36px;">
Go to your fork's <strong>Settings → Secrets and variables → Actions</strong> and add:<br>
<code>RECIPIENT_EMAIL</code> — your email address<br>
<code>SMTP_USER</code> — your Gmail/Outlook address<br>
<code>SMTP_PASSWORD</code> — an App Password (<a href="https://myaccount.google.com/apppasswords" style="color: #2F4F3E;">Gmail</a> or <a href="https://account.microsoft.com/security" style="color: #2F4F3E;">Microsoft</a>)<br>
<em>Optional:</em> <code>ANTHROPIC_API_KEY</code> or <code>GEMINI_API_KEY</code> for AI scoring
</p>
</div>

{schedule_note}
""", unsafe_allow_html=True)

st.success(f"That's it! Your digest will run {schedule_options[schedule].lower()} at {send_hour_utc}:00 UTC. 🎉")

st.divider()

# ── Footer ──
st.markdown("""
<div style="text-align: center; font-family: 'DM Mono', monospace; font-size: 10px;
     letter-spacing: 0.1em; color: #6A6A66; margin-top: 24px; margin-bottom: 24px;">
     Built by <a href="https://silkedainese.github.io" style="color: #2F4F3E;">Silke S. Dainese</a> ·
     <a href="mailto:dainese@phys.au.dk" style="color: #6A6A66;">dainese@phys.au.dk</a> ·
     <a href="https://github.com/SilkeDainese" style="color: #6A6A66;">GitHub</a>
</div>
""", unsafe_allow_html=True)
