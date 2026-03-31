"""ClerkAuthProvider — verifies Clerk JWTs via JWKS."""
from __future__ import annotations

import os
from typing import Optional

from web.auth import AuthProvider, AuthUser


class ClerkAuthProvider(AuthProvider):
    def __init__(self) -> None:
        self._publishable_key = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
        self._issuer = os.environ.get("CLERK_JWT_ISSUER", "")
        self._jwks_client = None

        if not self._publishable_key:
            raise RuntimeError("CLERK_PUBLISHABLE_KEY env var is required when AUTH_PROVIDER=clerk")
        if not self._issuer:
            raise RuntimeError("CLERK_JWT_ISSUER env var is required when AUTH_PROVIDER=clerk")

        # Derive JWKS URL from issuer (Clerk standard: issuer + /.well-known/jwks.json)
        jwks_url = self._issuer.rstrip("/") + "/.well-known/jwks.json"

        try:
            import jwt
            from jwt import PyJWKClient
            self._jwt = jwt
            self._jwks_client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
        except ImportError:
            raise RuntimeError(
                "PyJWT[crypto] is required for Clerk auth — run: pip install 'PyJWT[crypto]>=2.8.0'"
            )

    @property
    def is_enabled(self) -> bool:
        return True

    async def verify_token(self, token: str) -> Optional[AuthUser]:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            payload = self._jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_aud": False},
                issuer=self._issuer,
            )
            user_id = payload.get("sub", "")
            if not user_id:
                return None

            # Clerk puts email in email claim or primary_email_address_id is separate;
            # the flat email claim is set when the user has a primary email
            email = payload.get("email") or None
            name = payload.get("name") or None
            return AuthUser(id=user_id, email=email, name=name)
        except Exception:
            return None

    def get_frontend_config(self) -> dict:
        return {
            "provider": "clerk",
            "enabled": True,
            "publishable_key": self._publishable_key,
        }
