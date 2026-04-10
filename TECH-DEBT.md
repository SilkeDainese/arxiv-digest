# TECH-DEBT.md — arXiv Digest

Tracking open technical debt, resolved items, and new discoveries.

---

## RESOLVED

### [SEC-001] Credential leak in arxiv-digest-students-private — CLOSED 2026-04-10
**Root cause:** Private GitHub repo used as runtime database. `students/subscriptions.json`
contained password hashes (scrypt) + salts + email addresses committed to git from
2026-03-15 to 2026-03-30. Password auth had been removed from code on 2026-03-20 but
the already-committed records were never cleaned.

**Fix applied:**
- Repo gutted: all application code and data deleted from working tree
- History rewritten: git-filter-repo removed both data files from all 78 commits
- Force-pushed: clean single-commit history on GitHub
- Prevention stack: gitleaks global hooks, global gitignore, security rulebook rules
- Architecture pivot: student subscription system to be rebuilt with no server-side auth
  and no subscriber data in git (separate sprint, storage TBD)

**Backup:** `~/Projects/_backups/arxiv-digest-students-private-pre-scrub-2026-04-10.git`

**Incident memo:** `arxiv-digest-students-private/docs/incidents/2026-04-10-credential-leak.md`

---

## OPEN

### [SEC-002] GitHub cache-purge pending — OPEN
The force-push rewrote history on GitHub but GitHub's caches (CDN, API cache, pack
files) may retain the old objects for some period. A support request to GitHub must be
sent to request explicit invalidation.

**Action required by Silke:** Send the cache-purge email to support@github.com.
Draft is in the final Cerberus sprint report.

### [SEC-003] Repo archive pending — OPEN
`SilkeDainese/arxiv-digest-students-private` should be archived via GitHub web UI
to make it read-only and prevent accidental future writes.

**Action required by Silke:** Go to github.com/SilkeDainese/arxiv-digest-students-private
→ Settings → Danger Zone → Archive this repository.

### [SEC-004] New student subscription system — OPEN (future sprint)
The student digest currently has no subscription backend. Architecture TBD once
Silke decides on storage ("SOMEWHERE"). Requirements: no passwords, email + topic
preferences only, no subscriber data in git under any circumstances.

**Constraint:** Gitignored local file and/or a proper database (SQLite, Supabase, etc.)
are both valid. Private-repo-as-database is permanently banned.

### [INF-001] flask not in setup/requirements.txt — OPEN
Running `pytest tests/test_setup_server.py` fails with `ModuleNotFoundError: No module
named 'flask'` when using the project venv. Flask is a runtime dependency of
`setup/server.py` but is missing from `setup/requirements.txt`.

**Fix:** Add `flask==3.x.x` (pinned) to `setup/requirements.txt`.
