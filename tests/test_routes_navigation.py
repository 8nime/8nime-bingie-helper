# -*- coding: utf-8 -*-
"""Directory-entry click semantics + name-sort for the category browses.

In a real browsable window (All Series / Specials / All Movies, search, My List)
there is no custom skin onclick, so Kodi's default click behaviour must work:
shows are folders that navigate into their seasons, movies are playable leaves.
Widgets keep the legacy (base-path, non-folder) form so the skin's home/spotlight
onclicks keep driving navigation off the item PROPERTIES.
"""
from unittest.mock import patch

import xbmcgui

from resources.lib.constants import PLUGIN_URL
from resources.lib.routes import RouteHandler


def _tv_item(folderpath="plugin://plugin.video.8nime.bingie.helper/?info=seasons&mal_id=1"):
    li = xbmcgui.ListItem(label="A Show")
    li.setProperty("IsPlayable", "false")
    li.setProperty("folderpath", folderpath)
    li.setPath(PLUGIN_URL)
    return li


def _movie_item(play="plugin://plugin.video.8nime.bingie.helper/?info=play&mal_id=2&tmdb_type=movie"):
    li = xbmcgui.ListItem(label="A Movie")
    li.setProperty("IsPlayable", "true")
    li.setProperty("folderpath", play)
    li.setPath(play)
    return li


class TestDirectoryEntries:
    def test_window_show_is_folder_to_seasons(self):
        h = RouteHandler(1, {"info": "dir_tv"})
        tv = _tv_item()
        entries = h._directory_entries([tv])
        assert len(entries) == 1
        path, li, is_folder = entries[0]
        assert is_folder is True
        assert path == tv.getProperty("folderpath")
        assert path != PLUGIN_URL

    def test_window_movie_is_playable_leaf(self):
        h = RouteHandler(1, {"info": "dir_movie"})
        mv = _movie_item()
        path, li, is_folder = h._directory_entries([mv])[0]
        assert is_folder is False
        assert path == mv.getPath()
        assert "info=play" in path

    def test_window_show_without_folderpath_is_not_a_dead_folder(self):
        # If a show has no nav url, fall back to base path AND don't mark it a
        # folder (a folder pointing at the bare base url would open empty).
        h = RouteHandler(1, {"info": "dir_tv"})
        tv = xbmcgui.ListItem(label="No Nav")
        tv.setProperty("IsPlayable", "false")
        tv.setPath(PLUGIN_URL)
        path, li, is_folder = h._directory_entries([tv])[0]
        assert path == PLUGIN_URL
        assert is_folder is False

    def test_widget_keeps_legacy_non_folder_base_path(self):
        h = RouteHandler(1, {"info": "trakt_popular", "widget": "true"})
        assert h.is_widget is True
        tv, mv = _tv_item(), _movie_item()
        entries = h._directory_entries([tv, mv])
        assert all(is_folder is False for _, _, is_folder in entries)
        assert entries[0][0] == tv.getPath()  # base url, skin onclick drives nav
        assert entries[1][0] == mv.getPath()


class TestCategoryNameSort:
    def test_dir_all_sorts_by_title(self):
        captured = {}

        def browse(variables, trending=False):
            captured.update(variables)
            return ([], False)

        h = RouteHandler(1, {"info": "dir_tv", "page": "1"})
        h.client.browse = browse
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_all()
        assert captured["sort"] == ["TITLE_ENGLISH"]  # default title_language

    def test_dir_ova_sorts_by_title(self):
        captured = {}

        def browse(variables, trending=False):
            captured.update(variables)
            return ([], False)

        h = RouteHandler(1, {"info": "dir_ova", "page": "1"})
        h.client.browse = browse
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_ova()
        assert captured["sort"] == ["TITLE_ENGLISH"]

    def test_title_sort_follows_setting(self):
        from resources.lib import titles

        with patch.object(titles.ADDON, "getSetting", return_value="romaji"):
            assert titles.title_sort() == "TITLE_ROMAJI"
        with patch.object(titles.ADDON, "getSetting", return_value="english"):
            assert titles.title_sort() == "TITLE_ENGLISH"
        with patch.object(titles.ADDON, "getSetting", return_value=""):
            assert titles.title_sort() == "TITLE_ENGLISH"  # default


class TestCategorySearchSort:
    def _capture(self):
        captured = {}

        def browse(variables, trending=False):
            captured.update(variables)
            return ([], False)

        return captured, browse

    def test_search_param_passed_and_ranks_by_relevance(self):
        captured, browse = self._capture()
        h = RouteHandler(1, {"info": "dir_tv", "search": " naruto "})
        h.client.browse = browse
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_all()
        assert captured["search"] == "naruto"  # trimmed
        assert captured["sort"] == ["SEARCH_MATCH", "POPULARITY_DESC"]

    def test_explicit_sort_overrides_default(self):
        captured, browse = self._capture()
        h = RouteHandler(1, {"info": "dir_tv", "sort": "score"})
        h.client.browse = browse
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_all()
        assert captured["sort"] == ["SCORE_DESC"]
        assert "search" not in captured

    def test_search_plus_explicit_sort(self):
        captured, browse = self._capture()
        h = RouteHandler(1, {"info": "dir_movie", "search": "your name", "sort": "newest"})
        h.client.browse = browse
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_all()
        assert captured["search"] == "your name"
        assert captured["sort"] == ["START_DATE_DESC"]

    def test_no_search_no_sort_is_alphabetical(self):
        captured, browse = self._capture()
        h = RouteHandler(1, {"info": "dir_tv"})
        h.client.browse = browse
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_all()
        assert captured["sort"] == ["TITLE_ENGLISH"]  # default title_sort
        assert "search" not in captured

    def test_ova_search(self):
        captured, browse = self._capture()
        h = RouteHandler(1, {"info": "dir_ova", "search": "evangelion"})
        h.client.browse = browse
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_ova()
        assert captured["search"] == "evangelion"
        assert captured["format"] == ["OVA", "ONA", "SPECIAL"]
