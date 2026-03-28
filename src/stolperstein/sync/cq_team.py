"""Optional CQ team API sync — pull shared KUs and graduate local ones."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from stolperstein.config import settings

logger = logging.getLogger(__name__)


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
        """Query team tier for shared KUs."""
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
                return resp.json()
        except Exception:
            logger.warning("CQ team API query failed", exc_info=True)
            return []

    async def graduate(self, ku_json: dict[str, Any]) -> dict[str, Any] | None:
        """Graduate a local KU to the team tier."""
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
