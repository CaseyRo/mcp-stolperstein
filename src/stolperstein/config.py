"""Configuration loaded from environment variables."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Storage
    cq_local_db_path: str = "/data/stolperstein.db"

    # Server transport
    transport: Literal["stdio", "http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8716

    # MCP server auth
    mcp_stolperstein_api_key: SecretStr = SecretStr("")
    mcp_stolperstein_public_url: str = ""

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
    stolperstein_emergent_disabled: bool = False
    emergent_detect_every_n: int = 10
    emergent_min_misses: int = 5
    emergent_min_sessions: int = 2

    # NOTE: the STOLPERSTEIN_HOOK* env vars are consumed by the plugin's
    # hook handlers (client-side, plain os.environ) — they are not server
    # settings. See plugin/stolperstein/SKILL.md.

    model_config = {"env_prefix": "", "case_sensitive": False}

    def ensure_api_key(self) -> str:
        """Return the API key, generating one if not configured."""
        existing = self.mcp_stolperstein_api_key.get_secret_value()
        if existing:
            return existing

        from stolperstein.auth import generate_api_key

        key = generate_api_key()
        self.mcp_stolperstein_api_key = SecretStr(key)
        logger.warning(
            "Generated API key: %s (set MCP_STOLPERSTEIN_API_KEY to persist)", key
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
        if self.mcp_stolperstein_public_url:
            return self.mcp_stolperstein_public_url.rstrip("/")
        return f"http://{self.host}:{self.port}"

    @property
    def trusted_orgs_list(self) -> list[str]:
        """Parsed comma-separated DIDs; `['*']` means trust-all."""
        raw = self.trusted_orgs.strip()
        if not raw:
            return ["*"]
        return [t.strip() for t in raw.split(",") if t.strip()]


settings = Settings()
