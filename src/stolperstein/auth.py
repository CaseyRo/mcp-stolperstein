"""Authentication for the MCP server.

Supports two authentication modes simultaneously via MultiAuth:

1. **Keycloak JWT** (for Claude.ai connectors and other OAuth clients):
   Validates JWT tokens issued by Keycloak using JWKS endpoint.

2. **Bearer token** (for Claude Code, n8n, and other direct clients):
   Static API key validation via Authorization: Bearer <key>.
"""

from __future__ import annotations

import hmac
import logging
import secrets

from fastmcp.server.auth import (
    AccessToken,
    JWTVerifier,
    MultiAuth,
    RemoteAuthProvider,
    TokenVerifier,
)
from pydantic import AnyHttpUrl

logger = logging.getLogger(__name__)


class BearerTokenVerifier(TokenVerifier):
    """Validates incoming requests against a static API key.

    Uses constant-time comparison to prevent timing attacks.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self._api_key = api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._api_key):
            logger.warning("Rejected request with invalid API key")
            return None

        return AccessToken(
            token=token,
            client_id="mcp-stolperstein-client",
            scopes=["all"],
        )


def create_auth(
    api_key: str | None,
    base_url: str,
    keycloak_issuer: str,
    keycloak_audience: str,
) -> MultiAuth:
    """Create the dual authentication provider.

    Returns a MultiAuth that accepts both:
    - Keycloak JWT clients (Claude.ai) via JWKS-based JWT validation
    - Bearer token clients (Claude Code, n8n) via static API key
    """
    jwks_uri = f"{keycloak_issuer.rstrip('/')}/protocol/openid-connect/certs"

    jwt_verifier = JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=keycloak_issuer,
        audience=keycloak_audience,
    )

    keycloak_auth = RemoteAuthProvider(
        token_verifier=jwt_verifier,
        authorization_servers=[AnyHttpUrl(keycloak_issuer)],
        base_url=base_url,
        scopes_supported=["openid"],
        resource_name="Stolperstein MCP Server",
    )

    verifiers: list[TokenVerifier] = []
    if api_key:
        verifiers.append(BearerTokenVerifier(api_key))

    return MultiAuth(server=keycloak_auth, verifiers=verifiers)


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"stmcp_{secrets.token_urlsafe(32)}"
