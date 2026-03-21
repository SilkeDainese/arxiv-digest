<h1 align="center">🔭 arXiv Digest</h1>
<p align="center">
  <b>Get a daily email with the arXiv papers most relevant to your research, scored by AI.</b><br>
  <sub>
    Created by <a href="https://silkedainese.github.io">Silke S. Dainese</a> ·
    <a href="mailto:dainese@phys.au.dk">dainese@phys.au.dk</a> ·
    <a href="https://orcid.org/0009-0001-7885-2439">ORCID</a>
  </sub><br>
  <sub>
    <a href="https://arxiv-digest-production-93ba.up.railway.app"><b>Open setup wizard →</b></a> ·
    <a href="#quick-start">Quick Start</a> ·
    <a href="#how-scoring-works">How scoring works</a> ·
    <a href="#faq">FAQ</a>
  </sub>
</p>

I built this during my PhD in astronomy at Aarhus University to stay on top of new papers without doomscrolling arXiv. Others found it useful, so I made it public. It works for anyone whose papers are on arXiv — astronomy, physics, CS, whatever your field.

<p align="center">
  <img src=".github/sample-digest.png" width="480" alt="Sample arXiv Digest email showing a TOP PICK paper card with relevance score, research context summary, and feedback arrows"><br>
  <sub>Example digest email — TOP PICK card with relevance score and feedback arrows.</sub>
</p>

---

<details>
<summary><b>AU Students — there's an easier setup for you</b></summary>

AU students can subscribe through a separate signup page — contact the course instructor for the link. No GitHub, no config files, no API keys (passwords to AI services). Just your AU email and a password. AI scoring and email delivery are handled for you.

Pick from pre-built interest packages (exoplanets, stars, galaxies, cosmology, and more) and get a weekly digest. You can update your interests or unsubscribe anytime.

From another field? [Write me](mailto:dainese@phys.au.dk) and I'll set up packages for your speciality.

</details>

---

## Quick Start

Setup has three parts: make your own copy of the project, configure it for your research, and give it permission to send emails. The setup wizard handles the middle part — it generates a config file you just drop in.

**Step 1 — Fork the repo** (make your own copy of the project on GitHub)

Go to [github.com/SilkeDainese/arxiv-digest](https://github.com/SilkeDainese/arxiv-digest) and click **Fork** in the top right. This creates a private copy under your own GitHub account. Your config and data stay in your fork, separate from everyone else's.

**Step 2 — Run the setup wizard**

**[Open the setup wizard →](https://arxiv-digest-production-93ba.up.railway.app)**

Fill in your research interests — the wizard generates a `config.yaml` file for you. Download it, then upload it to the root of your fork (on GitHub: "Add file" → "Upload files" → drop `config.yaml` → "Commit changes").

**Step 3 — Add your secrets and start the automation**

Secrets are private settings stored inside your GitHub repository — like a password vault that GitHub Actions (GitHub's built-in automation — it runs your digest on a schedule, no server needed) can read but nobody else can see.

Go to your fork → **Settings → Secrets and variables → Actions → New repository secret** and add these:

| Secret name | What to put there | Required? |
|---|---|---|
| `RECIPIENT_EMAIL` | Your email address | Yes |
| `DIGEST_RELAY_TOKEN` | If you got an access code from a colleague: enter it in the setup wizard's Access Code button — the token appears automatically. No access code? Skip this row and use Option B (your own email) instead. | Option A |
| `SMTP_USER` + `SMTP_PASSWORD` | Your email address + an app password (a special one-time password your email provider generates so you don't expose your real password). **Gmail users:** You need 2-Step Verification enabled first — [enable it here](https://myaccount.google.com/signinoptions/two-step-verification). Then [generate an app password](https://myaccount.google.com/apppasswords). **Outlook users:** also add `smtp_server: "smtp.office365.com"` to your config.yaml. | Option B |
| `GEMINI_API_KEY` | A free API key (a password that lets the digest use Google's AI on your behalf) from [aistudio.google.com](https://aistudio.google.com/apikey) — optional, improves scoring | Optional |
| `ANTHROPIC_API_KEY` | A paid API key for Claude — optional, used if you prefer it over Gemini | Optional |

Finally, go to the **Actions** tab in your fork, enable workflows when prompted, then click **arXiv Digest → Run workflow** to send your first digest. After that, it runs automatically on the schedule you set.

> **That's it.** *Default schedule: Mon/Wed/Fri at 9am Danish time.*

<details>
<summary>Something not working?</summary>

- Make sure workflows are enabled — **Actions** tab → click "I understand my workflows, go ahead and enable them"
- Secrets go in *your fork*, not the original repo
- The file must be named exactly `config.yaml` (not `config (1).yaml`) and sit in the repo root
- First run: use "Run workflow" manually to test — check the run log if no email arrives (Actions → click on the run → expand the steps)
- Outlook users: add `smtp_server: "smtp.office365.com"` to your `config.yaml`

</details>

---

## How Scoring Works

Every new arXiv paper in your categories gets scored before it reaches your inbox. The process has three layers:

```
Your interests → arXiv papers → Keyword match → AI re-ranking → Author boost → Your digest
```

**1. Keyword matching** — Each paper's title and abstract is compared against your keywords. Every keyword has a weight from 1 to 10. Matching is fuzzy: `planet` matches `planetary`, `atmospheric` matches `atmosphere`.

**2. AI re-ranking** — If you have an AI key, the system reads your free-text research description and re-ranks the keyword-filtered papers by actual relevance — not just term overlap. The more specific your description, the better. A paper about "M-dwarf flare rates" might score low on keywords but rank high if you wrote "I study how stellar activity affects atmospheric escape on rocky planets."

**3. Author boost** — Papers by people in your collaborator list get bumped up. Papers you authored get a dedicated celebration section.

If AI is unavailable, the system cascades automatically through fallback tiers:

| Tier | Provider | When it's used |
|------|----------|----------------|
| 1 | Claude (Anthropic) | If you add `ANTHROPIC_API_KEY` |
| 2 | Gemini (Google) | If you add `GEMINI_API_KEY` |
| 3 | Keywords only | Always — no key needed |

If one tier fails, the next takes over. You always get a digest. The AI keys are entirely optional — keyword scoring works well on its own, especially once you tune your keyword weights.

---

## Customising Your Digest

See [`config.example.yaml`](config.example.yaml) for all options with inline comments. Key fields:

| Field | What it does |
|-------|-------------|
| `research_context` | Free-text description of your research — the more specific, the better |
| `keywords` | `keyword: weight` pairs (1–10) |
| `categories` | arXiv categories to monitor (e.g. `astro-ph.EP` for exoplanets) |
| `research_authors` | Authors whose papers get a relevance boost |
| `colleagues` | People whose papers always appear, even if off-topic |
| `digest_mode` | `highlights` (up to 6 papers, higher bar) or `in_depth` (up to 15, wider net) |
| `recipient_view_mode` | `deep_read` (full cards with context) or `5_min_skim` (top 3 one-liners) |
| `self_match` | Your name as it appears on arXiv — triggers a celebration section when you publish |

To change the schedule, edit the cron line in [`.github/workflows/digest.yml`](.github/workflows/digest.yml). The default is Mon/Wed/Fri at 9am Danish time.

---

## FAQ

<details>
<summary>Do I need an API key?</summary>

No. An API key is a password that lets your digest talk to an AI service (Google or Anthropic) to rank papers more intelligently. Keyword scoring works fine without one. If you want smarter ranking later, get a free key from [Google AI Studio](https://aistudio.google.com/apikey) or a paid key from [Anthropic Console](https://console.anthropic.com/), and add it as a repository secret.

</details>

<details>
<summary>What if I don't have an invite code / relay token?</summary>

You can send digests from your own email instead. Add `SMTP_USER` (your email address) and `SMTP_PASSWORD` (a Gmail or Outlook app password — a special password generated just for this, separate from your real one) as repository secrets.

- Gmail app password: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- Outlook users: also add `smtp_server: "smtp.office365.com"` to your `config.yaml`

</details>

<details>
<summary>How does the feedback loop work?</summary>

Each paper card in the digest email has ↑ and ↓ arrows. Clicking one creates a GitHub issue in your fork (GitHub Issues is just a built-in note-taking system — the digest reads these notes on its next run). Upvoted keywords get a scoring boost, downvoted ones get dampened. The system learns what you actually care about over time.

To enable feedback arrows, set `github_repo: "yourusername/arxiv-digest"` in your `config.yaml`.

</details>

<details>
<summary>I have an invite code — where do I enter it?</summary>

On the [setup wizard](https://arxiv-digest-production-93ba.up.railway.app), click the **Access code** button in the top-right corner. An invite code is a shortcut from a colleague who already runs the digest — it pre-fills your AI key and email relay settings so you don't have to configure them yourself.

</details>

<details>
<summary>Can I change the delivery schedule?</summary>

The setup wizard lets you pick Mon/Wed/Fri, every weekday, or weekly. That choice goes into your `config.yaml`.

The *actual* schedule is controlled by a timer in `.github/workflows/digest.yml` (the `cron:` line). The default runs Mon/Wed/Fri at 07:00 UTC (~09:00 Danish time). If you want a different schedule, edit that line in your fork — [crontab.guru](https://crontab.guru) is a friendly tool for building the right expression. Or just trigger a manual run any time: your repo → Actions → arXiv Digest → Run workflow.

</details>

<details>
<summary>How do I pause or unsubscribe?</summary>

- **Pause:** your repo → Actions → arXiv Digest → click `⋯` → Disable workflow
- **Delete everything:** your repo → Settings → scroll to Danger Zone → Delete this repository

Every digest email also includes self-service links at the bottom: edit interests, pause, re-run setup, delete.

</details>

<details>
<summary>Can I run it locally?</summary>

```bash
pip install -r requirements.txt
python digest.py --preview        # renders in browser, no email sent
python digest.py                  # full run (needs RECIPIENT_EMAIL + email credentials)
python setup/server.py            # run the setup wizard locally at localhost:8080
```

</details>

<details>
<summary>Can I use the terminal for setup?</summary>

Run `python -m scripts.friend_setup` from a checkout of this repo. It opens the setup wizard, waits for the downloaded config file, forks the repo, uploads the config, and enables GitHub Actions — all in one go.

</details>

---

## License

MIT — see [LICENSE](LICENSE). Contribution guidelines: [CONTRIBUTING.md](CONTRIBUTING.md).
