# Demo Creator Agent — Architecture

## What This Is
An internal tool that takes a discovery call transcript and automatically produces a working, deployed demo for the next customer meeting — with zero pre-sales engineering involvement.

**Current flow:** Cold call → Discovery (founder) → **Agent builds + deploys demo** → Demo meeting

---

## Team & Roles
- **SDR**: Pastes transcript into Slack, sends customer emails, relays customer inputs
- **Founder**: Reviews output, delivers the demo to customer
- **Agent**: Does everything in between — classify, check dependencies, match existing solutions, build code, deploy to Railway, post live URL

---

## Pipeline (5 Stages)

```
/demo [transcript]
       │
       ▼
[1] CLASSIFIER (Claude)
    → Is demo needed? What type? Extract raw spec.
    → If demo_decision=NO: stop here, explain why
       │
       ▼
[2] DEPENDENCY CHECKER (Claude + capabilities.json)
    → What APIs/hosting we provide
    → What systems to mock (enterprise systems, CRMs, etc.)
    → What to ask the customer (public URLs, API keys, sample data)
    → can_build_immediately: true/false
       │
       ▼
[3] SOLUTIONS MATCHER (Claude + solutions.json)
    → Check registry for existing demos to reuse
    → Full match (3+ keywords) → customize, don't rebuild
    → Partial match → use as starting point
    → No match → build from scratch
    → source=manual: founder must share/record (no URL)
    → source=demo_tool: live Railway URL available immediately
       │
       ├── ask_customer=true ────────────────────┐
       │                                         │
       ▼                                         │
[4] SDR MESSENGER (Claude)                       │
    → Internal brief for SDR                     │
    → Draft email to customer                    │
    → Bot posts to Slack thread                  │
    → SDR gets reply → /demo-continue [reply]    │
       │                                         │
       └─────────────────────────────┐           │
                                     ▼           ▼
                            [5] DEMO BUILDER (Claude)
                                → Writes complete runnable code
                                → JSON-only storage (no databases)
                                → Fallback mock data included
                                → README + talking points for founder
                                     │
                                     ▼
                            [DEPLOY] deploy.py
                                → Parse files from builder output
                                → Create GitHub repo + push (Git Tree API)
                                → Create Railway project + service
                                → Trigger deploy + provision domain
                                → Poll until SUCCESS (up to 5 min)
                                → Write entry to solutions.json
                                     │
                                     ▼
                            Bot posts live URL to Slack
                            Founder is tagged
```

---

## File Structure

```
demo-creation-agent/
├── prompts/
│   ├── 01_classifier.md           Stage 1 — is demo needed? what type?
│   ├── 02_dependency_checker.md   Stage 2 — what to provide/mock/ask
│   ├── 03_solutions_matcher.md    Stage 3 — reuse existing demos
│   ├── 04_sdr_messenger.md        Stage 4 — customer email draft
│   └── 05_demo_builder.md         Stage 5 — write complete demo code
├── registry/
│   ├── capabilities.json          APIs/hosting we have; systems to mock; what to ask
│   └── solutions.json             Library of all demos ever built (grows automatically)
├── slack/
│   ├── bot.py                     Slack bot — entry point for /demo and /demo-continue
│   ├── deploy.py                  GitHub + Railway deploy pipeline
│   └── requirements.txt
├── docs/
│   ├── ARCHITECTURE.md            This file
│   ├── GITHUB_SETUP.md            How to get GITHUB_TOKEN
│   └── RAILWAY_SETUP.md           How to get RAILWAY_TOKEN + GitHub App setup
├── test-trascripts/
│   └── renocomputerfix.txt        Sample transcript for testing
├── test_pipeline.py               CLI test runner (no Slack needed)
└── .env.example                   Token reference
```

---

## Environment Variables

| Variable | Required for | Where to get it |
|---|---|---|
| `SLACK_BOT_TOKEN` | Slack bot | Slack app dashboard → OAuth & Permissions |
| `SLACK_APP_TOKEN` | Slack bot (Socket Mode) | Slack app dashboard → Basic Information → App-Level Tokens |
| `ANTHROPIC_API_KEY` | All Claude calls | console.anthropic.com/settings/keys |
| `GITHUB_TOKEN` | Deploy pipeline | See `docs/GITHUB_SETUP.md` |
| `GITHUB_ORG` | Deploy pipeline (optional) | GitHub org name — repos created under this org; omit to use personal account |
| `RAILWAY_TOKEN` | Deploy pipeline | See `docs/RAILWAY_SETUP.md` |

---

## Running the Bot

```bash
# From project root — always run from here (prompts/ and registry/ paths are relative)
source .venv/bin/activate
python slack/bot.py
```

**Required Slack bot token scopes** (OAuth & Permissions → Bot Token Scopes):
- `commands` — slash commands (`/demo`, `/demo-continue`)
- `chat:write` — post messages
- `files:read` — download PDF files uploaded to channels

## Testing Without Slack

```bash
# Stages 1–5 only (needs ANTHROPIC_API_KEY)
python test_pipeline.py

# Explicit transcript
python test_pipeline.py test-trascripts/renocomputerfix.txt

# Stop after a specific stage (for prompt iteration)
python test_pipeline.py transcript.txt --stage 2

# Full end-to-end including deploy (needs all 5 tokens)
python test_pipeline.py transcript.txt --deploy
```

Output is saved to `test_output_{company}_{timestamp}.json` after each run.

---

## Registry Files

### `capabilities.json`
Defines three categories used by the Dependency Checker:

| Category | Meaning | Action |
|---|---|---|
| `we_provide` | APIs/hosting we have access to | Inject automatically |
| `always_mock` | Enterprise systems (Salesforce, SAP, SSO, etc.) | Simulate with realistic fake data |
| `ask_customer` | Fast items the customer can send in <15 mins | SDR sends email |

### `solutions.json`
Library of every demo ever built. The Matcher checks this before building anything new.

| Field | Values | Meaning |
|---|---|---|
| `source` | `manual` | Built by hand — no URL, founder must share/record |
| `source` | `demo_tool` | Auto-deployed by deploy.py — live Railway URL in `demo_url` |
| `demo_url` | string or null | Railway URL if source=demo_tool, null otherwise |

**Entries are added automatically** after every successful `--deploy` run. Manually add entries for demos built outside the tool (voice agents, 11labs integrations, etc.) with `source: manual`.

---

## Model Configuration

All stages use `claude-sonnet-4-20250514`:

| Stage | max_tokens |
|---|---|
| Classifier | 2000 |
| Dependency Checker | 2000 |
| Solutions Matcher | 2000 |
| SDR Messenger | 1500 |
| Demo Builder | 8000 |

---

## Tech Stack Constraints (enforced by prompts)

- **Storage**: JSON files only — no databases (PostgreSQL, SQLite, MongoDB, Redis)
- **Deployment**: Railway (web UIs, chat agents), Modal (pipelines, cron jobs), Vercel (static)
- **Never**: Docker, complex auth, database migrations, anything requiring >1 command to run

---

## Phase 2 (Next — Semi-Automated)

- **Spiky integration**: Poll for new transcripts tagged "discovery" — pipeline fires automatically
- **State persistence**: Store stage outputs in Supabase so `/demo-continue` doesn't require re-paste
- **Thread management**: One Slack thread per prospect with live status updates

## Phase 3 (Full Automation)

- Spiky webhook replaces polling (instant trigger on meeting end)
- SDR receives Slack DM automatically — no `/demo` command needed
- Demo deployed and URL posted before SDR has left the Zoom call
