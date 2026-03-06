"""SQLite backend — opt-in via STORAGE_BACKEND=sqlite. Single data.db file in DATA_DIR."""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from storage import StorageBackend, PROJECT_ROOT

_SCHEMA = """
CREATE TABLE IF NOT EXISTS solutions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    built_for TEXT,
    demo_type TEXT,
    keywords TEXT,
    stack TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'built',
    demo_url TEXT,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    mode TEXT,
    status TEXT,
    current_stage INTEGER DEFAULT 0,
    transcript TEXT,
    email TEXT,
    stage_outputs TEXT,
    deploy_url TEXT,
    logs TEXT,
    error TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS slack_state (
    channel_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# Stage keys stored inside the stage_outputs JSON blob
_STAGE_KEYS = [
    "stage_1_classifier", "stage_2_dependency", "stage_3_matcher",
    "stage_4_messenger", "stage_5_demo", "stage_6_guide",
]


class SqliteBackend(StorageBackend):
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()
        self._seed_if_empty()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_schema(self) -> None:
        conn = self._conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    def _seed_if_empty(self) -> None:
        row = self._conn().execute("SELECT COUNT(*) FROM solutions").fetchone()
        if row[0] > 0:
            return
        seed = PROJECT_ROOT / "registry" / "solutions.json"
        if not seed.exists():
            seed = PROJECT_ROOT / "registry" / "solutions.example.json"
        if not seed.exists():
            return
        data = json.loads(seed.read_text())
        for s in data.get("solutions", []):
            self._insert_solution(s)

    def _insert_solution(self, entry: dict) -> None:
        self._conn().execute(
            """INSERT OR IGNORE INTO solutions
               (id, name, description, built_for, demo_type, keywords, stack,
                source, status, demo_url, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("id"), entry.get("name"), entry.get("description"),
                entry.get("built_for"), entry.get("demo_type"),
                json.dumps(entry.get("keywords", [])),
                entry.get("stack"), entry.get("source", "manual"),
                entry.get("status", "built"), entry.get("demo_url"),
                entry.get("note"),
            ),
        )
        self._conn().commit()

    # -- Solutions -----------------------------------------------------------

    def get_solutions(self) -> dict:
        rows = self._conn().execute("SELECT * FROM solutions").fetchall()
        solutions = []
        for r in rows:
            entry = dict(r)
            if entry.get("keywords"):
                entry["keywords"] = json.loads(entry["keywords"])
            solutions.append(entry)
        return {
            "version": "1.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "solutions": solutions,
        }

    def save_solutions(self, data: dict) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM solutions")
        for s in data.get("solutions", []):
            self._insert_solution(s)
        conn.commit()

    def append_solution(self, entry: dict, data: dict) -> None:
        self._insert_solution(entry)

    # -- Sessions ------------------------------------------------------------

    def _session_to_row(self, session: dict) -> tuple:
        stage_outputs = {k: session.get(k) for k in _STAGE_KEYS}
        return (
            session.get("session_id"),
            session.get("mode"),
            session.get("status"),
            session.get("current_stage", 0),
            session.get("transcript"),
            session.get("email"),
            json.dumps(stage_outputs),
            session.get("deploy_url"),
            json.dumps(session.get("logs", [])),
            session.get("error"),
            session.get("created_at", datetime.now().isoformat()),
            datetime.now().isoformat(),
        )

    def _row_to_session(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        stage_outputs = json.loads(d.pop("stage_outputs") or "{}")
        d.update(stage_outputs)
        d["logs"] = json.loads(d.get("logs") or "[]")
        return d

    def get_session(self, session_id: str) -> dict | None:
        row = self._conn().execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def save_session(self, session: dict) -> None:
        values = self._session_to_row(session)
        self._conn().execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, mode, status, current_stage, transcript, email,
                stage_outputs, deploy_url, logs, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        self._conn().commit()

    def list_sessions(self) -> list[dict]:
        rows = self._conn().execute(
            """SELECT session_id, mode, status, current_stage, stage_outputs,
                      deploy_url, created_at, updated_at
               FROM sessions ORDER BY updated_at DESC"""
        ).fetchall()
        sessions = []
        for r in rows:
            d = dict(r)
            stage_outputs = json.loads(d.pop("stage_outputs") or "{}")
            classifier = stage_outputs.get("stage_1_classifier") or {}
            sessions.append({
                "session_id": d["session_id"],
                "company": (
                    classifier.get("company_name")
                    or classifier.get("customer", {}).get("company", "Unknown")
                ),
                "status": d.get("status", "unknown"),
                "current_stage": d.get("current_stage", 0),
                "created_at": d.get("created_at", ""),
                "updated_at": d.get("updated_at", ""),
            })
        return sessions

    # -- Slack state ---------------------------------------------------------

    def get_slack_state(self, channel_id: str) -> dict | None:
        row = self._conn().execute(
            "SELECT state FROM slack_state WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["state"])

    def save_slack_state(self, channel_id: str, state: dict) -> None:
        self._conn().execute(
            "INSERT OR REPLACE INTO slack_state (channel_id, state) VALUES (?, ?)",
            (channel_id, json.dumps(state)),
        )
        self._conn().commit()

    def delete_slack_state(self, channel_id: str) -> None:
        self._conn().execute(
            "DELETE FROM slack_state WHERE channel_id = ?", (channel_id,)
        )
        self._conn().commit()
