"""JSON file backend — zero-config default. Reads/writes JSON files to DATA_DIR."""

import json
from datetime import datetime
from pathlib import Path

from storage import StorageBackend, PROJECT_ROOT


class JsonFileBackend(StorageBackend):
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._solutions_path = data_dir / "registry" / "solutions.json"
        self._sessions_dir = data_dir / "sessions"
        self._slack_state_dir = data_dir / "slack" / "state"

        # Ensure directories exist
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    # -- Solutions -----------------------------------------------------------

    def _seed_solutions(self) -> None:
        """Create solutions.json from bundled example or empty."""
        self._solutions_path.parent.mkdir(parents=True, exist_ok=True)
        seed = PROJECT_ROOT / "registry" / "solutions.json"
        if not seed.exists():
            seed = PROJECT_ROOT / "registry" / "solutions.example.json"
        if seed.exists():
            self._solutions_path.write_text(seed.read_text())
        else:
            self._solutions_path.write_text(json.dumps({
                "version": "1.0",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "solutions": [],
            }, indent=2))

    def get_solutions(self) -> dict:
        if not self._solutions_path.exists():
            self._seed_solutions()
        else:
            # Re-seed if existing file has empty solutions list (stale volume)
            data = json.loads(self._solutions_path.read_text())
            if not data.get("solutions"):
                self._seed_solutions()
        return json.loads(self._solutions_path.read_text())

    def save_solutions(self, data: dict) -> None:
        self._solutions_path.parent.mkdir(parents=True, exist_ok=True)
        data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        self._solutions_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def append_solution(self, entry: dict, data: dict) -> None:
        data.get("solutions", []).append(entry)
        self.save_solutions(data)

    # -- Sessions ------------------------------------------------------------

    def _session_path(self, session_id: str) -> Path:
        return self._sessions_dir / f"{session_id}.json"

    def get_session(self, session_id: str) -> dict | None:
        p = self._session_path(session_id)
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def save_session(self, session: dict) -> None:
        session["updated_at"] = datetime.now().isoformat()
        self._session_path(session["session_id"]).write_text(
            json.dumps(session, indent=2)
        )

    def list_sessions(self) -> list[dict]:
        sessions = []
        if not self._sessions_dir.exists():
            return sessions
        for f in self._sessions_dir.glob("*.json"):
            try:
                s = json.loads(f.read_text())
                classifier = s.get("stage_1_classifier") or {}
                sessions.append({
                    "session_id": s["session_id"],
                    "company": (
                        classifier.get("company_name")
                        or classifier.get("customer", {}).get("company", "Unknown")
                    ),
                    "status": s.get("status", "unknown"),
                    "current_stage": s.get("current_stage", 0),
                    "created_at": s.get("created_at", ""),
                    "updated_at": s.get("updated_at", ""),
                })
            except Exception:
                pass
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions

    # -- Slack state ---------------------------------------------------------

    def _slack_path(self, channel_id: str) -> Path:
        return self._slack_state_dir / f"{channel_id}.json"

    def get_slack_state(self, channel_id: str) -> dict | None:
        p = self._slack_path(channel_id)
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def save_slack_state(self, channel_id: str, state: dict) -> None:
        self._slack_state_dir.mkdir(parents=True, exist_ok=True)
        self._slack_path(channel_id).write_text(json.dumps(state, indent=2))

    def delete_slack_state(self, channel_id: str) -> None:
        p = self._slack_path(channel_id)
        if p.exists():
            p.unlink()
