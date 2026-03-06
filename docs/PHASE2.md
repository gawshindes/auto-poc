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

### 3. Team onboarding tool (CLI + web)
Currently `registry/team.json` is edited manually. A small onboarding flow that asks for team member names and writes the file — useful for new deployers.

**Implementation ideas:**
- CLI: `python onboard.py` — prompts for names interactively, writes `registry/team.json`
- Web: `/settings` page with a form to add/remove team members, saved to the volume
