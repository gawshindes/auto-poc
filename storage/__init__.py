"""
Storage abstraction layer.

Backends:
  - SQLite (default): zero config, single data.db file — for local dev
  - Supabase: Postgres-backed — for production (STORAGE_BACKEND=supabase)

Schema managed via SQL migration files in storage/migrations/.
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT)))
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class StorageBackend(ABC):
    """Abstract interface for all runtime data storage."""

    # -- Migrations ----------------------------------------------------------
    @abstractmethod
    def run_migrations(self) -> None:
        """Apply any pending SQL migrations from storage/migrations/."""

    # -- Demos ---------------------------------------------------------------
    @abstractmethod
    def save_demo(self, demo: dict) -> None:
        """Create or update a demo record."""

    @abstractmethod
    def get_demo(self, demo_id: str) -> dict | None:
        """Return demo dict or None."""

    @abstractmethod
    def list_demos(self, filters: dict | None = None) -> list[dict]:
        """Return list of demo summaries, newest first."""

    @abstractmethod
    def get_demo_by_session_id(self, session_id: str) -> dict | None:
        """Return the demo created by a given session, or None."""

    @abstractmethod
    def get_solutions(self) -> dict:
        """Return reusable demos formatted as solutions registry for the Design stage prompt."""

    # -- Sessions ------------------------------------------------------------
    @abstractmethod
    def save_session(self, session: dict) -> None:
        """Create or update a session record."""

    @abstractmethod
    def get_session(self, session_id: str) -> dict | None:
        """Return session dict or None."""

    @abstractmethod
    def list_sessions(self) -> list[dict]:
        """Return list of session summaries, newest first."""

    # -- Session logs --------------------------------------------------------
    @abstractmethod
    def append_log(self, session_id: str, message: str,
                   level: str = "info", stage: int | None = None) -> None:
        """Append a log entry for a session."""

    @abstractmethod
    def get_logs(self, session_id: str) -> list[dict]:
        """Return all log entries for a session, ordered by timestamp."""

    # -- Team ----------------------------------------------------------------
    @abstractmethod
    def get_team(self) -> list[str]:
        """Return list of team member names."""

    @abstractmethod
    def save_team(self, names: list[str]) -> None:
        """Replace the team member list."""



_backend: StorageBackend | None = None


def get_backend() -> StorageBackend:
    """Factory — returns singleton backend based on STORAGE_BACKEND env var."""
    global _backend
    if _backend is not None:
        return _backend

    backend_type = os.environ.get("STORAGE_BACKEND", "sqlite").lower()
    if backend_type == "supabase":
        from storage.supabase_backend import SupabaseBackend
        _backend = SupabaseBackend()
    else:
        from storage.sqlite_backend import SqliteBackend
        _backend = SqliteBackend(DATA_DIR / "data.db")
    return _backend
