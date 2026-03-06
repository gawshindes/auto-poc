# Phase 2 — Roadmap

## Features

### 1. User prompt / meeting context
Allow the user to provide free-text context from the demo meeting before the pipeline runs — e.g. "they specifically asked for a Shopify integration" or "budget is tight, keep it simple". This context is passed into the relevant stages (dependency checker, demo builder) to steer the output without editing the transcript.

**Implementation ideas:**
- Add an optional "Meeting notes" textarea on the upload/mode-selection screen
- Pass as an extra field in the `/run` request body
- Inject into classifier and demo builder prompts as a `<context>` block

### 2. Multiple document upload
Accept more than one file per session — e.g. transcript + a spec doc + a product one-pager. The pipeline combines them for richer context.

**Implementation ideas:**
- Multi-file drop zone in the UI (accept PDF and TXT)
- Concatenate or section-label each document before passing to the classifier
- Show uploaded file list with remove option before starting

### 3. Onboarding tool (CLI + web)
Currently `registry/team.json` and `registry/solutions.json` are edited manually. A guided onboarding flow for new deployers.

**Team onboarding:**
- CLI: `python onboard.py` — prompts for team member names interactively, writes `registry/team.json`
- Web: `/settings` page with a form to add/remove team members

**Solutions onboarding:**
- Allow adding pre-existing solutions (built outside the pipeline) via a form
- Fields: name, description, demo type, keywords, stack, source (manual/demo_tool), demo URL
- Useful for bootstrapping the registry with solutions the team has already built before adopting this tool

**Implementation ideas:**
- Single `/settings` page in the web UI covering both team + solutions management
- CLI: `python onboard.py --team` and `python onboard.py --solutions` for headless setup
- Validate entries against the expected schema before saving
