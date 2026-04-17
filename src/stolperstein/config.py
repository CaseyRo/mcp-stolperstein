"""Configuration loaded from environment variables."""

from __future__ import annotations

import logging
import warnings
from typing import Any, Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Storage
    cq_local_db_path: str = "/data/stolperstein.db"
    cq_log_level: str = "INFO"

    # Server transport
    transport: Literal["stdio", "http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8716

    # MCP server auth
    mcp_stolperstein_api_key: str = ""
    mcp_stolperstein_public_url: str = ""

    # Cloudflare Access OIDC (replaces Keycloak)
    cf_access_team: str = ""
    cf_access_client_id: str = ""
    cf_access_client_secret: str = ""

    # Embeddings
    cq_embedding_model: str = "all-MiniLM-L6-v2"
    cq_embedding_api_url: str = ""

    # LLM for reflect tool (OpenAI-compatible chat completions endpoint)
    cq_llm_api_url: str = ""  # e.g. https://api.openai.com/v1 or local endpoint
    cq_llm_api_key: str = ""
    cq_llm_model: str = "gpt-4o-mini"

    # CQ team sync (optional)
    cq_team_addr: str = ""
    cq_team_api_key: SecretStr = SecretStr("")

    # Siyuan sync (optional)
    cq_siyuan_url: str = ""
    cq_siyuan_notebook: str = ""
    cq_siyuan_token: SecretStr = SecretStr("")
    cq_siyuan_schema_version: int = 1  # 0 = legacy shape during transition

    # Multi-tenant visibility
    trusted_orgs: str = "*"  # comma-separated DIDs; "*" = trust-all

    # Emergent signal detection
    stolperstein_emergent_disabled: bool = False
    emergent_detect_every_n: int = 10
    emergent_min_misses: int = 5
    emergent_min_sessions: int = 2

    # Claude Code hooks
    stolperstein_hooks_disabled: str = ""  # comma-separated hook names
    stolperstein_hook_cooldown_s: int = 30
    stolperstein_reflect_threshold: int = 20
    stolperstein_error_patterns: str = ""  # project override (JSON list)

    model_config = {"env_prefix": "", "case_sensitive": False}

    def model_post_init(self, __context: Any) -> None:
        if self.cq_siyuan_url and not self.cq_siyuan_token.get_secret_value():
            warnings.warn(
                "CQ_SIYUAN_URL is set but CQ_SIYUAN_TOKEN is empty. "
                "Siyuan sync will be unauthenticated.",
                stacklevel=2,
            )

    def ensure_api_key(self) -> str:
        """Return the API key, generating one if not configured."""
        if self.mcp_stolperstein_api_key:
            return self.mcp_stolperstein_api_key

        from stolperstein.auth import generate_api_key

        key = generate_api_key()
        self.mcp_stolperstein_api_key = key
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
    def siyuan_enabled(self) -> bool:
        return bool(self.cq_siyuan_url)

    @property
    def team_sync_enabled(self) -> bool:
        return bool(self.cq_team_addr)

    @property
    def trusted_orgs_list(self) -> list[str]:
        """Parsed comma-separated DIDs; `['*']` means trust-all."""
        raw = self.trusted_orgs.strip()
        if not raw:
            return ["*"]
        return [t.strip() for t in raw.split(",") if t.strip()]


settings = Settings()
