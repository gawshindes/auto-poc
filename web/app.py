"""
Web UI for the Demo Creation Pipeline.

Run locally:
    uvicorn web.app:app --reload --port 8000

Deploy (Railway):
    Procfile at repo root → web: uvicorn web.app:app --host 0.0.0.0 --port $PORT
"""

import asyncio
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

# Resolve project root (web/app.py → parent is project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "slack"))  # for deploy.py

# Load .env file for local development (no-op if already set or file missing)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from pipeline import (
    run_understand, run_design, run_build, run_guide,
    append_to_registry, read_transcript,
)
from storage import get_backend

app = FastAPI()

_backend = get_backend()

HTML_FILE = Path(__file__).parent / "index.html"

# Per-session state: asyncio queues for SSE, threading events for verbose pausing
_queues: dict[str, asyncio.Queue] = {}
_pause_events: dict[str, threading.Event] = {}
_input_values: dict[str, str] = {}
_loop: asyncio.AbstractEventLoop | None = None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _load_session(session_id: str) -> dict:
    session = _backend.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _save_session(session: dict) -> None:
    _backend.save_session(session)


def _new_session(transcript: str, mode: str = "auto", email: str = "") -> dict:
    session_id = str(uuid.uuid4())[:8]
    session = {
        "session_id": session_id,
        "mode": mode,
        "status": "idle",
        "current_stage": 0,
        "transcript": transcript,
        "email": email or None,
        "stage_1_understand": None,
        "stage_2_design": None,
        "stage_3_demo": None,
        "deploy_url": None,
        "stage_4_guide": None,
        "logs": [],
        "error": None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    _save_session(session)
    return session


# ---------------------------------------------------------------------------
# SSE helpers — bridge background thread → async generator
# ---------------------------------------------------------------------------

def _push(session_id: str, event: str, data: dict) -> None:
    """Called from background thread to push an SSE event."""
    if session_id not in _queues or _loop is None:
        return
    payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    asyncio.run_coroutine_threadsafe(_queues[session_id].put(payload), _loop)


def _log(session: dict, message: str) -> None:
    session["logs"].append(message)
    _save_session(session)
    _push(session["session_id"], "log", {"message": message})


# ---------------------------------------------------------------------------
# Pipeline runner (background thread) — 4-stage pipeline
# ---------------------------------------------------------------------------

def _run_pipeline_thread(session: dict) -> None:
    sid = session["session_id"]
    mode = session["mode"]
    verbose = mode == "verbose"

    def pause_if_verbose(label: str, result_data: dict = None) -> None:
        """In verbose mode, emit waiting event and block until /continue called."""
        if not verbose:
            return
        session["status"] = "waiting_continue"
        _save_session(session)
        _push(sid, "waiting", {"reason": "continue", "label": label, "result": result_data})
        _pause_events[sid].wait()
        _pause_events[sid].clear()
        session["status"] = "running"

    try:
        session["status"] = "running"
        _save_session(session)

        # Stage 1 — Understand
        session["current_stage"] = 1
        _log(session, "Stage 1 — Understand started")
        t = time.time()
        understand = run_understand(session["transcript"])
        session["stage_1_understand"] = understand
        _log(session, f"Stage 1 — Understand completed in {time.time()-t:.1f}s")
        _push(sid, "stage_done", {"stage": 1, "result": understand})
        _save_session(session)

        if understand.get("demo_decision") == "NO":
            session["status"] = "done"
            session["error"] = f"No demo needed: {understand.get('reason', '')}"
            _save_session(session)
            _push(sid, "done", {"message": session["error"]})
            return

        pause_if_verbose("Stage 1 complete — Understand", understand)

        # Stage 2 — Design
        session["current_stage"] = 2

        # Check if customer input needed BEFORE design
        ask_items = understand.get("dependencies", {}).get("ask_customer", [])
        customer_inputs = ""

        # Determine if we need customer input
        needs_input = ask_items and not understand.get("can_build_immediately")

        if ask_items:
            _log(session, f"Customer input items identified: {len(ask_items)}")

        # Collect customer inputs if needed (always stop for this, even in auto mode)
        if needs_input:
            session["status"] = "waiting_input"
            _save_session(session)
            _push(sid, "waiting", {"reason": "input", "items": ask_items})
            _pause_events[sid].wait()
            _pause_events[sid].clear()
            customer_inputs = _input_values.pop(sid, "")
            session["status"] = "running"

        # Append additional context provided at pipeline start
        additional_context = session.get("additional_context") or ""
        if additional_context:
            customer_inputs = (customer_inputs + "\n\n[Additional context from operator]:\n" + additional_context).strip() if customer_inputs else f"[Additional context from operator]:\n{additional_context}"

        # Merge resolved knowledge into customer inputs
        resolved = understand.get("dependencies", {}).get("resolved_by_knowledge", [])
        if resolved:
            resolved_text = "\n\n".join(
                f"[Auto-resolved] {r['dependency']}:\n{r['answer']}"
                for r in resolved
            )
            customer_inputs = (resolved_text + "\n\n" + customer_inputs).strip() if customer_inputs else resolved_text

        _log(session, "Stage 2 — Design started")
        t = time.time()
        design = run_design(understand, customer_inputs)
        session["stage_2_design"] = design
        _log(session, f"Stage 2 — Design completed in {time.time()-t:.1f}s")
        _push(sid, "stage_done", {"stage": 2, "result": design})
        _save_session(session)

        # Skip build if ALL components exist (deterministic Python check)
        matches = design.get("component_matches", [])
        if matches and all(m.get("action", "build_new").startswith("exists") for m in matches):
            existing_urls = [m["demo_url"] for m in matches if m.get("demo_url")]
            sdr_note = design.get("build_instruction", {}).get("sdr_note", "")
            msg = sdr_note or "All required components already exist in solutions library."
            _log(session, "Build skipped — all components exist in library.")
            session["status"] = "done"
            session["deploy_url"] = existing_urls[0] if existing_urls else None
            _save_session(session)
            _push(sid, "done", {"deploy_url": existing_urls[0] if existing_urls else "", "guide": msg})
            return

        pause_if_verbose("Stage 2 complete — Design", design)

        # Stage 3 — Build
        session["current_stage"] = 3
        _log(session, "Stage 3 — Build started (this takes 30-60s)")
        t = time.time()
        demo = run_build(design, customer_inputs)
        session["stage_3_demo"] = demo
        _log(session, f"Stage 3 — Build completed in {time.time()-t:.1f}s")
        _push(sid, "stage_done", {"stage": 3, "result": "Demo code generated"})
        _save_session(session)

        pause_if_verbose("Stage 3 complete — Demo built", {"lines": len(demo.splitlines())})

        # Deploy
        live_url = ""
        try:
            from deploy import deploy_demo, parse_demo_files, validate_demo_files, ValidationError
            _log(session, "Validating demo files...")
            files = parse_demo_files(demo)
            if "requirements.txt" not in files and "main.py" in files:
                files["requirements.txt"] = ""
            file_summary = ", ".join(f"{k}({len(v)}B)" for k, v in files.items())
            _log(session, f"Parsed files: {file_summary}")
            validate_demo_files(files)
            slug = re.sub(r"[^a-z0-9-]", "-",
                          understand.get("customer", {}).get("company", "demo").lower())
            _log(session, f"Deploying to Railway (slug: {slug})...")
            t = time.time()
            live_url = deploy_demo(demo, slug, classifier=understand)
            session["deploy_url"] = live_url
            _log(session, f"Deployed in {time.time()-t:.1f}s — {live_url}")
            _push(sid, "log", {"message": f"Deployed: {live_url}"})
            _save_session(session)
        except Exception as deploy_err:
            _log(session, f"Deploy skipped or failed: {deploy_err}")
            _push(sid, "log", {"message": f"Deploy error: {deploy_err}"})

        # Stage 4 — Guide
        session["current_stage"] = 4
        _log(session, "Stage 4 — Guide started")
        t = time.time()
        guide = run_guide(understand, demo, live_url=live_url)
        session["stage_4_guide"] = guide
        _log(session, f"Stage 4 — Guide completed in {time.time()-t:.1f}s")
        _push(sid, "stage_done", {"stage": 4, "result": guide})
        _save_session(session)

        # Registry
        new_id = append_to_registry(design, understand, deploy_url=live_url or None)
        if new_id:
            _log(session, f"Registry updated: {new_id}")

        # Email (auto mode only, if email provided)
        if mode == "auto" and session.get("email"):
            _send_email(session["email"], understand, live_url, guide)
            _log(session, f"Email sent to {session['email']}")

        session["status"] = "done"
        _save_session(session)
        _push(sid, "done", {"deploy_url": live_url, "guide": guide})

    except Exception as e:
        session["status"] = "error"
        session["error"] = str(e)
        _save_session(session)
        _push(sid, "error", {"message": str(e)})
    finally:
        # Sentinel to close SSE stream
        if sid in _queues and _loop:
            asyncio.run_coroutine_threadsafe(_queues[sid].put(None), _loop)


def _send_email(email: str, understand: dict, deploy_url: str, guide: str) -> None:
    resend_key = os.environ.get("RESEND_API_KEY", "")
    if not resend_key:
        return
    try:
        import resend
        resend.api_key = resend_key
        company = understand.get("customer", {}).get("company", "your customer")
        resend.Emails.send({
            "from": "demos@resend.dev",
            "to": [email],
            "subject": f"Demo ready — {company}",
            "html": (
                f"<h2>Your demo is live</h2>"
                f"<p><a href='{deploy_url}'>{deploy_url}</a></p>"
                f"<h3>Demo Guide</h3><pre style='white-space:pre-wrap'>{guide}</pre>"
            ),
        })
    except Exception:
        pass  # Email is best-effort


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _capture_loop():
    global _loop
    _loop = asyncio.get_event_loop()


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return HTML_FILE.read_text()


@app.post("/upload")
async def upload_transcript(file: UploadFile = File(...)):
    content = await file.read()
    suffix = Path(file.filename).suffix.lower()

    if suffix in (".txt", ".md"):
        transcript = content.decode("utf-8").strip()
    elif suffix == ".pdf":
        try:
            import pdfplumber, io as _io
            with pdfplumber.open(_io.BytesIO(content)) as pdf:
                parts = [p.extract_text() for p in pdf.pages if p.extract_text()]
            transcript = "\n".join(parts).strip()
            if not transcript:
                raise HTTPException(status_code=422, detail="PDF is empty or unreadable — try a .txt export")
        except ImportError:
            raise HTTPException(status_code=500, detail="pdfplumber not installed")
    else:
        raise HTTPException(status_code=422, detail="Unsupported file type — upload .txt or .pdf")

    session = _new_session(transcript)
    return {"session_id": session["session_id"]}


@app.post("/run/{session_id}")
async def run_pipeline(session_id: str, body: dict):
    session = _load_session(session_id)
    if session["status"] not in ("idle", "error"):
        raise HTTPException(status_code=409, detail="Pipeline already running or done")

    session["mode"] = body.get("mode", "auto")
    session["email"] = body.get("email") or None
    session["additional_context"] = body.get("additional_context", "").strip() or None
    session["status"] = "running"
    _save_session(session)

    _queues[session_id] = asyncio.Queue()
    _pause_events[session_id] = threading.Event()

    thread = threading.Thread(target=_run_pipeline_thread, args=(session,), daemon=True)
    thread.start()

    return {"started": True}


@app.get("/stream/{session_id}")
async def stream(session_id: str):
    if session_id not in _queues:
        # Session exists but no active stream — client reconnecting
        session = _load_session(session_id)
        if session["status"] == "done":
            async def done_stream():
                yield f"event: done\ndata: {json.dumps({'deploy_url': session.get('deploy_url',''), 'guide': session.get('stage_4_guide','')})}\n\n"
            return StreamingResponse(done_stream(), media_type="text/event-stream")
        # Create a new queue for re-connection; existing thread (if alive) won't use it
        _queues[session_id] = asyncio.Queue()

    async def event_generator():
        queue = _queues[session_id]
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=30)
                if msg is None:
                    break
                yield msg
        except asyncio.TimeoutError:
            yield "event: ping\ndata: {}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/continue/{session_id}")
async def continue_pipeline(session_id: str):
    if session_id not in _pause_events:
        raise HTTPException(status_code=404, detail="No active pipeline for this session")
    session = _load_session(session_id)
    session["status"] = "running"
    _save_session(session)
    _pause_events[session_id].set()
    return {"ok": True}


@app.post("/input/{session_id}")
async def submit_input(session_id: str, body: dict):
    if session_id not in _pause_events:
        raise HTTPException(status_code=404, detail="No active pipeline for this session")
    _input_values[session_id] = body.get("inputs", "")
    session = _load_session(session_id)
    session["status"] = "running"
    _save_session(session)
    _pause_events[session_id].set()
    return {"ok": True}


@app.get("/sessions")
async def list_sessions():
    return JSONResponse(_backend.list_sessions())


@app.post("/redeploy/{session_id}")
async def redeploy(session_id: str):
    session = _load_session(session_id)
    demo = session.get("stage_3_demo")
    understand = session.get("stage_1_understand") or {}
    if not demo:
        raise HTTPException(status_code=400, detail="No demo code found in session. Run the full pipeline first.")
    try:
        from deploy import deploy_demo
        # Railway project names have a 32 character limit. "demo-" is 5 chars.
        # We limit the slug to 25 chars and strip leading/trailing hyphens.
        raw_slug = understand.get("customer", {}).get("company", "demo").lower()
        slug = re.sub(r"[^a-z0-9-]", "-", raw_slug)
        slug = re.sub(r"-+", "-", slug).strip("-")[:25].strip("-")
        
        live_url = deploy_demo(demo, slug, classifier=understand)

        session["deploy_url"] = live_url
        _save_session(session)
        return JSONResponse({"deploy_url": live_url})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    session = _load_session(session_id)
    # Don't send full transcript/demo in status check — too large
    summary = {k: v for k, v in session.items() if k not in ("transcript", "stage_3_demo")}
    return JSONResponse(summary)


@app.get("/session/{session_id}/demo")
async def get_session_demo(session_id: str):
    session = _load_session(session_id)
    demo = session.get("stage_3_demo") or ""
    return JSONResponse({
        "session_id": session_id,
        "demo_length": len(demo),
        "demo_output": demo,
    })


@app.get("/debug/solutions")
async def debug_solutions():
    solutions = _backend.get_solutions()
    entries = solutions.get("solutions", [])
    return JSONResponse({
        "count": len(entries),
        "solutions": [{"id": s.get("id"), "name": s.get("name")} for s in entries],
    })


# ---------------------------------------------------------------------------
# Settings API — Team & Solutions management
# ---------------------------------------------------------------------------

TEAM_PATH = PROJECT_ROOT / "registry" / "team.json"


def _load_team() -> dict:
    if TEAM_PATH.exists():
        return json.loads(TEAM_PATH.read_text())
    return {"team": []}


def _save_team(data: dict) -> None:
    TEAM_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEAM_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


@app.get("/api/team")
async def get_team():
    return JSONResponse(_load_team())


@app.put("/api/team")
async def update_team(body: dict):
    """Replace team list. Body: {"team": ["Name 1", "Name 2", ...]}"""
    team = body.get("team")
    if not isinstance(team, list):
        raise HTTPException(status_code=422, detail="Body must have a 'team' array of name strings")
    data = _load_team()
    data["team"] = team
    _save_team(data)
    return JSONResponse({"ok": True, "count": len(team)})


@app.get("/api/solutions")
async def get_solutions():
    return JSONResponse(_backend.get_solutions())


@app.post("/api/solutions")
async def add_solution(body: dict):
    """Add a solution. Body: {name, description?, demo_type?, keywords?, stack?, source?, demo_url?, note?}"""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Solution 'name' is required")
    data = _backend.get_solutions()
    existing_ids = [s.get("id", "") for s in data.get("solutions", [])]
    max_num = 0
    for sid in existing_ids:
        parts = sid.split("_")
        if len(parts) == 2 and parts[1].isdigit():
            max_num = max(max_num, int(parts[1]))
    new_id = f"sol_{max_num + 1:03d}"
    entry = {
        "id": new_id,
        "name": name,
        "source": body.get("source", "manual"),
        "status": "built",
    }
    for field in ("description", "built_for", "demo_type", "keywords", "stack", "demo_url", "note"):
        if body.get(field):
            entry[field] = body[field]
    _backend.append_solution(entry, data)
    return JSONResponse({"ok": True, "id": new_id})


@app.put("/api/solutions/bulk")
async def bulk_replace_solutions(body: dict):
    """Replace all solutions from uploaded JSON. Body: {"solutions": [...]}"""
    solutions = body.get("solutions")
    if not isinstance(solutions, list):
        raise HTTPException(status_code=422, detail="Body must have a 'solutions' array")
    for i, s in enumerate(solutions):
        if not s.get("id"):
            s["id"] = f"sol_{i + 1:03d}"
        if not s.get("source"):
            s["source"] = "manual"
        if not s.get("status"):
            s["status"] = "built"
    data = _backend.get_solutions()
    data["solutions"] = solutions
    _backend.save_solutions(data)
    return JSONResponse({"ok": True, "count": len(solutions)})


@app.delete("/api/solutions/{solution_id}")
async def delete_solution(solution_id: str):
    data = _backend.get_solutions()
    solutions = data.get("solutions", [])
    before = len(solutions)
    data["solutions"] = [s for s in solutions if s.get("id") != solution_id]
    if len(data["solutions"]) == before:
        raise HTTPException(status_code=404, detail="Solution not found")
    _backend.save_solutions(data)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Admin API — protected by ADMIN_TOKEN Bearer header
# ---------------------------------------------------------------------------

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def _require_admin(request: Request) -> None:
    """Raise 401/403 if request lacks a valid ADMIN_TOKEN Bearer header."""
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_TOKEN env var is not set — admin endpoints are disabled",
        )
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid or missing admin token")


@app.delete("/admin/sessions")
async def delete_sessions(request: Request, keep_last: int = 0):
    _require_admin(request)
    sessions_dir = _backend._sessions_dir
    if not sessions_dir.exists():
        return JSONResponse({"ok": True, "deleted": 0, "kept": 0})
    all_files = sorted(sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if keep_last > 0:
        to_delete = all_files[:-keep_last] if len(all_files) > keep_last else []
        kept = len(all_files) - len(to_delete)
    else:
        to_delete = all_files
        kept = 0
    for f in to_delete:
        f.unlink()
    return JSONResponse({"ok": True, "deleted": len(to_delete), "kept": kept})


@app.delete("/admin/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    _require_admin(request)
    session_file = _backend._sessions_dir / f"{session_id}.json"
    if not session_file.exists():
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    session_file.unlink()
    return JSONResponse({"ok": True, "deleted": session_id})
