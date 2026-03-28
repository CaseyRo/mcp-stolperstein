"""One-way async sync of active KUs to a Siyuan notebook."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from stolperstein.config import settings

logger = logging.getLogger(__name__)

# Async queue for non-blocking sync
_sync_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
_worker_started = False


class SiyuanSyncClient:
    """Push KUs to Siyuan as structured documents."""

    def __init__(self, url: str, token: str, notebook: str) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._notebook = notebook
        self._notebook_id: str | None = None

    async def _api(self, endpoint: str, payload: dict) -> dict:
        headers = {}
        if self._token:
            headers["Authorization"] = f"Token {self._token}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._url}/api{endpoint}",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Siyuan API error: {data.get('msg')}")
            return data.get("data", {})

    async def _ensure_notebook(self) -> str:
        """Find or remember the target notebook ID."""
        if self._notebook_id:
            return self._notebook_id

        data = await self._api("/notebook/lsNotebooks", {})
        for nb in data.get("notebooks", []):
            if nb["name"] == self._notebook:
                self._notebook_id = nb["id"]
                return self._notebook_id

        raise RuntimeError(f"Siyuan notebook '{self._notebook}' not found")

    def _render_ku_markdown(self, ku: dict) -> str:
        """Render a KU as structured Siyuan markdown."""
        insight = ku.get("insight", {})
        domain = ku.get("domain", [])
        tags = " ".join(f"#{t}" for t in domain)

        return f"""{tags}

## Problem

{insight.get('detail', '')}

## Action

{insight.get('action', '')}

## Metadata

| Field | Value |
|-------|-------|
| Kind | {ku.get('kind', '')} |
| Status | {ku.get('status', '')} |
| Confidence | {ku.get('confidence', 0)} |
| Confirmations | {ku.get('confirmations', 0)} |
| First Observed | {ku.get('first_observed', '')} |
| Last Confirmed | {ku.get('last_confirmed', '')} |
| ID | `{ku.get('id', '')}` |
"""

    async def sync_ku(self, ku: dict, action: str = "upsert") -> None:
        """Create or update a KU document in Siyuan."""
        notebook_id = await self._ensure_notebook()
        insight = ku.get("insight", {})
        title = insight.get("summary", ku.get("id", "Untitled KU"))
        content = self._render_ku_markdown(ku)

        if action == "archive":
            # TODO: move to archive sub-path or delete
            logger.info("KU %s archived (Siyuan sync skipped for archives)", ku.get("id"))
            return

        # Use upsert: search by title, update if exists, create if not
        # Search for existing doc with matching title
        try:
            search_data = await self._api("/search/searchDoc", {
                "k": title,
                "types": {"document": True},
            })
            existing = [
                d for d in search_data.get("data", [])
                if d.get("hPath", "").endswith(f"/{title}")
                and d.get("box") == notebook_id
            ]
        except Exception:
            existing = []

        if existing:
            # Update existing document
            doc_id = existing[0]["id"]
            await self._api("/block/updateBlock", {
                "id": doc_id,
                "dataType": "markdown",
                "data": content,
            })
            logger.info("Updated Siyuan doc for KU %s", ku.get("id"))
        else:
            # Create new document
            await self._api("/filetree/createDocWithMd", {
                "notebook": notebook_id,
                "path": f"/{title}",
                "markdown": content,
            })
            logger.info("Created Siyuan doc for KU %s", ku.get("id"))


async def _sync_worker() -> None:
    """Background worker that processes the sync queue."""
    client = get_siyuan_client()
    if not client:
        return

    while True:
        item = await _sync_queue.get()
        retries = 0
        max_retries = 3

        while retries < max_retries:
            try:
                await client.sync_ku(item["ku"], item.get("action", "upsert"))
                break
            except Exception:
                retries += 1
                if retries < max_retries:
                    wait = 2**retries
                    logger.warning(
                        "Siyuan sync failed (retry %d/%d in %ds)",
                        retries, max_retries, wait, exc_info=True,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("Siyuan sync failed after %d retries", max_retries, exc_info=True)

        _sync_queue.task_done()


def enqueue_sync(ku: dict, action: str = "upsert") -> None:
    """Enqueue a KU for async Siyuan sync. Non-blocking, fire-and-forget."""
    if not settings.siyuan_enabled:
        return

    global _worker_started
    if not _worker_started:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_sync_worker())
            _worker_started = True
        except RuntimeError:
            logger.warning("No running event loop for Siyuan sync worker")
            return

    try:
        _sync_queue.put_nowait({"ku": ku, "action": action})
    except asyncio.QueueFull:
        logger.warning("Siyuan sync queue full, dropping sync for KU %s", ku.get("id"))


def get_siyuan_client() -> SiyuanSyncClient | None:
    """Create Siyuan client if configured."""
    if not settings.siyuan_enabled:
        return None
    return SiyuanSyncClient(
        url=settings.cq_siyuan_url,
        token=settings.cq_siyuan_token.get_secret_value(),
        notebook=settings.cq_siyuan_notebook,
    )
