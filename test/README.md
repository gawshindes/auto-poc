# Test Scripts — Usage Guide

All scripts are run from the **project root** (`demo-creation-agent/`).

---

## test_pipeline.py

End-to-end CLI runner for the 5-stage demo creation pipeline. No Slack required.

**Stages:**
1. Classifier — identifies customer, demo type, problem/solution
2. Dependency Checker — lists what's needed to build
3. Solutions Matcher — checks if an existing demo can be reused
4. SDR Messenger — drafts email to collect customer inputs (only if needed)
5. Demo Builder — generates full deployable app code

```bash
# Run full pipeline on default transcript (renocomputerfix.txt)
python3 test/scripts/test_pipeline.py

# Run on a specific transcript (txt or PDF)
python3 test/scripts/test_pipeline.py test/data/transcripts/renocomputerfix.txt
python3 test/scripts/test_pipeline.py "test/data/transcripts/Discovery Call_ViewPlusXPOPTranscript.pdf"

# Stop after a specific stage (1–5)
python3 test/scripts/test_pipeline.py transcript.pdf --stage 3

# Run full pipeline + deploy to GitHub & Railway
python3 test/scripts/test_pipeline.py transcript.pdf --deploy

# Re-run only Stage 5 from a saved output JSON (saves token cost)
python3 test/scripts/test_pipeline.py --rebuild-demo latest
python3 test/scripts/test_pipeline.py --rebuild-demo latest --deploy
python3 test/scripts/test_pipeline.py --rebuild-demo test/data/outputs/test_output_acme_20260305_120000.json

# Deploy from a saved output JSON without re-running any stages
python3 test/scripts/test_pipeline.py --redeploy latest
python3 test/scripts/test_pipeline.py --redeploy test/data/outputs/test_output_acme_20260305_120000.json
```

**Output:** JSON saved to `test/data/outputs/test_output_<company>_<timestamp>.json`

**Required env vars:** `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `RAILWAY_TOKEN`
**Optional:** `GITHUB_ORG` (defaults to personal account if not set)

---

## cleanup_deploy.py

Delete GitHub repos and/or Railway projects matching a name pattern. Dry-run by default.

```bash
# Preview what would be deleted (dry-run, no changes)
python3 test/scripts/cleanup_deploy.py viewplus --github
python3 test/scripts/cleanup_deploy.py viewplus --railway
python3 test/scripts/cleanup_deploy.py viewplus --github --railway

# Actually delete (add --confirm)
python3 test/scripts/cleanup_deploy.py viewplus --github --railway --confirm

# Wipe all demo- prefixed repos/projects
python3 test/scripts/cleanup_deploy.py demo- --github --railway --confirm
```

**Required env vars:**
- `GITHUB_TOKEN_CLEANUP` — a separate token with `delete_repo` scope (kept separate from the agent's `GITHUB_TOKEN` for safety)
- `RAILWAY_TOKEN` — same token used by the pipeline
- `GITHUB_ORG` — optional, same as above

---

## create_sample_transcripts.py

One-time utility to convert a `.txt` transcript to `.pdf` format for testing the PDF ingestion path.

```bash
python3 test/scripts/create_sample_transcripts.py
```

Reads `test/data/transcripts/spiky_sample.txt` → writes `test/data/transcripts/spiky_sample.pdf`.

Requires: `pip install fpdf2`

---

## Directory layout

```
test/
├── scripts/
│   ├── test_pipeline.py          # Main pipeline test runner
│   ├── cleanup_deploy.py         # Delete GitHub repos + Railway projects
│   └── create_sample_transcripts.py  # txt → pdf converter
└── data/
    ├── transcripts/              # Input transcripts (.txt and .pdf)
    └── outputs/                  # Saved pipeline results (test_output_*.json)
```
