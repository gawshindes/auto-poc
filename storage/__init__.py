"""
Storage abstraction layer.

Default: JSON files (zero setup).
Opt-in: SQLite via STORAGE_BACKEND=sqlite (concurrent access, better querying).
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT)))


class StorageBackend(ABC):
    """Abstract interface for all runtime data storage."""

    # -- Solutions registry --------------------------------------------------
    @abstractmethod
    def get_solutions(self) -> dict:
        """Return full solutions structure (for prompt injection)."""

    @abstractmethod
    def save_solutions(self, data: dict) -> None:
        """Write full solutions structure back to storage."""

    @abstractmethod
    def append_solution(self, entry: dict, data: dict) -> None:
        """Append a solution entry and save. `data` is the full structure."""

    # -- Sessions ------------------------------------------------------------
    @abstractmethod
    def get_session(self, session_id: str) -> dict | None:
        """Return session dict or None if not found."""

    @abstractmethod
    def save_session(self, session: dict) -> None:
        """Create or update a session."""

    @abstractmethod
    def list_sessions(self) -> list[dict]:
        """Return list of session summaries (no transcript/demo), newest first."""

    # -- Slack state ---------------------------------------------------------
    @abstractmethod
    def get_slack_state(self, channel_id: str) -> dict | None:
        """Return slack state or None."""

    @abstractmethod
    def save_slack_state(self, channel_id: str, state: dict) -> None:
        """Save slack pipeline state."""

    @abstractmethod
    def delete_slack_state(self, channel_id: str) -> None:
        """Remove slack state after pipeline resumes."""


_backend: StorageBackend | None = None


def get_backend() -> StorageBackend:
    """Factory — returns singleton backend based on STORAGE_BACKEND env var."""
    global _backend
    if _backend is not None:
        return _backend

    backend_type = os.environ.get("STORAGE_BACKEND", "json").lower()
    if backend_type == "sqlite":
        from storage.sqlite_backend import SqliteBackend
        _backend = SqliteBackend(DATA_DIR / "data.db")
    else:
        from storage.json_backend import JsonFileBackend
        _backend = JsonFileBackend(DATA_DIR)
    return _backend
