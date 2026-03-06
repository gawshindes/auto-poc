# Demo Creator Agent — Architecture

## What This Is
An internal tool that takes a discovery call transcript and automatically produces a working, deployed demo for the next customer meeting — with zero pre-sales engineering involvement.

**Flow:** Discovery call → Upload transcript → **Agent builds + deploys demo** → Demo meeting

---

## Interfaces

| Interface | Entry point | Use case |
|-----------|-------------|----------|
| **Web UI** | `uvicorn web.app:app --port 8000` | Primary — upload transcript, run pipeline, view results |
| **Slack bot** | `python slack/bot.py` | `/demo [transcript]` and `/demo-continue` commands |
| **CLI** | `python test/scripts/test_pipeline.py transcript.txt` | Testing and batch processing |

---

## Pipeline (6 Stages)

```
Upload transcript
       │
       ▼
[1] CLASSIFIER (Claude)
    → Is demo needed? What type? Extract raw spec.
    → If demo_decision=NO: stop here, explain why
       │
       ▼
[2] DEPENDENCY CHECKER (Claude + capabilities.md)
    → What APIs/hosting we provide
    → What systems to mock (enterprise systems, CRMs, etc.)
    → What to ask the customer (public URLs, API keys, sample data)
    → can_build_immediately: true/false
       │
       ▼
[3] SOLUTIONS MATCHER (Claude + solutions registry)
    → Check registry for existing demos to reuse
    → Full match → customize, don't rebuild
    → Partial match → use as starting point
    → No match → build from scratch
       │
       ├── ask_customer items ──────────────────┐
       │                                        │
       ▼                                        │
[4] SDR MESSENGER (Claude)                      │
    → Internal brief for SDR                    │
    → Draft email to customer                   │
    → Collect customer inputs                   │
       │                                        │
       └────────────────────────────┐           │
                                    ▼           ▼
                           [5] DEMO BUILDER (Claude)
                               → Writes complete runnable code
                               → Fallback mock data included
                                    │
                                    ▼
                           [DEPLOY] deploy.py
                               → Parse files from builder output
                               → Create GitHub repo + push
                               → Create Railway project + deploy
                               → Append to solutions registry
                                    │
                                    ▼
                           [6] DEMO GUIDE (Claude)
                               → Talking points for founder
                               → How to run/present the demo
```

---

## File Structure

```
demo-creation-agent/
├── pipeline.py                  Shared pipeline module — all run_* functions
├── Procfile                     Railway start command
├── requirements.txt             Python dependencies
├── .env.example                 Environment variable reference
│
├── prompts/
│   ├── 01_classifier.md         Stage 1 — is demo needed? what type?
│   ├── 02_dependency_checker.md Stage 2 — what to provide/mock/ask
│   ├── capabilities.md          Reference: APIs, mock strategies, customer ask patterns
│   ├── 03_solutions_matcher.md  Stage 3 — reuse existing demos
│   ├── 04_sdr_messenger.md      Stage 4 — customer email draft
│   ├── 05_demo_builder.md       Stage 5 — write complete demo code
│   └── 06_demo_guide.md         Stage 6 — demo talking points
│
├── storage/
│   ├── __init__.py              StorageBackend ABC + get_backend() factory
│   ├── json_backend.py          JSON file backend (default, zero setup)
│   └── sqlite_backend.py        SQLite backend (opt-in, concurrent access)
│
├── registry/
│   ├── team.json                Internal team members (names only)
│   ├── team.example.json        Template for new deployers
│   ├── solutions.json           Library of all demos ever built (grows automatically)
│   └── solutions.example.json   Template with schema reference
│
├── web/
│   ├── app.py                   FastAPI backend — SSE, session management
│   └── index.html               Single-page UI
│
├── slack/
│   ├── bot.py                   Slack bot — /demo and /demo-continue
│   └── deploy.py                GitHub + Railway deploy pipeline
│
├── test/
│   ├── scripts/
│   │   └── test_pipeline.py     CLI test runner
│   └── data/
│       ├── transcripts/         Sample transcripts (.txt)
│       └── outputs/             Test run outputs (gitignored)
│
└── docs/
    ├── ARCHITECTURE.md          This file
    ├── PHASE2.md                Phase 2 roadmap
    ├── GITHUB_SETUP.md          How to get GITHUB_TOKEN
    └── RAILWAY_SETUP.md         How to get RAILWAY_TOKEN
```

---

## Storage Architecture

### Static config (committed to git, baked into image)

| File | Purpose | Loaded by |
|------|---------|-----------|
| `prompts/*.md` | System prompts for each pipeline stage | `pipeline.py` at import time |
| `registry/team.json` | Team member names (classifier uses to identify customers) | `pipeline.py` at import time |
| `prompts/capabilities.md` | APIs, mock strategies, customer ask patterns | `pipeline.py` at import time |

### Runtime data (managed by storage backend)

| Data | Default (JSON) | SQLite |
|------|----------------|--------|
| **Solutions registry** | `{DATA_DIR}/registry/solutions.json` | `solutions` table in `data.db` |
| **Sessions** | `{DATA_DIR}/sessions/{id}.json` | `sessions` table in `data.db` |
| **Slack state** | `{DATA_DIR}/slack/state/{channel}.json` | `slack_state` table in `data.db` |

### Storage backends

| Backend | Env var | When to use |
|---------|---------|-------------|
| **JSON files** (default) | `STORAGE_BACKEND=json` | Local dev, single user, zero setup |
| **SQLite** | `STORAGE_BACKEND=sqlite` | Concurrent pipelines, better session listing |

Both backends auto-seed solutions from `registry/solutions.json` on first boot.

### DATA_DIR

| Environment | Value | Effect |
|-------------|-------|--------|
| Local dev | Defaults to project root | Runtime data lives alongside code |
| Railway | `DATA_DIR=/data` | Runtime data on persistent volume, survives redeploys |

---

## Environment Variables

| Variable | Required for | Where to get it |
|----------|-------------|-----------------|
| `ANTHROPIC_API_KEY` | All Claude calls | console.anthropic.com/settings/keys |
| `GITHUB_TOKEN` | Deploy pipeline | See `docs/GITHUB_SETUP.md` |
| `GITHUB_ORG` | Deploy (optional) | GitHub org name |
| `RAILWAY_TOKEN` | Deploy pipeline | See `docs/RAILWAY_SETUP.md` |
| `DATA_DIR` | Railway deploy | Set to `/data` (volume mount) |
| `STORAGE_BACKEND` | Optional | `json` (default) or `sqlite` |
| `RESEND_API_KEY` | Email notifications (optional) | resend.com |
| `SLACK_BOT_TOKEN` | Slack bot only | Slack app dashboard |
| `SLACK_APP_TOKEN` | Slack bot only | Slack app dashboard |

---

## Quick Start

```bash
git clone <repo>
cp .env.example .env              # Add ANTHROPIC_API_KEY (minimum)
cp registry/team.example.json registry/team.json  # Add your team names
pip install -r requirements.txt
uvicorn web.app:app --port 8000   # Open http://localhost:8000
```

---

## Model Configuration

All stages use `claude-sonnet-4-20250514`:

| Stage | max_tokens |
|-------|-----------|
| Classifier | 2000 |
| Dependency Checker | 2000 |
| Solutions Matcher | 2000 |
| SDR Messenger | 1500 |
| Demo Builder | 16000 |
| Demo Guide | 1000 |

---

## Deploy Pipeline (deploy.py)

When a demo is built, `deploy.py` handles:
1. Parse markdown output into individual files
2. Create GitHub repo under `GITHUB_ORG` (or personal account)
3. Push all files via Git Tree API (single commit)
4. Create Railway project + service linked to the repo
5. Trigger deploy + provision public domain
6. Poll until deployment succeeds (up to 5 min timeout)
7. Append solution entry to the registry
