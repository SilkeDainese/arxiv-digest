# Contributing to arXiv Digest

Thanks for your interest. This is a personal tool that I have made public. Contributions are welcome but I cannot promise to merge everything — my research comes first.

---

## Before You Start

Open an issue before writing code. Describe what you want to change and why. This saves both of us time if the direction is wrong.

---

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/arxiv-digest.git
cd arxiv-digest

# Install dependencies
pip install -r requirements.txt

# Run the digest locally
export RECIPIENT_EMAIL="you@example.com"  # or "alice@example.com,bob@example.com"
export SMTP_USER="you@gmail.com"
export SMTP_PASSWORD="your-app-password"
export ANTHROPIC_API_KEY="your-key"   # optional
python digest.py

# Run the test suite
pytest tests/
```

---

## Project Structure

```
digest.py              — the entire pipeline (single-file by design)
brand.py               — colour palette, single source of truth
config.example.yaml    — config template and documentation
requirements.txt       — pinned runtime dependencies
setup/                 — Streamlit setup wizard (separate app)
tests/test_digest.py   — pytest suite
.github/workflows/     — CI/CD
```

The core is intentionally a single file. This makes it easy for non-developers to read and fork. Do not split it into modules without a strong reason.

---

## Rules for Changes

**Config changes:**
- New config fields must have a default in `load_config()`. Old configs without the field must not crash.
- Do not add required fields — everything must be optional with a sensible fallback.
- Do not commit changes to `config.yaml` — it is user data.

**Dependencies:**
- Do not add packages to `requirements.txt` without a strong case. The dependency list is deliberately minimal.
- All entries must be pinned to exact versions (`==`). No ranges (`>=`).

**Scoring cascade:**
- The order Claude → Gemini → keyword fallback is fixed. Do not change it.
- The keyword-only fallback must always work without any API key.

**Brand:**
- Colours come from `brand.py`. Do not hardcode hex values elsewhere.

**GitHub Actions:**
- All `uses:` lines must be pinned to a commit SHA. Format: `uses: actions/foo@<sha>  # vN`.
- Do not add secrets with new names if the existing names cover the use case.

---

## Tests

All changes must pass `pytest tests/`. If you add a new function, add tests for it.

- Use the `make_paper()` and `make_config()` helpers for test fixtures.
- Mock file I/O and env vars with `unittest.mock.patch`. Tests must not touch the real filesystem or make real API calls.
- If you find a bug but fixing it would break existing behaviour, mark the test `@pytest.mark.xfail` with an explanation rather than silently accepting the wrong behaviour.

---

## Pull Requests

- One concern per PR. Do not bundle unrelated changes.
- Write a clear description of what changed and why.
- If the change affects the README, update it.
- If the change affects config fields, update `config.example.yaml`.

---

## What I Will Not Merge

- Changes that add required config fields (breaks existing forks)
- New runtime dependencies without a strong case
- Changes to the README that add jargon or make the Quick Start longer
- Splitting `digest.py` into multiple modules (unless the file grows dramatically)

---

## Questions

Open an issue or email [dainese@phys.au.dk](mailto:dainese@phys.au.dk). I read everything but response time varies.
