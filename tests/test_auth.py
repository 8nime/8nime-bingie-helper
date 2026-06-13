# -*- coding: utf-8 -*-
"""Tests for auth.py — helper-owned AniList token with two-way Otaku sharing."""
import xbmcaddon

from resources.lib import auth

OTAKU = "plugin.video.otaku"


def _set_otaku(token="", username=""):
    a = xbmcaddon.Addon(OTAKU)
    a.setSetting("anilist.token", token)
    a.setSetting("anilist.username", username)


def _get_otaku(key):
    return xbmcaddon.Addon(OTAKU).getSetting(key)


class TestReadPriority:
    def test_helper_token_wins_over_otaku(self):
        xbmcaddon.Addon().setSetting("anilist_token", "HELPER")
        _set_otaku("OTAKU")
        assert auth.get_anilist_token() == "HELPER"

    def test_otaku_token_used_when_helper_empty(self):
        _set_otaku("OTAKU")
        assert auth.get_anilist_token() == "OTAKU"

    def test_no_token_anywhere(self):
        assert auth.get_anilist_token() == ""
        assert auth.has_anilist_token() is False

    def test_username_priority(self):
        _set_otaku("t", "OtakuName")
        assert auth.get_anilist_username() == "OtakuName"
        xbmcaddon.Addon().setSetting("anilist_username", "HelperName")
        assert auth.get_anilist_username() == "HelperName"


class TestSetAndMirror:
    def test_set_writes_helper_and_mirrors_otaku(self):
        auth.set_anilist_token("TKN", "Neo")
        assert xbmcaddon.Addon().getSetting("anilist_token") == "TKN"
        assert xbmcaddon.Addon().getSetting("anilist_username") == "Neo"
        assert _get_otaku("anilist.token") == "TKN"
        assert _get_otaku("anilist.username") == "Neo"
        assert auth.has_anilist_token() is True

    def test_set_strips_whitespace(self):
        auth.set_anilist_token("  TKN  ", "  Neo  ")
        assert xbmcaddon.Addon().getSetting("anilist_token") == "TKN"
        assert xbmcaddon.Addon().getSetting("anilist_username") == "Neo"

    def test_clear_clears_helper_and_otaku(self):
        auth.set_anilist_token("TKN", "Neo")
        auth.clear_anilist_token()
        assert auth.get_anilist_token() == ""
        assert xbmcaddon.Addon().getSetting("anilist_username") == ""
        assert _get_otaku("anilist.token") == ""
        assert _get_otaku("anilist.username") == ""

    def test_mirror_skipped_when_otaku_absent(self, monkeypatch):
        real_addon = xbmcaddon.Addon

        def fake_addon(addon_id=None):
            if addon_id == OTAKU:
                raise RuntimeError("addon not installed")
            return real_addon(addon_id)

        monkeypatch.setattr(xbmcaddon, "Addon", fake_addon)
        # Must not raise even though Otaku is "absent"; helper still stores the token.
        auth.set_anilist_token("TKN", "Neo")
        assert auth.get_anilist_token() == "TKN"
