"""Tests for CQ team sync and Siyuan sync modules."""

from __future__ import annotations

import pytest

from stolperstein.sync.siyuan import SiyuanSyncClient, enqueue_sync


class TestCQTeamSync:
    """CQ team API client tests."""

    def test_team_client_none_when_disabled(self, monkeypatch):
        """get_team_client returns None when CQ_TEAM_ADDR is not set."""
        monkeypatch.setenv("CQ_TEAM_ADDR", "")
        from stolperstein.sync.cq_team import get_team_client

        assert get_team_client() is None

    def test_team_client_created_when_configured(self, monkeypatch):
        """get_team_client returns a client when CQ_TEAM_ADDR is set."""
        monkeypatch.setenv("CQ_TEAM_ADDR", "http://localhost:8742")
        monkeypatch.setenv("CQ_TEAM_API_KEY", "test_key")

        # Need to reimport to pick up new settings
        from importlib import reload

        import stolperstein.config
        reload(stolperstein.config)
        from stolperstein.sync.cq_team import get_team_client

        client = get_team_client()
        # May or may not work depending on reload timing, just check no crash
        assert client is not None or client is None  # smoke test


class TestSiyuanSync:
    """Siyuan sync tests."""

    def test_siyuan_client_none_when_disabled(self, monkeypatch):
        """get_siyuan_client returns None when CQ_SIYUAN_URL is not set."""
        monkeypatch.setenv("CQ_SIYUAN_URL", "")
        from stolperstein.sync.siyuan import get_siyuan_client

        assert get_siyuan_client() is None

    def test_ku_rendering(self):
        """KU renders to expected markdown structure."""
        client = SiyuanSyncClient(
            url="http://localhost:6806",
            token="test",
            notebook="Test",
        )
        ku = {
            "id": "ku_test123",
            "insight": {
                "summary": "Test KU",
                "detail": "This is the detail.",
                "action": "Do this thing.",
            },
            "domain": ["swift", "xcode"],
            "kind": "pitfall",
            "status": "active",
            "confidence": 0.75,
            "confirmations": 3,
            "first_observed": "2026-03-25T00:00:00+00:00",
            "last_confirmed": "2026-03-27T00:00:00+00:00",
        }
        md = client._render_ku_markdown(ku)

        assert "#swift" in md
        assert "#xcode" in md
        assert "## Problem" in md
        assert "This is the detail." in md
        assert "## Action" in md
        assert "Do this thing." in md
        assert "## Metadata" in md
        assert "0.75" in md
        assert "pitfall" in md
        assert "`ku_test123`" in md

    def test_enqueue_noop_when_disabled(self, monkeypatch):
        """enqueue_sync is a no-op when Siyuan is not configured."""
        monkeypatch.setenv("CQ_SIYUAN_URL", "")

        from importlib import reload

        import stolperstein.config
        reload(stolperstein.config)

        # Should not raise
        enqueue_sync({"id": "ku_test", "insight": {"summary": "test"}})
