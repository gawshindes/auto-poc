# Demo Creator Agent — Architecture

## What This Is
An internal tool that takes a discovery call transcript and automatically produces a working, deployed demo for the next customer meeting — with zero pre-sales engineering involvement.

**Flow:** Discovery call → Upload transcript → **Agent builds + deploys demo** → Demo meeting

---

## Interfaces

| Interface | Entry point | Use case |
|-----------|-------------|----------|
| **Web UI** | `uvicorn web.app:app --port 8000` | Primary — upload transcript, run pipeline, view results |
| **CLI** | `python test/scripts/test_pipeline.py transcript.txt` | Testing and batch processing |

---

## Pipeline (4 Stages)

```
Upload transcript
       │
       ▼
[1] UNDERSTAND (Claude)
    → Classify transcript: is demo needed? what type?
    → Extract customer info, core problem, proposed solution
    → Dependency resolution: what to provide / mock / ask customer
    → Knowledge resolution: self-resolve what LLM can generate
    → Solutions match: check existing demos for reuse
    → If match found → stop here, present existing demo
    → If demo_decision=NO → stop here, explain why
       │
       ├── ask_customer items (if any with urgency "needed before build")
       │   → Pipeline pauses, UI shows input panel
       │   → User provides customer inputs or leaves blank for mock data
       │
       ▼
[2] DESIGN (Claude)
    → Demo spec: name, description, features, stack, skills
    → Component matches from solutions registry
    → Blueprint for the builder
       │
       ▼
[3] BUILD (Claude) + VERIFY + DEPLOY
    → Writes complete runnable code
    → Static analysis + verification agent fixes issues
    → deploy.py: GitHub repo + Railway deploy
    → Health check verification
    → Demo saved to DB only after successful deploy
       │
       ▼
[4] GUIDE (Claude)
    → Talking points for founder
    → How to present the demo
```

---

## File Structure

```
demo-creation-agent/
├── pipeline.py                  Shared pipeline module — all run_* functions
├── deploy.py                    GitHub + Railway deploy pipeline
├── Procfile                     Railway start command
├── requirements.txt             Python dependencies
├── .env.example                 Environment variable reference
│
├── prompts/
│   ├── 01_understand.md         Stage 1 — classify, dependencies, knowledge, solutions match
│   ├── 02_design.md             Stage 2 — demo spec and blueprint
│   ├── 03_build.md              Stage 3 — write complete demo code
│   ├── 03b_verify.md            Stage 3b — fix issues found by static analysis
│   ├── 04_guide.md              Stage 4 — demo talking points
│   └── capabilities.md          Reference: APIs, mock strategies, customer ask patterns
│
├── storage/
│   ├── __init__.py              StorageBackend ABC + get_backend() factory
│   ├── sqlite_backend.py        SQLite backend (default, local dev)
│   ├── supabase_backend.py      Supabase/PostgreSQL backend (production)
│   └── migrations/              SQL migration files (auto-applied for SQLite, manual for Supabase)
│
├── skills/                      Pluggable skill adapters (e.g., slack/)
│   └── slack/
│       ├── manifest.json        Skill metadata
│       └── adapter.py           Skill implementation
│
├── registry/
│   ├── team.json                Internal team members (names only)
│   └── team.example.json        Template for new deployers
│
├── web/
│   ├── app.py                   FastAPI backend — SSE, session management
│   └── index.html               Single-page UI (vanilla JS)
│
├── scripts/
│   └── migrate_to_supabase.py   One-time migration from SQLite to Supabase
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
    ├── USER_GUIDE.md            End-user guide
    ├── GITHUB_SETUP.md          How to get GITHUB_TOKEN
    └── RAILWAY_SETUP.md         How to get RAILWAY_TOKEN
```

---

## Data Model

4 tables: `sessions`, `demos`, `session_logs`, `team_members`.

### Sessions
A session is a single pipeline run. It owns transcript data inline.

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | `sess_XXXXXXXX` |
| source | TEXT | `web`, `cli`, `slack` |
| transcript | TEXT | Full transcript text (inline, not a separate table) |
| meeting_link | TEXT | Optional URL to recording |
| additional_context | TEXT | Operator-provided context |
| email | TEXT | For auto-mode notifications |
| status | TEXT | `idle`, `running`, `waiting_input`, `waiting_continue`, `verifying`, `deploying`, `done`, `error` |
| current_stage | INT | 0–4 |
| mode | TEXT | `auto` or `verbose` |
| error | TEXT | Error message if failed |
| stage_1_understand | JSON | Understand output |
| stage_2_design | JSON | Design output |
| stage_3_demo | TEXT | Generated demo code |
| stage_4_guide | TEXT | Demo guide text |

### Demos
A demo is a deployed artifact. Only created after successful deployment.

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | `demo_XXXXXXXX` |
| session_id | TEXT FK | Links back to the session that created it |
| company | TEXT | Customer company name |
| name | TEXT | Demo name from Design stage |
| deploy_url | TEXT | Live Railway URL |
| github_repo | TEXT | GitHub repo path |
| health_check_passed | BOOL | Whether deploy health check passed |
| is_active | BOOL | Soft-delete flag (false = deleted) |
| demo_type, use_case, description, stack, keywords, skills_used | Various | Metadata from pipeline |

### Session Logs
Append-only log entries per session.

### Team Members
Internal team names — used by Understand stage to distinguish team from customer in transcripts.

### Key Design Decisions
- **Demos only after deploy**: No demo record exists until Railway deploy succeeds. This means the demos table = the solutions registry.
- **No separate solutions registry**: Every active demo is a solution candidate. `get_solutions()` returns all demos where `is_active=1`.
- **Session owns transcript**: No separate transcripts table. Transcript text lives directly on the session row.
- **Soft-delete via is_active**: Deleting a demo sets `is_active=0`. It won't appear in the library or be matched to future sessions.

---

## Storage Backends

| Backend | Env var | When to use |
|---------|---------|-------------|
| **SQLite** (default) | `STORAGE_BACKEND=sqlite` | Local dev, zero setup |
| **Supabase** | `STORAGE_BACKEND=supabase` | Production, multi-user |

Migrations in `storage/migrations/`:
- `*.sql` (non-`_pg`) — auto-applied by SQLite backend on startup
- `*_pg.sql` — must be run manually in Supabase SQL Editor

---

## Solutions Matching

The Understand stage (Stage 1) checks the solutions registry for existing demos that match the customer's need. This happens BEFORE Design/Build, saving LLM calls when a match exists.

**Flow:**
1. `get_solutions()` returns all active demos from DB
2. Understand prompt includes the solutions list
3. LLM uses semantic judgment: "Would this existing demo demonstrate the capability the customer asked about?"
4. If matched → pipeline stops, UI shows match panel with link to existing demo
5. If no match → pipeline continues to Design

---

## Environment Variables

| Variable | Required for | Where to get it |
|----------|-------------|-----------------|
| `ANTHROPIC_API_KEY` | All Claude calls | console.anthropic.com/settings/keys |
| `GITHUB_TOKEN` | Deploy pipeline | See `docs/GITHUB_SETUP.md` |
| `GITHUB_ORG` | Deploy (optional) | GitHub org name |
| `RAILWAY_TOKEN` | Deploy pipeline | See `docs/RAILWAY_SETUP.md` |
| `DATA_DIR` | Railway deploy | Set to `/data` (volume mount) |
| `STORAGE_BACKEND` | Optional | `sqlite` (default) or `supabase` |
| `SUPABASE_URL` | Supabase backend | Supabase dashboard → Settings → API |
| `SUPABASE_KEY` | Supabase backend | Supabase dashboard → Settings → API (service_role key) |
| `RESEND_API_KEY` | Email notifications (optional) | resend.com |
| `ADMIN_TOKEN` | Admin API endpoints | Any strong secret |

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

All stages use `claude-sonnet-4-20250514` (configurable via `BUILDER_ANTHROPIC_MODEL` env var):

| Stage | max_tokens |
|-------|-----------|
| Understand | 4000 |
| Design | 6000 |
| Build | 16000 |
| Verify | 16000 |
| Guide | 1000 |

---

## Deploy Pipeline (deploy.py)

When a demo is built, `deploy.py` handles:
1. Parse markdown output into individual files
2. Static analysis + verification agent (fix issues before deploy)
3. Create GitHub repo under `GITHUB_ORG` (or personal account)
4. Push all files via Git Tree API (single commit)
5. Create Railway project + service linked to the repo
6. Trigger deploy + provision public domain
7. Health check — verify the deployed app responds
8. On success: save demo to DB with deploy_url and health_check status
