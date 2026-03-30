"""
Supabase backend — production use via STORAGE_BACKEND=supabase.

Requires:
  - SUPABASE_URL: your Supabase project URL
  - SUPABASE_KEY: your Supabase service_role key (NOT anon key — needs write access)
  - pip install supabase

Tables must be created via the migration SQL in storage/migrations/.
Run the SQL in Supabase SQL Editor or use the migrate command.
"""

import json
import os
from datetime import datetime, timezone

from storage import StorageBackend, MIGRATIONS_DIR


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_dumps(obj) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj)


def _json_loads(s, default=None):
    if s is None:
        return default
    if isinstance(s, (list, dict)):
        return s
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


class SupabaseBackend(StorageBackend):
    def __init__(self):
        try:
            from supabase import create_client
        except ImportError:
            raise RuntimeError(
                "supabase package not installed. Run: pip install supabase"
            )

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set for Supabase backend"
            )
        self._client = create_client(url, key)
        self.run_migrations()

    # -- Migrations ----------------------------------------------------------

    def run_migrations(self) -> None:
        try:
            result = self._client.table("schema_migrations").select("version").execute()
            applied = {row["version"] for row in result.data}
        except Exception:
            print(
                "WARNING: schema_migrations table not found in Supabase. "
                "Run the SQL files in storage/migrations/ via the Supabase SQL Editor."
            )
            return

        # Only check *_pg.sql files for Postgres/Supabase
        migration_files = sorted(MIGRATIONS_DIR.glob("*_pg.sql"))
        pending = []
        for f in migration_files:
            version = int(f.name.split("_")[0])
            if version not in applied:
                pending.append(f.name)

        if pending:
            print(
                f"WARNING: {len(pending)} pending migration(s) for Supabase: "
                f"{', '.join(pending)}. Run them via the Supabase SQL Editor."
            )

    # -- Demos ---------------------------------------------------------------

    def save_demo(self, demo: dict) -> None:
        self._client.table("demos").upsert({
            "id": demo["id"],
            "session_id": demo.get("session_id"),
            "source": demo.get("source", "web"),
            "company": demo.get("company"),
            "demo_type": demo.get("demo_type"),
            "use_case": demo.get("use_case"),
            "name": demo.get("name"),
            "description": demo.get("description"),
            "keywords": _json_dumps(demo.get("keywords")),
            "stack": demo.get("stack"),
            "skills_used": _json_dumps(demo.get("skills_used")),
            "deploy_url": demo.get("deploy_url"),
            "github_repo": demo.get("github_repo"),
            "health_check_passed": 1 if demo.get("health_check_passed") else 0,
            "is_reusable": 1 if demo.get("is_reusable") else 0,
            "is_active": 1 if demo.get("is_active", True) else 0,
            "created_at": demo.get("created_at", _now()),
            "updated_at": _now(),
        }).execute()

    def get_demo(self, demo_id: str) -> dict | None:
        result = (
            self._client.table("demos")
            .select("*")
            .eq("id", demo_id)
            .execute()
        )
        if not result.data:
            return None
        d = result.data[0]
        d["keywords"] = _json_loads(d.get("keywords"), [])
        d["skills_used"] = _json_loads(d.get("skills_used"), [])
        d["health_check_passed"] = bool(d.get("health_check_passed"))
        return d

    def get_demo_by_session_id(self, session_id: str) -> dict | None:
        result = (
            self._client.table("demos")
            .select("*")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        d = result.data[0]
        d["keywords"] = _json_loads(d.get("keywords"), [])
        d["skills_used"] = _json_loads(d.get("skills_used"), [])
        d["health_check_passed"] = bool(d.get("health_check_passed"))
        return d

    def list_demos(self, filters: dict | None = None) -> list[dict]:
        query = self._client.table("demos").select("*")
        if filters:
            if "is_reusable" in filters:
                query = query.eq("is_reusable", 1 if filters["is_reusable"] else 0)
            if "is_active" in filters:
                query = query.eq("is_active", 1 if filters["is_active"] else 0)
            if "source" in filters:
                query = query.eq("source", filters["source"])
        result = query.order("updated_at", desc=True).execute()

        demos = []
        for d in result.data:
            d["keywords"] = _json_loads(d.get("keywords"), [])
            d["skills_used"] = _json_loads(d.get("skills_used"), [])
            d["health_check_passed"] = bool(d.get("health_check_passed"))
            demos.append(d)
        return demos

    def get_solutions(self) -> dict:
        """Return all active demos as solutions for matching."""
        result = (
            self._client.table("demos")
            .select("*")
            .eq("is_active", 1)
            .execute()
        )

        solutions = []
        for d in result.data:
            solutions.append({
                "id": d["id"],
                "name": d.get("name"),
                "description": d.get("description"),
                "demo_type": d.get("demo_type"),
                "use_case": d.get("use_case"),
                "keywords": _json_loads(d.get("keywords"), []),
                "stack": d.get("stack"),
                "skills_used": _json_loads(d.get("skills_used"), []),
                "source": d.get("source"),
                "built_for": d.get("company"),
                "deploy_url": d.get("deploy_url"),
                "status": "built",
            })

        return {
            "version": "1.0",
            "last_updated": _now()[:10],
            "solutions": solutions,
        }

    # -- Sessions ------------------------------------------------------------

    def save_session(self, session: dict) -> None:
        self._client.table("sessions").upsert({
            "id": session["id"],
            "source": session.get("source", "web"),
            "transcript": session.get("transcript"),
            "meeting_link": session.get("meeting_link"),
            "additional_context": session.get("additional_context"),
            "email": session.get("email"),
            "status": session.get("status", "idle"),
            "current_stage": session.get("current_stage", 0),
            "mode": session.get("mode", "auto"),
            "error": session.get("error"),
            "stage_1_understand": _json_dumps(session.get("stage_1_understand")),
            "stage_2_design": _json_dumps(session.get("stage_2_design")),
            "stage_3_demo": session.get("stage_3_demo"),
            "stage_4_guide": session.get("stage_4_guide"),
            "created_at": session.get("created_at", _now()),
            "updated_at": _now(),
        }).execute()

    def get_session(self, session_id: str) -> dict | None:
        result = (
            self._client.table("sessions")
            .select("*")
            .eq("id", session_id)
            .execute()
        )
        if not result.data:
            return None
        d = result.data[0]
        d["stage_1_understand"] = _json_loads(d.get("stage_1_understand"))
        d["stage_2_design"] = _json_loads(d.get("stage_2_design"))
        d["logs"] = self.get_logs(session_id)
        return d

    def list_sessions(self) -> list[dict]:
        result = (
            self._client.table("sessions")
            .select("id, source, status, current_stage, mode, created_at, updated_at")
            .order("updated_at", desc=True)
            .execute()
        )

        # Batch-fetch demos for all sessions
        session_ids = [s["id"] for s in result.data]
        demo_map = {}
        if session_ids:
            demo_result = (
                self._client.table("demos")
                .select("session_id, id, name, company, deploy_url, health_check_passed")
                .in_("session_id", session_ids)
                .execute()
            )
            for d in demo_result.data:
                demo_map[d["session_id"]] = d

        sessions = []
        for s in result.data:
            demo = demo_map.get(s["id"], {})
            sessions.append({
                "id": s["id"],
                "source": s.get("source"),
                "status": s.get("status"),
                "current_stage": s.get("current_stage", 0),
                "mode": s.get("mode"),
                "demo_id": demo.get("id"),
                "demo_name": demo.get("name"),
                "company": demo.get("company"),
                "deploy_url": demo.get("deploy_url"),
                "health_check_passed": bool(demo.get("health_check_passed", False)),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
            })
        return sessions

    # -- Session logs --------------------------------------------------------

    def append_log(self, session_id: str, message: str,
                   level: str = "info", stage: int | None = None) -> None:
        self._client.table("session_logs").insert({
            "session_id": session_id,
            "timestamp": _now(),
            "level": level,
            "stage": stage,
            "message": message,
        }).execute()

    def get_logs(self, session_id: str) -> list[dict]:
        result = (
            self._client.table("session_logs")
            .select("timestamp, level, stage, message")
            .eq("session_id", session_id)
            .order("id")
            .execute()
        )
        return result.data

    # -- Team ----------------------------------------------------------------

    def get_team(self) -> list[str]:
        result = (
            self._client.table("team_members")
            .select("name")
            .order("id")
            .execute()
        )
        return [r["name"] for r in result.data]

    def save_team(self, names: list[str]) -> None:
        self._client.table("team_members").delete().neq("id", 0).execute()
        if names:
            self._client.table("team_members").insert(
                [{"name": n, "created_at": _now()} for n in names]
            ).execute()

