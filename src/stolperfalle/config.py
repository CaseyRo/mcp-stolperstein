"""Configuration loaded from environment variables."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Storage
    # Filename intentionally NOT renamed with the product (stolperstein.db,
    # not stolperfalle.db) — this is the actual on-disk filename in the
    # production volume; renaming it would make the server create a fresh
    # empty database on next boot instead of finding the existing one.
    cq_local_db_path: str = "/data/stolperstein.db"

    # Server transport
    transport: Literal["stdio", "http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8716
    # Host-header allowlist for fastmcp >= 3.4.3's DNS-rebind guard.
    # Comma-separated fnmatch patterns; "*" = accept any Host. Wildcard is
    # the right default HERE because this server is reached under several
    # legitimate Host values (public hostname via cloudflared, Tailscale
    # IP:port from uptime monitors, localhost from the Docker healthcheck)
    # and its actual gate is bearer auth, not Host trust.
    allowed_hosts: str = "*"

    # MCP server auth
    mcp_stolperfalle_api_key: SecretStr = SecretStr("")
    mcp_stolperfalle_public_url: str = ""

    # Cloudflare Access OIDC (replaces Keycloak)
    cf_access_team: str = ""
    cf_access_client_id: str = ""
    cf_access_client_secret: SecretStr = SecretStr("")

    # Embeddings
    cq_embedding_model: str = "all-MiniLM-L6-v2"
    cq_embedding_api_url: str = ""

    # LLM for reflect tool (OpenAI-compatible chat completions endpoint)
    cq_llm_api_url: str = ""  # e.g. https://api.openai.com/v1 or local endpoint
    cq_llm_api_key: SecretStr = SecretStr("")
    cq_llm_model: str = "gpt-4o-mini"

    # Multi-tenant visibility
    trusted_orgs: str = "*"  # comma-separated DIDs; "*" = trust-all

    # Emergent signal detection
    stolperfalle_emergent_disabled: bool = False
    emergent_detect_every_n: int = 10
    emergent_min_misses: int = 5
    emergent_min_sessions: int = 2

    # NOTE: the STOLPERFALLE_HOOK* env vars are consumed by the plugin's
    # hook handlers (client-side, plain os.environ) — they are not server
    # settings. See plugin/stolperfalle/SKILL.md.

    model_config = {"env_prefix": "", "case_sensitive": False}

    def ensure_api_key(self) -> str:
        """Return the API key, generating one if not configured."""
        existing = self.mcp_stolperfalle_api_key.get_secret_value()
        if existing:
            return existing

        from stolperfalle.auth import generate_api_key

        key = generate_api_key()
        self.mcp_stolperfalle_api_key = SecretStr(key)
        # Never log the secret value — container stdout is captured by the
        # json-file driver and Komodo's log pane (pentest secret-leak finding).
        logger.warning(
            "MCP_STOLPERFALLE_API_KEY was empty; generated an ephemeral key "
            "(value not logged). Set MCP_STOLPERFALLE_API_KEY to a stable value "
            "so clients can authenticate and the key survives restarts."
        )
        return key

    @property
    def cf_access_config_url(self) -> str:
        """OIDC discovery URL for Cloudflare Access."""
        return (
            f"https://{self.cf_access_team}.cloudflareaccess.com"
            f"/cdn-cgi/access/sso/oidc/{self.cf_access_client_id}"
            f"/.well-known/openid-configuration"
        )

    @property
    def base_url(self) -> str:
        """Public URL for OAuth metadata, or computed from host:port."""
        if self.mcp_stolperfalle_public_url:
            return self.mcp_stolperfalle_public_url.rstrip("/")
        return f"http://{self.host}:{self.port}"

    @property
    def trusted_orgs_list(self) -> list[str]:
        """Parsed comma-separated DIDs; `['*']` means trust-all."""
        raw = self.trusted_orgs.strip()
        if not raw:
            return ["*"]
        return [t.strip() for t in raw.split(",") if t.strip()]


settings = Settings()
