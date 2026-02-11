"""OIDC authentication layer (§4 of AGENTS.md / §4.1.4 of the Agentic Bus paper).

Handles:
- Token verification (RS256 / RS384 / RS512 via JWKS)
- Extraction of standard OIDC claims (sub, iss, aud, scope)
- Custom claim propagation for IBAC
- Agent enrolment with cryptographic identity

The module exposes a lightweight ``OIDCVerifier`` that validates bearer tokens
against the IdP's JWKS endpoint and returns a structured ``OIDCIdentity``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import jwt
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OIDCIdentity(BaseModel):
    """Verified identity extracted from an OIDC token."""

    subject: str
    issuer: str = ""
    audience: str | list[str] = ""
    scopes: list[str] = Field(default_factory=list)
    custom_claims: dict[str, Any] = Field(default_factory=dict)
    raw_token: str = ""


class OIDCVerifier:
    """Verifies OIDC Bearer tokens against a JWKS endpoint.

    Parameters
    ----------
    issuer : str
        Expected ``iss`` claim (also used to derive ``/.well-known/openid-configuration``).
    audience : str
        Expected ``aud`` claim.
    """

    def __init__(
        self,
        issuer: str | None = None,
        audience: str | None = None,
    ):
        self.issuer = issuer or os.getenv("AGBUS_OIDC_ISSUER", "")
        self.audience = audience or os.getenv("AGBUS_OIDC_AUDIENCE", "")
        self._jwks_client: jwt.PyJWKClient | None = None

    async def _ensure_jwks(self) -> jwt.PyJWKClient:
        if self._jwks_client is None:
            # Fetch OIDC discovery document
            well_known = f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"
            async with httpx.AsyncClient() as client:
                resp = await client.get(well_known)
                resp.raise_for_status()
                jwks_uri = resp.json()["jwks_uri"]
            self._jwks_client = jwt.PyJWKClient(jwks_uri)
        return self._jwks_client

    async def verify(self, token: str) -> OIDCIdentity:
        """Verify a JWT and return the extracted ``OIDCIdentity``.

        Raises ``jwt.exceptions.InvalidTokenError`` on failure.
        """
        jwks = await self._ensure_jwks()
        signing_key = jwks.get_signing_key_from_jwt(token)

        decoded = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512"],
            issuer=self.issuer,
            audience=self.audience,
            options={"verify_exp": True},
        )

        # Standard claims
        subject = decoded.get("sub", "")
        scopes = decoded.get("scope", "").split() if isinstance(decoded.get("scope"), str) else []

        # Everything that isn't a registered claim is a custom claim
        registered = {"sub", "iss", "aud", "exp", "iat", "nbf", "jti", "scope"}
        custom = {k: v for k, v in decoded.items() if k not in registered}

        return OIDCIdentity(
            subject=subject,
            issuer=decoded.get("iss", ""),
            audience=decoded.get("aud", ""),
            scopes=scopes,
            custom_claims=custom,
            raw_token=token,
        )


class DevVerifier:
    """Development-mode verifier that accepts any token as a plain JSON payload.

    **Never use in production.**  Useful for local development without an IdP.
    """

    async def verify(self, token: str) -> OIDCIdentity:
        import json

        try:
            data = json.loads(token)
        except json.JSONDecodeError:
            # Treat as opaque subject string
            data = {"sub": token}

        return OIDCIdentity(
            subject=data.get("sub", token),
            issuer=data.get("iss", "dev"),
            audience=data.get("aud", "agbus"),
            scopes=data.get("scopes", []),
            custom_claims={k: v for k, v in data.items() if k not in {"sub", "iss", "aud", "scopes"}},
        )
