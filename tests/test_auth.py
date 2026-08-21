"""Tests for the OIDC auth module."""

import pytest
from app.core.auth.oidc import DevVerifier


class TestDevVerifier:
    @pytest.mark.asyncio
    async def test_json_token(self):
        v = DevVerifier()
        identity = await v.verify('{"sub": "agent-1", "iss": "dev", "role": "provider"}')
        assert identity.subject == "agent-1"
        assert identity.issuer == "dev"
        assert identity.custom_claims["role"] == "provider"

    @pytest.mark.asyncio
    async def test_opaque_token(self):
        v = DevVerifier()
        identity = await v.verify("plain-string-token")
        assert identity.subject == "plain-string-token"
        assert identity.issuer == "dev"
