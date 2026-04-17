"""Optional CQ team API sync — pull shared KUs and graduate local ones.

Outbound: always emits upstream-strict shape via `to_cq_json_strict()`.
Inbound: every payload is validated against the vendored upstream schema
and sanitized (tags stripped, lengths capped) before storage. A KU that
fails validation or exceeds length caps is rejected wholesale — no
partial ingest.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import jsonschema

from stolperstein.config import settings
from stolperstein.sanitize import OversizedError, sanitize_ku_dict

logger = logging.getLogger(__name__)

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "tests" / "fixtures" / "cq" / "knowledge_unit.json"
)
_CACHED_SCHEMA: dict | None = None


def _load_schema() -> dict:
    global _CACHED_SCHEMA
    if _CACHED_SCHEMA is None:
        _CACHED_SCHEMA = json.loads(_SCHEMA_PATH.read_text())
    return _CACHED_SCHEMA


def validate_and_sanitize_inbound(payload: dict) -> dict:
    """Validate an inbound KU payload against the vendored upstream schema
    and sanitize its text fields. Returns the cleaned payload, or raises.
    """
    cleaned = sanitize_ku_dict(payload)
    try:
        jsonschema.validate(cleaned, _load_schema())
    except jsonschema.ValidationError as e:
        raise ValueError(f"inbound KU failed CQ schema validation: {e.message}") from e
    return cleaned


class CQTeamClient:
    """HTTP client for the CQ team API."""

    def __init__(self, addr: str, api_key: str) -> None:
        self._addr = addr.rstrip("/")
        self._api_key = api_key

    async def query(
        self,
        domain: list[str] | None = None,
        confidence_min: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Query team tier for shared KUs. Returns only payloads that pass
        schema validation and sanitization; rejects are logged and dropped.
        """
        params: dict[str, Any] = {"confidence_min": confidence_min}
        if domain:
            params["domain"] = ",".join(domain)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._addr}/query",
                    params=params,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                resp.raise_for_status()
                raw = resp.json()
        except Exception:
            logger.warning("CQ team API query failed", exc_info=True)
            return []

        accepted: list[dict] = []
        for payload in raw if isinstance(raw, list) else []:
            try:
                accepted.append(validate_and_sanitize_inbound(payload))
            except (ValueError, OversizedError) as e:
                logger.warning(
                    "Rejected inbound team KU %s: %s",
                    payload.get("id", "<no id>"), e,
                )
        return accepted

    async def graduate(self, ku_json: dict[str, Any]) -> dict[str, Any] | None:
        """Graduate a local KU to the team tier. `ku_json` MUST be the
        output of `KnowledgeUnit.to_cq_json_strict()` — the wire shape.
        """
        # Defensive: strict-schema validate before posting so a bug in a
        # caller doesn't leak rich shape with extensions to the network.
        try:
            jsonschema.validate(ku_json, _load_schema())
        except jsonschema.ValidationError as e:
            logger.error(
                "Refusing to graduate KU %s: outbound payload failed strict-schema validation: %s",
                ku_json.get("id", "<no id>"), e.message,
            )
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._addr}/propose",
                    json=ku_json,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.warning("CQ team API graduation failed", exc_info=True)
            return None


def get_team_client() -> CQTeamClient | None:
    """Create team client if configured."""
    if not settings.team_sync_enabled:
        return None
    return CQTeamClient(
        addr=settings.cq_team_addr,
        api_key=settings.cq_team_api_key.get_secret_value(),
    )
