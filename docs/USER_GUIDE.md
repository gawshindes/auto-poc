# Demo Creation Tool — Internal User Guide

This guide explains how to use the web version of the demo creation tool end-to-end: from uploading a discovery call transcript to getting a live demo URL, finding the GitHub repo, and making manual edits.

---

## Accessing the Tool

Open the tool in your browser (use the Railway URL shared with your team). No login is required — it's an internal tool.

---

## Step 1 — Prepare Your Transcript

The tool accepts the following file formats:

| Format | Notes |
|--------|-------|
| `.txt` | Plain text transcript — works best |
| `.pdf` | Spiky and Fathom PDF exports work out of the box; PDF must be text-based (not a scanned image) |
| `.md`  | Markdown transcript |

**Supported recording tools:**
- **Spiky** — export as PDF or copy-paste to `.txt`
- **Fathom** — copy the full transcript text from the Fathom call page and save as `.txt`

**Tip:** The tool reads the raw transcript text — any format where speaker names and turns are clearly laid out will work.

---

## Step 2 — Upload the Transcript

1. On the home screen, drag your transcript file onto the upload zone, or click anywhere in the zone to browse your files.
2. The file name appears in the bar below the drop zone once selected.
3. Changed your mind? Click **Change file** to swap it before starting.

---

## Step 3 — Choose a Mode

After uploading, you'll choose how the pipeline runs:

### Auto *(Recommended)*

All 6 stages run automatically without you having to click anything. The pipeline only pauses if it needs specific customer inputs (e.g., API keys or credentials).

- Enter your email (optional) to receive a notification with the demo link when it's done.
- Best for most use cases — just upload and come back to the result.

### Verbose (Step by Step)

The pipeline pauses after each of the 6 stages and shows you the full output. You click **Continue** to advance to the next stage.

- Useful when you want to inspect the AI's analysis before proceeding.

Click **Start Pipeline** once you've chosen a mode.

---

## What the Pipeline Does

The pipeline runs 6 AI stages to go from transcript to deployed demo:

| Stage | Name | What it does |
|-------|------|-------------|
| 1 | **Classifier** | Reads the transcript, identifies the customer, company, core problem, and type of demo needed |
| 2 | **Dependency Checker** | Lists credentials, API keys, or integrations needed to build the demo |
| 3 | **Solutions Matcher** | Checks if we've already built something similar — reuses or adapts if matched |
| 4 | **SDR Messenger** | Drafts a message you can send the customer to request any missing inputs |
| 5 | **Demo Builder** | Writes the full demo application code (Python/Flask) |
| 6 | **Demo Guide** | Writes a short usage guide for the deployed demo |

---

## Providing Customer Inputs (When Prompted)

If Stage 2 identifies required inputs (e.g., an API key, webhook URL, or credentials), the pipeline pauses and shows an input panel with fields to fill in.

- **Required** fields (red tag) — must be filled to build a real, working demo.
- **Optional** fields (gray tag) — the demo will use placeholder/mock data if left blank.

You can leave all fields blank to build a demo with mock data and fill in real values later by editing the code (see below).

---

## Getting the Demo URL

After Stage 6 completes, the pipeline shows a **"Pipeline complete"** panel with:

- **Live demo URL** — format: `https://demo-{clientname}.up.railway.app`
- **Demo guide** — a short usage doc for the demo

This URL is shareable directly with the client.

---

## Finding the GitHub Repo

Every deployed demo automatically gets its own GitHub repository. To find it:

1. The repo name follows the pattern: **`demo-{clientname}`**
   Example: `demo-renocomputerfix`

2. Go to the team's GitHub organization and search for the repo name, or navigate directly:
   `https://github.com/{ORG}/demo-{clientname}`

3. The repo contains all the generated demo files:
   - `main.py` — the Flask web app
   - `requirements.txt` — Python dependencies
   - `Procfile` — Railway start command
   - Any HTML templates (`templates/`)

---

## Editing the Project Manually

Railway auto-deploys from GitHub — any push to `main` triggers a new deployment.

### Option A — Edit in GitHub (quick fixes)

1. Open the repo on GitHub.
2. Click the file you want to edit (e.g., `main.py`).
3. Click the pencil icon (Edit).
4. Make your changes and commit directly to `main`.
5. Railway picks up the push and redeploys automatically — live in ~1–2 minutes.

### Option B — Clone and edit locally (larger changes)

```bash
git clone https://github.com/{ORG}/demo-{clientname}
cd demo-{clientname}

# Make your changes
# ...

git add .
git commit -m "Customize demo for client"
git push
```

Railway detects the push and redeploys. Check the Railway dashboard under the `demo-{clientname}` project for deployment status and logs.

---

## Viewing Previous Sessions

The home page shows a **Recent Sessions** list with all previous pipeline runs. Click any session to view:

- Stage outputs (classifier analysis, dependency list, matched solution, etc.)
- The deployed demo URL
- Current status (running, done, error, waiting)

---

## Tips & Troubleshooting

**Pipeline errors at a stage**
Read the error message shown in the stage panel — it usually points to a missing environment variable, a network issue, or a code generation problem. Contact the tool admin if it persists.

**Deployed app isn't loading**
Check the Railway dashboard → `demo-{clientname}` project → Deployments tab → View logs. Common causes: missing env var in the generated code, port binding issue.

**PDF not uploading / parsing incorrectly**
Make sure the PDF is text-based (not a scanned image). If in doubt, open the PDF and try selecting/copying text — if you can't, it's image-based. Export the transcript as `.txt` instead.

**Want to change the demo after deployment?**
Edit the GitHub repo (see above). Changes go live automatically via Railway.
