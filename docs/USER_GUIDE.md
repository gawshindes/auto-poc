# Demo Creation Tool — Internal User Guide

This guide explains how to use the web version of the demo creation tool end-to-end: from uploading a discovery call transcript to getting a live demo URL, finding the GitHub repo, and making manual edits.

---

## Accessing the Tool

Open the tool in your browser (use the Railway URL shared with your team). No login is required — it's an internal tool.

### Running Locally

```bash
git clone <repo>
cd demo-creation-agent
cp .env.example .env              # Add at least ANTHROPIC_API_KEY
cp registry/team.example.json registry/team.json  # Add your team names
pip install -r requirements.txt
uvicorn web.app:app --reload --port 8000
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

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

1. On the **Create Demo** tab, drag your transcript file onto the upload zone, or click anywhere in the zone to browse your files.
2. The file name appears in the bar below the drop zone once selected.
3. Changed your mind? Click **Change file** to swap it before starting.

---

## Step 3 — Choose a Mode

After uploading, you'll choose how the pipeline runs:

### Auto *(Recommended)*

All 4 stages run automatically without you having to click anything. The pipeline only pauses if it needs specific customer inputs (e.g., a customer's store URL or API key).

- Enter your email (optional) to receive a notification with the demo link when it's done.
- You can also add **Additional context** — notes about the customer, links, or instructions the pipeline should factor in.
- Best for most use cases — just upload and come back to the result.

### Verbose (Step by Step)

The pipeline pauses after each stage and shows you the full output. You click **Continue** to advance to the next stage.

- Useful when you want to inspect the AI's analysis before proceeding.

Click **Start Pipeline** once you've chosen a mode.

---

## What the Pipeline Does

The pipeline runs 4 AI stages to go from transcript to deployed demo:

| Stage | Name | What it does |
|-------|------|-------------|
| 1 | **Understand** | Reads the transcript, identifies the customer, classifies the demo type, resolves dependencies, checks for existing matching demos |
| 2 | **Design** | Creates a full demo spec: features, stack, skills needed, component matches |
| 3 | **Build + Deploy** | Writes complete demo code, verifies it, deploys to GitHub + Railway |
| 4 | **Guide** | Writes a short usage guide and talking points for the demo meeting |

### Solutions Matching (Stage 1)

The Understand stage automatically checks if we've already built a similar demo. If a match is found:
- The pipeline stops early — no need to build again
- You see a **"Match Found"** panel with the existing demo's name, reasoning, and a link
- Click **"View in Demo Library"** to see the matched demo's details

This saves time and LLM calls when a customer's need overlaps with a previous demo.

---

## Providing Customer Inputs (When Prompted)

If Stage 1 identifies inputs that only the customer can provide (e.g., their eBay store URL, webhook endpoint), the pipeline pauses and shows an input panel.

- **Required** fields (red tag) — the demo needs the customer's specific data to work correctly.
- **Optional** fields (gray tag) — the demo will use realistic mock data if left blank.

The pipeline tries to self-resolve as much as possible. Generic knowledge (industry SOPs, standard procedures, sample scenarios) is generated automatically — you'll only be asked for things that are truly customer-specific.

You can leave all fields blank to build a demo with mock data and fill in real values later by editing the code.

---

## Getting the Demo URL

After Stage 4 completes, the pipeline shows a **"Pipeline complete"** panel with:

- **Live demo URL** — format: `https://demo-{clientname}-production.up.railway.app`
- **Health check status** — whether the deployed app responded correctly
- **Demo guide** — talking points and usage instructions

This URL is shareable directly with the client.

---

## UI Tabs

The tool has four tabs:

### Create Demo
Upload a transcript and run the pipeline. Shows real-time progress via SSE (Server-Sent Events).

### Demo Library
Browse all deployed demos. Each demo card shows:
- Demo name, company, type
- Deploy URL with verification status
- Creation date

Click any demo to see full details: transcript, demo metadata, deployment info, and a link to the originating session.

**Delete a demo**: Open demo detail → click **Delete Demo** at the bottom. This soft-deletes it — the demo won't appear in the library or be matched to future sessions.

### Sessions
Browse all pipeline runs — active, waiting, done, or errored.

**Filter bar**: Filter by status (All / Running / Waiting / Done / Error) and search by company name or session ID.

**Session rows** show: status badge, company/demo name, stage progress, mode, time ago, and navigation chips (Open deployed demo, View demo in library).

**Click a session** to expand and see: error messages, stage outputs (Understand, Design, Guide), logs, and action buttons (Open in Pipeline View, View Demo, Redeploy).

### Team
Manage internal team members. The Understand stage uses this list to distinguish your team from the customer in transcripts.

---

## Finding the GitHub Repo

Every deployed demo automatically gets its own GitHub repository. To find it:

1. The repo name follows the pattern: **`demo-{clientname}`**
   Example: `demo-renocomputerfix`

2. Go to the team's GitHub organization and search for the repo name, or navigate directly:
   `https://github.com/{ORG}/demo-{clientname}`

3. The repo contains all the generated demo files:
   - `main.py` — the FastAPI/Flask web app
   - `requirements.txt` — Python dependencies
   - `Procfile` — Railway start command
   - Any HTML templates or static files

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

## Redeploying a Demo

If a deploy failed or you want to redeploy with the same code:

1. Go to the **Sessions** tab
2. Find the session and expand it
3. Click **Redeploy**

You can also use the **Retry Deploy** button on the pipeline view if the initial deploy failed.

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

**Solutions match is wrong**
If the tool matched an existing demo that isn't actually relevant, you can delete that demo from the Demo Library (open it → Delete Demo), then re-run the pipeline.
