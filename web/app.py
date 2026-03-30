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
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

# Resolve project root (web/app.py → parent is project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# Load .env file for local development (no-op if already set or file missing)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from pipeline import (
    run_understand, run_design, run_build, run_verify, run_guide,
    read_transcript,
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
# ID generators
# ---------------------------------------------------------------------------

def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def _load_session(session_id: str) -> dict:
    session = _backend.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _save_session(session: dict) -> None:
    _backend.save_session(session)


def _new_session(transcript_text: str, mode: str = "auto",
                 email: str = "", additional_context: str = "",
                 source: str = "web") -> dict:
    """Create a session with transcript data inline. Returns session.
    Demo record is only created after successful deployment."""
    sess_id = _gen_id("sess")

    session = {
        "id": sess_id,
        "source": source,
        "transcript": transcript_text,
        "additional_context": additional_context or None,
        "email": email or None,
        "mode": mode,
        "status": "idle",
        "current_stage": 0,
    }
    _backend.save_session(session)

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


def _log(session: dict, message: str, level: str = "info",
         stage: int | None = None) -> None:
    sid = session["id"]
    _backend.append_log(sid, message, level=level, stage=stage)
    _push(sid, "log", {"message": message})


# ---------------------------------------------------------------------------
# Pipeline runner (background thread) — 4-stage pipeline
# ---------------------------------------------------------------------------

def _run_pipeline_thread(session: dict, demo: dict) -> None:
    sid = session["id"]
    demo_id = demo["id"]
    mode = session["mode"]
    verbose = mode == "verbose"

    def pause_if_verbose(label: str, result_data: dict = None) -> None:
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
        _log(session, "Stage 1 — Understand started", stage=1)
        t = time.time()
        understand = run_understand(session["transcript"])
        session["stage_1_understand"] = understand
        _log(session, f"Stage 1 — Understand completed in {time.time()-t:.1f}s", stage=1)
        _push(sid, "stage_done", {"stage": 1, "result": understand})
        _save_session(session)

        # Customer info lives in stage_1_understand JSON on the session
        customer = understand.get("customer", {})

        if understand.get("demo_decision") == "NO":
            session["status"] = "done"
            session["error"] = f"No demo needed: {understand.get('reason', '')}"
            _save_session(session)
            _push(sid, "done", {"message": session["error"]})
            return

        # --- Solutions match (checked in Understand) ---
        match = understand.get("existing_solution_match") or {}
        if match.get("matched"):
            matched_name = match.get("solution_name", "existing solution")
            deploy_url = match.get("deploy_url") or ""
            solution_id = match.get("solution_id") or ""
            reasoning = match.get("match_reasoning") or ""
            msg = f"Matched existing solution: {matched_name}"
            _log(session, msg, stage=1)
            session["status"] = "done"
            _save_session(session)
            _push(sid, "matched", {
                "solution_name": matched_name,
                "solution_id": solution_id,
                "deploy_url": deploy_url,
                "match_reasoning": reasoning,
            })
            return

        pause_if_verbose("Stage 1 complete — Understand", understand)

        # Stage 2 — Design
        session["current_stage"] = 2

        # Check if customer input needed before design
        ask_items = understand.get("dependencies", {}).get("ask_customer", [])
        customer_inputs = ""

        needs_input = bool(ask_items) and not understand.get("can_build_immediately")

        if ask_items:
            blocking_count = sum(
                1 for item in ask_items
                if isinstance(item, dict) and item.get("urgency", "").lower().startswith("needed")
            )
            _log(session, f"Customer input items: {len(ask_items)}, blocking: {blocking_count}, can_build_immediately: {understand.get('can_build_immediately')}", stage=2)

        if needs_input:
            session["status"] = "waiting_input"
            _save_session(session)
            _push(sid, "waiting", {"reason": "input", "items": ask_items})
            _pause_events[sid].wait()
            _pause_events[sid].clear()
            customer_inputs = _input_values.pop(sid, "")
            session["status"] = "running"

        # Append additional context
        additional_context = session.get("additional_context") or ""
        if additional_context:
            if customer_inputs:
                customer_inputs += f"\n\n[Additional context from operator]:\n{additional_context}"
            else:
                customer_inputs = f"[Additional context from operator]:\n{additional_context}"

        # Merge resolved knowledge
        resolved = understand.get("dependencies", {}).get("resolved_by_knowledge", [])
        if resolved:
            resolved_text = "\n\n".join(
                f"[Auto-resolved] {r['dependency']}:\n{r['answer']}"
                for r in resolved
            )
            customer_inputs = (resolved_text + "\n\n" + customer_inputs).strip() if customer_inputs else resolved_text

        _log(session, "Stage 2 — Design started", stage=2)
        t = time.time()
        design = run_design(understand, customer_inputs)
        session["stage_2_design"] = design
        _log(session, f"Stage 2 — Design completed in {time.time()-t:.1f}s", stage=2)
        _push(sid, "stage_done", {"stage": 2, "result": design})
        _save_session(session)

        # Enrich in-memory demo dict with info from design (not saved to DB yet)
        demo_spec = design.get("demo_spec", {})
        demo["demo_type"] = understand.get("demo_type")
        demo["use_case"] = demo_spec.get("use_case") or understand.get("use_case")
        demo["name"] = demo_spec.get("name") or f"{customer.get('company', 'Demo')} — {understand.get('demo_type', 'custom')}"
        demo["description"] = demo_spec.get("description") or understand.get("proposed_solution")
        demo["keywords"] = demo_spec.get("keywords")
        demo["stack"] = demo_spec.get("stack")
        demo["skills_used"] = demo_spec.get("required_skills")

        pause_if_verbose("Stage 2 complete — Design", design)

        # Stage 3 — Build
        session["current_stage"] = 3
        _log(session, "Stage 3 — Build started (this takes 30-60s)", stage=3)
        t = time.time()
        demo_code = run_build(design, customer_inputs)
        session["stage_3_demo"] = demo_code
        _log(session, f"Stage 3 — Build completed in {time.time()-t:.1f}s", stage=3)
        _push(sid, "stage_done", {"stage": 3, "result": "Demo code generated"})
        _save_session(session)

        pause_if_verbose("Stage 3 complete — Demo built", {"lines": len(demo_code.splitlines())})

        # --- Verification Agent (between Build and Deploy) ---
        from deploy import (
            deploy_demo, parse_demo_files, analyze_demo_files,
            DeployResult, ValidationReport,
        )

        _log(session, "Parsing and analyzing demo files...", stage=3)
        files = parse_demo_files(demo_code)
        if "requirements.txt" not in files and "main.py" in files:
            files["requirements.txt"] = ""
        file_summary = ", ".join(f"{k}({len(v)}B)" for k, v in files.items())
        _log(session, f"Parsed files: {file_summary}", stage=3)

        report = analyze_demo_files(files)

        if report.errors:
            if report.fixable:
                _log(session, f"Found {len(report.errors)} fixable issue(s), running verification agent...", stage=3)
                session["status"] = "verifying"
                _save_session(session)
                _push(sid, "log", {"message": f"Fixing {len(report.errors)} issue(s)..."})

                fixed_code = run_verify(demo_code, report.errors)

                # Merge fixed files back into original
                fixed_files = parse_demo_files(fixed_code)
                for fname, fcontent in fixed_files.items():
                    files[fname] = fcontent.strip()

                # Re-analyze
                report2 = analyze_demo_files(files)
                if report2.errors:
                    error_msg = "Verification agent could not fix all issues:\n" + "\n".join(f"  - {e}" for e in report2.errors)
                    _log(session, error_msg, level="error", stage=3)
                    session["status"] = "error"
                    session["error"] = error_msg
                    _save_session(session)
                    _push(sid, "error", {"message": error_msg})
                    return

                _log(session, "Verification agent fixed all issues.", stage=3)
                # Update demo_code with fixed version
                demo_code = fixed_code
                session["stage_3_demo"] = demo_code
                _save_session(session)
            else:
                error_msg = "Pre-deploy check failed (unfixable):\n" + "\n".join(f"  - {e}" for e in report.errors)
                _log(session, error_msg, level="error", stage=3)
                session["status"] = "error"
                session["error"] = error_msg
                _save_session(session)
                _push(sid, "error", {"message": error_msg})
                return

        if report.warnings:
            for w in report.warnings:
                _log(session, f"Warning: {w}", level="warn", stage=3)

        # --- Deploy ---
        live_url = ""
        deploy_result = None
        try:
            slug = re.sub(r"[^a-z0-9-]", "-",
                          customer.get("company", "demo").lower())

            session["status"] = "deploying"
            _log(session, f"Deploying to Railway (slug: {slug})...", stage=3)
            _save_session(session)
            t = time.time()

            deploy_result = deploy_demo(
                demo_code, slug,
                classifier=understand,
                design_spec=design,
                files=files,
            )
            live_url = deploy_result.url

            # Deploy succeeded — NOW save demo to DB (it's a real demo now)
            demo["session_id"] = session["id"]
            demo["deploy_url"] = live_url
            demo["github_repo"] = deploy_result.github_repo
            demo["health_check_passed"] = deploy_result.verified
            demo["company"] = customer.get("company")
            _backend.save_demo(demo)

            _log(session, f"Deployed in {time.time()-t:.1f}s — {live_url}", stage=3)
            if deploy_result.verified:
                _log(session, "Health check passed.", stage=3)
            else:
                _log(session, f"Health check failed: {deploy_result.error}", level="warn", stage=3)
            _push(sid, "log", {"message": f"Deployed: {live_url}"})

        except Exception as deploy_err:
            _log(session, f"Deploy failed: {deploy_err}", level="error", stage=3)
            _push(sid, "log", {"message": f"Deploy error: {deploy_err}"})

        # Stage 4 — Guide
        session["current_stage"] = 4
        _log(session, "Stage 4 — Guide started", stage=4)
        t = time.time()
        guide = run_guide(understand, demo_code, live_url=live_url)
        session["stage_4_guide"] = guide
        _log(session, f"Stage 4 — Guide completed in {time.time()-t:.1f}s", stage=4)
        _push(sid, "stage_done", {"stage": 4, "result": guide})
        _save_session(session)

        # Email (auto mode only) — read from session
        email_addr = session.get("email")
        if mode == "auto" and email_addr:
            _send_email(email_addr, understand, live_url, guide)
            _log(session, f"Email sent to {email_addr}", stage=4)

        session["status"] = "done"
        _save_session(session)
        _push(sid, "done", {"deploy_url": live_url, "guide": guide})

    except Exception as e:
        session["status"] = "error"
        session["error"] = str(e)
        _save_session(session)
        _push(sid, "error", {"message": str(e)})
    finally:
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
        pass


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
        transcript_text = content.decode("utf-8").strip()
    elif suffix == ".pdf":
        try:
            import pdfplumber, io as _io
            with pdfplumber.open(_io.BytesIO(content)) as pdf:
                parts = [p.extract_text() for p in pdf.pages if p.extract_text()]
            transcript_text = "\n".join(parts).strip()
            if not transcript_text:
                raise HTTPException(status_code=422, detail="PDF is empty or unreadable — try a .txt export")
        except ImportError:
            raise HTTPException(status_code=500, detail="pdfplumber not installed")
    else:
        raise HTTPException(status_code=422, detail="Unsupported file type — upload .txt or .pdf")

    session = _new_session(transcript_text)
    return {"session_id": session["id"]}


@app.post("/run/{session_id}")
async def run_pipeline(session_id: str, body: dict):
    session = _load_session(session_id)
    if session["status"] not in ("idle", "error"):
        raise HTTPException(status_code=409, detail="Pipeline already running or done")

    session["mode"] = body.get("mode", "auto")
    session["status"] = "running"

    # Store email and additional context on session
    email = body.get("email", "").strip()
    if email:
        session["email"] = email
    additional_context = body.get("additional_context", "").strip()
    if additional_context:
        session["additional_context"] = additional_context

    _save_session(session)

    # Build in-memory demo dict — only saved to DB after successful deploy
    demo = {
        "id": _gen_id("demo"),
        "source": session.get("source", "web"),
    }

    _queues[session_id] = asyncio.Queue()
    _pause_events[session_id] = threading.Event()

    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(session, demo),
        daemon=True,
    )
    thread.start()

    return {"started": True}


@app.get("/stream/{session_id}")
async def stream(session_id: str):
    if session_id not in _queues:
        session = _load_session(session_id)
        if session["status"] == "done":
            deploy_url = ""
            demo = _backend.get_demo_by_session_id(session_id)
            if demo:
                deploy_url = demo.get("deploy_url", "")
            async def done_stream():
                yield f"event: done\ndata: {json.dumps({'deploy_url': deploy_url, 'guide': session.get('stage_4_guide','')})}\n\n"
            return StreamingResponse(done_stream(), media_type="text/event-stream")
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
    sessions = _backend.list_sessions()
    # Backward compat: alias id → session_id for frontend
    for s in sessions:
        s["session_id"] = s["id"]
    return JSONResponse(sessions)


@app.post("/redeploy/{session_id}")
async def redeploy(session_id: str):
    session = _load_session(session_id)
    demo_code = session.get("stage_3_demo")
    understand = session.get("stage_1_understand") or {}
    if not demo_code:
        raise HTTPException(status_code=400, detail="No demo code found in session. Run the full pipeline first.")

    design = session.get("stage_2_design") or {}

    try:
        from deploy import deploy_demo, DeployResult

        raw_slug = understand.get("customer", {}).get("company", "demo").lower()
        slug = re.sub(r"[^a-z0-9-]", "-", raw_slug)
        slug = re.sub(r"-+", "-", slug).strip("-")[:25].strip("-")

        deploy_result = deploy_demo(
            demo_code, slug,
            classifier=understand,
            design_spec=design,
        )

        # Find existing demo or create a new one
        demo = _backend.get_demo_by_session_id(session_id)
        if not demo:
            demo_spec = design.get("demo_spec", {})
            customer = understand.get("customer", {})
            demo = {
                "id": _gen_id("demo"),
                "session_id": session_id,
                "source": "web",
                "company": customer.get("company"),
                "demo_type": understand.get("demo_type"),
                "use_case": demo_spec.get("use_case") or understand.get("use_case"),
                "name": demo_spec.get("name"),
                "description": demo_spec.get("description"),
                "keywords": demo_spec.get("keywords"),
                "stack": demo_spec.get("stack"),
                "skills_used": demo_spec.get("required_skills"),
            }

        demo["deploy_url"] = deploy_result.url
        demo["github_repo"] = deploy_result.github_repo
        demo["health_check_passed"] = deploy_result.verified
        _backend.save_demo(demo)

        return JSONResponse({
            "deploy_url": deploy_result.url,
            "verified": deploy_result.verified,
            "error": deploy_result.error,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    session = _load_session(session_id)
    summary = {k: v for k, v in session.items() if k not in ("stage_3_demo",)}
    summary["session_id"] = session["id"]  # backward compat

    # Include deploy info from demo
    demo = _backend.get_demo_by_session_id(session_id)
    if demo:
        summary["demo_id"] = demo["id"]
        summary["deploy_url"] = demo.get("deploy_url")
        summary["health_check_passed"] = demo.get("health_check_passed")
    return JSONResponse(summary)


@app.get("/session/{session_id}/demo")
async def get_session_demo(session_id: str):
    session = _load_session(session_id)
    demo_code = session.get("stage_3_demo") or ""
    return JSONResponse({
        "session_id": session_id,
        "demo_length": len(demo_code),
        "demo_output": demo_code,
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

@app.get("/api/team")
async def get_team():
    return JSONResponse({"team": _backend.get_team()})


@app.put("/api/team")
async def update_team(body: dict):
    """Replace team list. Body: {"team": ["Name 1", "Name 2", ...]}"""
    team = body.get("team")
    if not isinstance(team, list):
        raise HTTPException(status_code=422, detail="Body must have a 'team' array of name strings")
    _backend.save_team(team)
    return JSONResponse({"ok": True, "count": len(team)})


@app.get("/api/solutions")
async def get_solutions():
    return JSONResponse(_backend.get_solutions())


@app.post("/api/solutions")
async def add_solution(body: dict):
    """Add a manual solution (demo record with is_reusable=True)."""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Solution 'name' is required")

    demo_id = _gen_id("demo")
    deploy_url = body.get("demo_url") or body.get("deploy_url")
    demo = {
        "id": demo_id,
        "source": "manual",
        "name": name,
        "description": body.get("description"),
        "demo_type": body.get("demo_type"),
        "keywords": body.get("keywords"),
        "stack": body.get("stack"),
        "deploy_url": deploy_url,
        "health_check_passed": bool(deploy_url),
        "is_reusable": True,
        "is_active": True,
    }
    _backend.save_demo(demo)

    return JSONResponse({"ok": True, "id": demo_id})


@app.delete("/api/solutions/{solution_id}")
async def delete_solution(solution_id: str):
    """Soft-delete a solution by setting is_active=False on the demo."""
    demo = _backend.get_demo(solution_id)
    if not demo:
        raise HTTPException(status_code=404, detail="Solution not found")
    demo["is_active"] = False
    _backend.save_demo(demo)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Demos API
# ---------------------------------------------------------------------------

@app.get("/api/demos")
async def list_demos():
    return JSONResponse(_backend.list_demos(filters={"is_active": True}))


@app.get("/api/demos/{demo_id}")
async def get_demo(demo_id: str):
    demo = _backend.get_demo(demo_id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")

    # Enrich from session if linked
    if demo.get("session_id"):
        session = _backend.get_session(demo["session_id"])
        if session:
            understand = session.get("stage_1_understand") or {}
            customer = understand.get("customer", {})
            demo["contact_name"] = customer.get("name")
            demo["contact_email"] = customer.get("email")
            demo["industry"] = customer.get("industry")
            demo["meeting_link"] = session.get("meeting_link")
            demo["additional_context"] = session.get("additional_context")
            demo["transcript_content"] = session.get("transcript")
            demo["transcript_source"] = session.get("source")
            demo["transcript_created_at"] = session.get("created_at")
            demo["sessions"] = [{"session_id": session["id"], **{
                k: session[k] for k in ("id", "status", "current_stage", "mode", "created_at", "updated_at")
            }}]
    if "sessions" not in demo:
        demo["sessions"] = []

    return JSONResponse(demo)


@app.patch("/api/demos/{demo_id}")
async def update_demo(demo_id: str, body: dict):
    """Update specific fields on a demo (e.g. is_reusable toggle)."""
    demo = _backend.get_demo(demo_id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    for field in ("is_reusable", "is_active", "name", "description"):
        if field in body:
            demo[field] = body[field]
    _backend.save_demo(demo)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Admin API — protected by ADMIN_TOKEN Bearer header
# ---------------------------------------------------------------------------

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def _require_admin(request: Request) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_TOKEN env var is not set — admin endpoints are disabled",
        )
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid or missing admin token")
