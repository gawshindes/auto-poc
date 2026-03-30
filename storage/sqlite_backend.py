"""SQLite backend — default for local dev. Single data.db file in DATA_DIR."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from storage import StorageBackend, MIGRATIONS_DIR


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_dumps(obj) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj)


def _json_loads(s: str | None, default=None):
    if s is None:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


class SqliteBackend(StorageBackend):
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.run_migrations()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    # -- Migrations ----------------------------------------------------------

    def run_migrations(self) -> None:
        conn = self._conn()
        # Ensure schema_migrations table exists first
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        conn.commit()

        applied = {
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }

        # Skip *_pg.sql files — those are for PostgreSQL/Supabase
        migration_files = sorted(
            f for f in MIGRATIONS_DIR.glob("*.sql") if not f.name.endswith("_pg.sql")
        )
        for f in migration_files:
            version = int(f.name.split("_")[0])
            if version in applied:
                continue
            sql = f.read_text()
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, f.name, _now()),
            )
            conn.commit()

    # -- Demos ---------------------------------------------------------------

    def save_demo(self, demo: dict) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT OR REPLACE INTO demos
               (id, session_id, source, company, demo_type, use_case,
                name, description, keywords, stack, skills_used,
                deploy_url, github_repo, health_check_passed,
                is_reusable, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                demo["id"],
                demo.get("session_id"),
                demo.get("source", "web"),
                demo.get("company"),
                demo.get("demo_type"),
                demo.get("use_case"),
                demo.get("name"),
                demo.get("description"),
                _json_dumps(demo.get("keywords")),
                demo.get("stack"),
                _json_dumps(demo.get("skills_used")),
                demo.get("deploy_url"),
                demo.get("github_repo"),
                1 if demo.get("health_check_passed") else 0,
                1 if demo.get("is_reusable") else 0,
                1 if demo.get("is_active", True) else 0,
                demo.get("created_at", _now()),
                _now(),
            ),
        )
        conn.commit()

    def get_demo(self, demo_id: str) -> dict | None:
        row = self._conn().execute(
            "SELECT * FROM demos WHERE id = ?", (demo_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["keywords"] = _json_loads(d.get("keywords"), [])
        d["skills_used"] = _json_loads(d.get("skills_used"), [])
        d["is_reusable"] = bool(d.get("is_reusable"))
        d["is_active"] = bool(d.get("is_active"))
        d["health_check_passed"] = bool(d.get("health_check_passed"))
        return d

    def get_demo_by_session_id(self, session_id: str) -> dict | None:
        row = self._conn().execute(
            "SELECT * FROM demos WHERE session_id = ? LIMIT 1", (session_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["keywords"] = _json_loads(d.get("keywords"), [])
        d["skills_used"] = _json_loads(d.get("skills_used"), [])
        d["is_reusable"] = bool(d.get("is_reusable"))
        d["is_active"] = bool(d.get("is_active"))
        d["health_check_passed"] = bool(d.get("health_check_passed"))
        return d

    def list_demos(self, filters: dict | None = None) -> list[dict]:
        query = "SELECT * FROM demos"
        conditions = []
        params = []
        if filters:
            if "is_reusable" in filters:
                conditions.append("is_reusable = ?")
                params.append(1 if filters["is_reusable"] else 0)
            if "is_active" in filters:
                conditions.append("is_active = ?")
                params.append(1 if filters["is_active"] else 0)
            if "source" in filters:
                conditions.append("source = ?")
                params.append(filters["source"])
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY updated_at DESC"

        rows = self._conn().execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["keywords"] = _json_loads(d.get("keywords"), [])
            d["skills_used"] = _json_loads(d.get("skills_used"), [])
            d["is_reusable"] = bool(d.get("is_reusable"))
            d["is_active"] = bool(d.get("is_active"))
            d["health_check_passed"] = bool(d.get("health_check_passed"))
            result.append(d)
        return result

    def get_solutions(self) -> dict:
        """Return all active demos as solutions for matching."""
        rows = self._conn().execute("""
            SELECT id, name, description, demo_type, use_case,
                   keywords, stack, skills_used, source,
                   company AS built_for, deploy_url
            FROM demos
            WHERE is_active = 1
        """).fetchall()

        solutions = []
        for r in rows:
            entry = dict(r)
            entry["keywords"] = _json_loads(entry.get("keywords"), [])
            entry["skills_used"] = _json_loads(entry.get("skills_used"), [])
            entry["status"] = "built"
            solutions.append(entry)

        return {
            "version": "1.0",
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "solutions": solutions,
        }

    # -- Sessions ------------------------------------------------------------

    def save_session(self, session: dict) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (id, source, transcript, meeting_link, additional_context, email,
                status, current_stage, mode, error,
                stage_1_understand, stage_2_design, stage_3_demo, stage_4_guide,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session["id"],
                session.get("source", "web"),
                session.get("transcript"),
                session.get("meeting_link"),
                session.get("additional_context"),
                session.get("email"),
                session.get("status", "idle"),
                session.get("current_stage", 0),
                session.get("mode", "auto"),
                session.get("error"),
                _json_dumps(session.get("stage_1_understand")),
                _json_dumps(session.get("stage_2_design")),
                session.get("stage_3_demo"),
                session.get("stage_4_guide"),
                session.get("created_at", _now()),
                _now(),
            ),
        )
        conn.commit()

    def get_session(self, session_id: str) -> dict | None:
        row = self._conn().execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["stage_1_understand"] = _json_loads(d.get("stage_1_understand"))
        d["stage_2_design"] = _json_loads(d.get("stage_2_design"))
        d["logs"] = self.get_logs(session_id)
        return d

    def list_sessions(self) -> list[dict]:
        rows = self._conn().execute("""
            SELECT s.id, s.source, s.status, s.current_stage, s.mode,
                   s.created_at, s.updated_at,
                   d.id AS demo_id, d.name AS demo_name, d.company,
                   d.deploy_url, d.health_check_passed
            FROM sessions s
            LEFT JOIN demos d ON d.session_id = s.id
            ORDER BY s.updated_at DESC
        """).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["health_check_passed"] = bool(d.get("health_check_passed"))
            result.append(d)
        return result

    # -- Session logs --------------------------------------------------------

    def append_log(self, session_id: str, message: str,
                   level: str = "info", stage: int | None = None) -> None:
        self._conn().execute(
            """INSERT INTO session_logs (session_id, timestamp, level, stage, message)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, _now(), level, stage, message),
        )
        self._conn().commit()

    def get_logs(self, session_id: str) -> list[dict]:
        rows = self._conn().execute(
            """SELECT timestamp, level, stage, message
               FROM session_logs WHERE session_id = ?
               ORDER BY id ASC""",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Team ----------------------------------------------------------------

    def get_team(self) -> list[str]:
        rows = self._conn().execute(
            "SELECT name FROM team_members ORDER BY id"
        ).fetchall()
        return [r["name"] for r in rows]

    def save_team(self, names: list[str]) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM team_members")
        for name in names:
            conn.execute(
                "INSERT INTO team_members (name, created_at) VALUES (?, ?)",
                (name, _now()),
            )
        conn.commit()

