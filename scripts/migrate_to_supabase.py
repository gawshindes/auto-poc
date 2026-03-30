"""
Migrate production data from Railway JSON exports into Supabase.

Usage:
    python scripts/migrate_to_supabase.py

Reads from:
    /tmp/railway-export/sessions/*.json   — full session data
    /tmp/railway-export/solutions.json    — solutions registry
    /tmp/railway-export/team.json         — team members

Requires SUPABASE_URL and SUPABASE_KEY in .env

Schema: simplified 4-table model (sessions, demos, session_logs, team_members + slack_state).
Transcripts are inline on sessions; deploy info is inline on demos.
"""

import json
import os
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from supabase import create_client

EXPORT_DIR = Path("/tmp/railway-export")


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set")
        sys.exit(1)

    client = create_client(url, key)
    print(f"Connected to Supabase: {url}")

    # --- 1. Team members ---
    team_file = EXPORT_DIR / "team.json"
    if team_file.exists():
        team_data = json.loads(team_file.read_text())
        names = team_data.get("team", [])
        if names:
            client.table("team_members").delete().neq("id", 0).execute()
            for i in range(0, len(names), 50):
                batch = [{"name": n} for n in names[i:i+50]]
                client.table("team_members").insert(batch).execute()
            print(f"  Team: {len(names)} members imported")
    else:
        print("  Team: skipped (no file)")

    # --- 2. Solutions → demos (with deploy info inline) ---
    solutions_file = EXPORT_DIR / "solutions.json"
    if solutions_file.exists():
        sol_data = json.loads(solutions_file.read_text())
        solutions = sol_data.get("solutions", [])
        for sol in solutions:
            demo_id = _gen_id("demo")
            deploy_url = sol.get("demo_url")

            demo = {
                "id": demo_id,
                "source": sol.get("source", "manual"),
                "company": sol.get("built_for"),
                "demo_type": sol.get("demo_type"),
                "use_case": sol.get("use_case"),
                "name": sol.get("name"),
                "description": sol.get("description"),
                "keywords": json.dumps(sol.get("keywords")) if sol.get("keywords") else None,
                "stack": sol.get("stack"),
                "deploy_url": deploy_url,
                "health_check_passed": 1 if deploy_url else 0,
                "is_reusable": 1,
                "is_active": 1,
            }
            client.table("demos").upsert(demo).execute()

        print(f"  Solutions: {len(solutions)} imported as demos")
    else:
        print("  Solutions: skipped (no file)")

    # --- 3. Sessions → sessions + demos + logs ---
    sessions_dir = EXPORT_DIR / "sessions"
    if not sessions_dir.exists():
        print("  Sessions: skipped (no directory)")
        return

    session_files = sorted(sessions_dir.glob("*.json"))
    imported = 0

    for sf in session_files:
        old_session = json.loads(sf.read_text())
        old_sid = old_session.get("session_id", sf.stem)

        # Extract transcript
        transcript_text = old_session.get("transcript", "")
        understand = old_session.get("stage_1_understand") or {}
        customer = understand.get("customer", {})

        if not transcript_text:
            transcript_text = (
                f"[Transcript not available — migrated from Railway]\n"
                f"Company: {customer.get('company', 'Unknown')}\n"
                f"Contact: {customer.get('name', 'Unknown')}\n"
                f"Industry: {customer.get('industry', 'Unknown')}"
            )

        sess_id = f"sess_{old_sid}"
        demo_id = _gen_id("demo")

        # Session (transcript inline)
        client.table("sessions").upsert({
            "id": sess_id,
            "source": "web",
            "transcript": transcript_text,
            "email": old_session.get("email"),
            "status": old_session.get("status", "done"),
            "current_stage": old_session.get("current_stage", 0),
            "mode": old_session.get("mode", "auto"),
            "error": old_session.get("error"),
            "stage_1_understand": json.dumps(understand) if understand else None,
            "stage_2_design": json.dumps(old_session.get("stage_2_design")) if old_session.get("stage_2_design") else None,
            "stage_3_demo": old_session.get("stage_3_demo"),
            "stage_4_guide": old_session.get("stage_4_guide"),
            "created_at": old_session.get("created_at"),
            "updated_at": old_session.get("updated_at"),
        }).execute()

        # Demo (deploy info inline)
        design = old_session.get("stage_2_design") or {}
        demo_spec = design.get("demo_spec", {})
        deploy_url = old_session.get("deploy_url")

        client.table("demos").upsert({
            "id": demo_id,
            "session_id": sess_id,
            "source": "web",
            "company": customer.get("company"),
            "demo_type": understand.get("demo_type"),
            "use_case": demo_spec.get("use_case"),
            "name": demo_spec.get("name"),
            "description": demo_spec.get("description"),
            "keywords": json.dumps(demo_spec.get("keywords")) if demo_spec.get("keywords") else None,
            "stack": demo_spec.get("stack"),
            "deploy_url": deploy_url,
            "github_repo": old_session.get("github_repo"),
            "health_check_passed": 1 if deploy_url else 0,
            "created_at": old_session.get("created_at"),
            "updated_at": old_session.get("updated_at"),
        }).execute()

        # Logs
        old_logs = old_session.get("logs", [])
        if old_logs:
            log_entries = []
            for msg in old_logs:
                if isinstance(msg, str):
                    log_entries.append({
                        "session_id": sess_id,
                        "level": "info",
                        "message": msg,
                    })
                elif isinstance(msg, dict):
                    log_entries.append({
                        "session_id": sess_id,
                        "level": msg.get("level", "info"),
                        "stage": msg.get("stage"),
                        "message": msg.get("message", str(msg)),
                        "timestamp": msg.get("timestamp"),
                    })
            if log_entries:
                for i in range(0, len(log_entries), 50):
                    client.table("session_logs").insert(log_entries[i:i+50]).execute()

        imported += 1
        company = customer.get("company", "?")
        print(f"    {old_sid} → {sess_id} ({company})")

    print(f"  Sessions: {imported} imported")

    # --- 4. Record migrations as applied ---
    client.table("schema_migrations").upsert([
        {"version": 1, "name": "001_initial_pg.sql"},
        {"version": 2, "name": "002_team_pg.sql"},
        {"version": 3, "name": "003_session_transcript_pg.sql"},
    ]).execute()
    print("\n  Migration versions recorded.")
    print("\nDone!")


if __name__ == "__main__":
    main()
