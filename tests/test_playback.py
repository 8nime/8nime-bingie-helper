# -*- coding: utf-8 -*-
"""Playback provider selection / routing tests."""
from unittest.mock import patch

from resources.lib import playback


class TestProviderIds:
    def test_fanimef_real_id(self):
        # Regression: was plugin.video.fanime_f (nonexistent) and dead-ended.
        assert playback.PLUGIN_IDS[playback.PLAYBACK_FANIME_F] == "plugin.video.fanimef"

    def test_watchnixtoons2_id(self):
        assert playback.PLUGIN_IDS[playback.PLAYBACK_WATCHNIXTOONS2] == "plugin.video.watchnixtoons2"

    def test_otaku_id(self):
        assert playback.PLUGIN_IDS[playback.PLAYBACK_OTAKU] == "plugin.video.otaku"


class TestDefaultProvider:
    def test_empty_setting_defaults_to_watchnixtoons2(self):
        with patch.object(playback.ADDON, "getSetting", return_value=""):
            assert playback.get_playback_key() == playback.PLAYBACK_WATCHNIXTOONS2
            assert playback.get_playback_plugin() == "plugin.video.watchnixtoons2"

    def test_invalid_setting_falls_back_to_watchnixtoons2(self):
        with patch.object(playback.ADDON, "getSetting", return_value="bogus"):
            assert playback.get_playback_key() == playback.PLAYBACK_WATCHNIXTOONS2

    def test_explicit_setting_wins(self):
        with patch.object(playback.ADDON, "getSetting", return_value="fanime_f"):
            assert playback.get_playback_key() == playback.PLAYBACK_FANIME_F
            assert playback.get_playback_plugin() == "plugin.video.fanimef"


class TestFanimeSearchRoute:
    def test_route_is_keyboard_search(self):
        # fanimef has no query param; mode=8 needs a non-empty url or it falls to
        # the main menu, and mode=search crashed it (int("search")).
        assert playback._fanime_search("Some Title") == (
            "plugin://plugin.video.fanimef/?mode=8&url=search"
        )


class TestPlayMoviePath:
    def test_otaku_movie_uses_play_movie_route(self):
        with patch.object(playback.ADDON, "getSetting", return_value="otaku"):
            path = playback.play_movie_path({"idMal": 199}, title="Spirited Away")
        assert path == "plugin://plugin.video.otaku/play_movie/199/"
