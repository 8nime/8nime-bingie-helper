# -*- coding: utf-8 -*-
"""Tests for window_state.py — the monitor's non-poll duties (auth/reload/fribb)."""
import xbmcgui

import resources.lib.window_state as window_state
import resources.lib.season_map as season_map
from resources.lib.constants import WIDGET_RELOAD_PROP


def _home():
    return xbmcgui.Window(window_state.HOME_WINDOW)


class TestAuthProperty:
    def test_sets_when_token(self, monkeypatch):
        monkeypatch.setattr("resources.lib.auth.has_anilist_token", lambda: True)
        _home().clearProperty(window_state.AUTH_PROP)
        window_state.sync_auth_property()
        assert _home().getProperty(window_state.AUTH_PROP) == "1"

    def test_clears_when_no_token(self, monkeypatch):
        monkeypatch.setattr("resources.lib.auth.has_anilist_token", lambda: False)
        _home().setProperty(window_state.AUTH_PROP, "1")
        window_state.sync_auth_property()
        assert _home().getProperty(window_state.AUTH_PROP) == ""


class TestWidgetReload:
    def test_bump_sets_changing_token(self):
        win = _home()
        window_state.bump_widget_reload()
        first = win.getProperty(WIDGET_RELOAD_PROP)
        assert first
        window_state.bump_widget_reload()
        second = win.getProperty(WIDGET_RELOAD_PROP)
        assert second and second != first


class TestEnsureFribbFresh:
    def test_kicks_once_when_cache_missing(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(season_map, "refresh_async", lambda: calls.append(1))
        monkeypatch.setattr(season_map, "_cache_path", lambda: str(tmp_path / "missing.json"))
        window_state._fribb_kicked = False
        window_state.ensure_fribb_fresh()
        window_state.ensure_fribb_fresh()  # per-process guard: no second kick
        assert calls == [1]

    def test_skips_when_cache_fresh(self, monkeypatch, tmp_path):
        calls = []
        fresh = tmp_path / "season_map.json"
        fresh.write_text("{}")
        monkeypatch.setattr(season_map, "refresh_async", lambda: calls.append(1))
        monkeypatch.setattr(season_map, "_cache_path", lambda: str(fresh))
        window_state._fribb_kicked = False
        window_state.ensure_fribb_fresh()
        assert calls == []
