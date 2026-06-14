# -*- coding: utf-8 -*-
"""Smoke tests for the boot service's one-shot progress sync (service.sync_now)."""
import service


class TestServiceSync:
    def test_syncs_when_logged_in(self, monkeypatch):
        called = {}

        class FakeClient:
            def sync_progress(self):
                called["hit"] = True
                return 42

        monkeypatch.setattr(service, "has_anilist_token", lambda: True)
        monkeypatch.setattr(service, "AniListClient", FakeClient)
        assert service.sync_now() == 42
        assert called.get("hit") is True

    def test_noop_without_token(self, monkeypatch):
        def _must_not_construct():
            raise AssertionError("AniListClient must not be built without a token")

        monkeypatch.setattr(service, "has_anilist_token", lambda: False)
        monkeypatch.setattr(service, "AniListClient", _must_not_construct)
        assert service.sync_now() == 0

    def test_sync_failure_is_swallowed(self, monkeypatch):
        class BoomClient:
            def sync_progress(self):
                raise RuntimeError("network down")

        monkeypatch.setattr(service, "has_anilist_token", lambda: True)
        monkeypatch.setattr(service, "AniListClient", BoomClient)
        assert service.sync_now() == 0  # logged + swallowed, never raises
