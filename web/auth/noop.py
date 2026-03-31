"""NoopAuthProvider — auth disabled, all requests pass through."""
from __future__ import annotations

from typing import Optional

from web.auth import AuthProvider, AuthUser


class NoopAuthProvider(AuthProvider):
    @property
    def is_enabled(self) -> bool:
        return False

    async def verify_token(self, token: str) -> Optional[AuthUser]:
        return AuthUser(id="anonymous")

    def get_frontend_config(self) -> dict:
        return {"provider": "none", "enabled": False}
