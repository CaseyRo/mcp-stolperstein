"""Authentication for the MCP server.

Supports two authentication modes simultaneously via MultiAuth:

1. **Cloudflare Access OIDC** (for MCP Portal and other OAuth clients):
   The server proxies the full OAuth flow via OIDCProxy using a
   Cloudflare Access for SaaS OIDC application.

2. **Bearer token** (for Claude Code, n8n, and other direct clients):
   Static API key validation via Authorization: Bearer <key>.
"""

from __future__ import annotations

import hmac
import logging
import secrets

from fastmcp.server.auth import (
    AccessToken,
    MultiAuth,
    TokenVerifier,
)
from fastmcp.server.auth.oidc_proxy import OIDCProxy

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
    cf_access_config_url: str,
    cf_access_client_id: str,
    cf_access_client_secret: str,
) -> MultiAuth:
    """Create the dual authentication provider.

    Returns a MultiAuth that accepts both:
    - Cloudflare Access OIDC clients (MCP Portal) via OIDCProxy
    - Bearer token clients (Claude Code, n8n) via static API key

    Args:
        api_key: Static API key for bearer token auth (None to skip).
        base_url: Public URL of this server.
        cf_access_config_url: CF Access OIDC discovery URL.
        cf_access_client_id: CF Access SaaS app client ID.
        cf_access_client_secret: CF Access SaaS app client secret.
    """
    oidc_auth = OIDCProxy(
        config_url=cf_access_config_url,
        client_id=cf_access_client_id,
        client_secret=cf_access_client_secret,
        base_url=base_url,
    )

    verifiers: list[TokenVerifier] = []
    if api_key:
        verifiers.append(BearerTokenVerifier(api_key))

    return MultiAuth(server=oidc_auth, verifiers=verifiers)


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"stmcp_{secrets.token_urlsafe(32)}"
