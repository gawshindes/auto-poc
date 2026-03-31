"""
Provider-agnostic authentication for the Demo Creation Pipeline.

Usage:
    from web.auth import get_auth_provider

    _auth = get_auth_provider()        # singleton, reads AUTH_PROVIDER env var
    user = await _auth.verify_token(token)  # AuthUser | None
    config = _auth.get_frontend_config()    # dict sent to browser

Providers:
    AUTH_PROVIDER=        → NoopAuthProvider (no auth, app works as today)
    AUTH_PROVIDER=clerk   → ClerkAuthProvider (JWT via Clerk JWKS)
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuthUser:
    id: str
    email: Optional[str] = None
    name: Optional[str] = None


class AuthProvider(ABC):
    @abstractmethod
    async def verify_token(self, token: str) -> Optional[AuthUser]:
        """Verify a Bearer token. Returns AuthUser on success, None on failure."""
        ...

    @abstractmethod
    def get_frontend_config(self) -> dict:
        """Return config dict sent to the browser via GET /api/auth/config."""
        ...

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """False means auth is disabled — middleware lets all requests through."""
        ...


# ---------------------------------------------------------------------------
# Factory — singleton
# ---------------------------------------------------------------------------

_provider: Optional[AuthProvider] = None


def get_auth_provider() -> AuthProvider:
    global _provider
    if _provider is not None:
        return _provider

    provider_name = os.environ.get("AUTH_PROVIDER", "").strip().lower()

    if provider_name == "clerk":
        from web.auth.clerk import ClerkAuthProvider
        _provider = ClerkAuthProvider()
    else:
        from web.auth.noop import NoopAuthProvider
        _provider = NoopAuthProvider()

    return _provider
