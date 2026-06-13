# -*- coding: utf-8 -*-
"""Tests for the More-Info routes: the self-sufficient details bundle, the seasons
list, and server-side-resolved next-episode. Output is captured by intercepting
xbmcplugin.addDirectoryItem (the stub is a no-op)."""
import pytest
import xbmcplugin

from resources.lib.info_routes import InfoHandler
import resources.lib.info_routes as info_routes
import resources.lib.season_map as season_map


def _reset_season_map():
    season_map._BY_ANILIST = {}
    season_map._BY_MAL = {}
    season_map._TVDB_MEMBERS = {}
    season_map._LOADED = True
    season_map._BY_TMDB = None
    season_map._BY_TMDB_SRC = None


@pytest.fixture
def captured(monkeypatch):
    items = []

    def _add(handle, url, li, is_folder=False, total_items=0):
        items.append((url, li, is_folder))

    monkeypatch.setattr(xbmcplugin, "addDirectoryItem", _add)
    monkeypatch.setattr(xbmcplugin, "endOfDirectory", lambda *a, **k: None)
    monkeypatch.setattr(xbmcplugin, "setContent", lambda *a, **k: None)
    _reset_season_map()
    return items


class FakeClient:
    def __init__(self, media, progress=0):
        self._media = media
        self._progress = progress

    def resolve_mal_id(self, params):
        return self._media.get("idMal")

    def get_media(self, mal_id=None, anilist_id=None):
        return self._media

    def get_progress(self, mal_id):
        return self._progress


def _media(mal=40748, anilist=101922, episodes=26, fmt="TV"):
    return {
        "idMal": mal,
        "id": anilist,
        "format": fmt,
        "episodes": episodes,
        "averageScore": 83,
        "genres": ["Action"],
        "title": {"english": "Demon Slayer", "romaji": "Kimetsu"},
        "nextAiringEpisode": {"episode": 8},  # 7 aired
    }


def _two_season_franchise(media):
    s2 = {"idMal": 99999, "id": 2, "episodes": 11, "title": {"english": "S2"}}
    return [
        {"season": 1, "mal_id": 40748, "media": media, "cours": [{"media": media}],
         "tmdb_id": None, "tmdb_season": None},
        {"season": 2, "mal_id": 99999, "media": s2, "cours": [{"media": s2}],
         "tmdb_id": None, "tmdb_season": None},
    ]


class TestDetails:
    def test_bundles_seasons_and_totals(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "details", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr("resources.lib.info_routes.franchise_show_title", lambda f, t: "Demon Slayer")
        monkeypatch.setattr(h, "_franchise", lambda m=None: _two_season_franchise(media))
        h.details()
        # header item + 2 season items
        assert len(captured) == 3
        detail = captured[0][1]
        assert detail.getProperty("TotalSeasons") == "2"
        assert detail.getProperty("TotalEpisodes") == "37"  # 26 + 11
        assert detail.getProperty("LatestEpisode") == "7"   # nextAiring 8 -> 7 aired
        # the two season tiles are folders
        assert captured[1][2] is True and captured[2][2] is True

    def test_cacheonly_returns_header_only(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "details", "mal_id": "40748", "cacheonly": "true"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: _two_season_franchise(media))
        h.details()
        assert len(captured) == 1  # no season enumeration under cacheonly

    def test_movie_has_no_seasons(self, captured):
        media = _media(fmt="MOVIE", episodes=1)
        h = InfoHandler(1, {"info": "details", "mal_id": "40748"})
        h.client = FakeClient(media)
        h.details()
        assert len(captured) == 1


class TestSeasons:
    def test_lists_franchise_seasons_as_folders(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "seasons", "mal_id": "40748"})
        h.client = FakeClient(media)
        # Pin ascending so season 1 lands first regardless of the sort-order default.
        monkeypatch.setattr("resources.lib.info_routes._sort_descending", lambda: False)
        monkeypatch.setattr("resources.lib.info_routes.franchise_show_title", lambda f, t: "Demon Slayer")
        monkeypatch.setattr(h, "_franchise", lambda m=None: _two_season_franchise(media))
        h.seasons()
        assert len(captured) == 2
        assert all(folder for (_u, _li, folder) in captured)
        # season tiles carry per-season metadata (year/rating via build_season_item)
        assert captured[0][1].getProperty("mal_id") == "40748"


def _one_piece_split_franchise(media):
    """Two TMDB-split seasons of a single monolithic media (offsets 0 and 61)."""
    c1 = {"media": media, "mal_id": 21, "season": 1, "episodes": 61,
          "tmdb_id": 37854, "tmdb_season": 1, "_episode_count": 61, "_play_offset": 0,
          "_tmdb_split": True, "start_key": (1999, 10, 20, 21)}
    c2 = {"media": media, "mal_id": 21, "season": 2, "episodes": 16,
          "tmdb_id": 37854, "tmdb_season": 2, "_episode_count": 16, "_play_offset": 61,
          "_tmdb_split": True, "start_key": (2001, 1, 1, 21)}
    return [
        {"season": 1, "mal_id": 21, "media": media, "cours": [c1],
         "tmdb_id": 37854, "tmdb_season": 1, "_tmdb_split": True, "episodes": 61},
        {"season": 2, "mal_id": 21, "media": media, "cours": [c2],
         "tmdb_id": 37854, "tmdb_season": 2, "_tmdb_split": True, "episodes": 16},
    ]


class TestTmdbSplitEpisodes:
    """One Piece S2: episodes display season-local (1..16) with real TMDB titles,
    but PLAY the absolute AniList episode (62..77)."""

    def test_split_season_local_display_absolute_play(self, monkeypatch, captured):
        media = _media(mal=21, anilist=21, episodes=1100)
        media.pop("nextAiringEpisode", None)  # treat as fully aired for the test
        h = InfoHandler(1, {"info": "episodes", "mal_id": "21", "season": "2"})
        h.client = FakeClient(media)
        # Pin ascending so the local/absolute mapping reads in episode order; the
        # display-vs-play mapping under test is independent of sort direction.
        monkeypatch.setattr("resources.lib.info_routes._sort_descending", lambda: False)
        monkeypatch.setattr("resources.lib.info_routes.franchise_show_title", lambda f, t: "One Piece")
        monkeypatch.setattr(h, "_franchise", lambda m=None: _one_piece_split_franchise(media))
        # TMDB numbers One Piece episodes ABSOLUTELY (S2 -> episode_number 62..77),
        # exactly as the live API does -- not season-local.
        s2 = {n: {"still": f"http://img/e{n}.jpg", "name": f"Arc2 Ep{n}",
                  "plot": f"plot {n}", "aired": ""} for n in range(62, 78)}
        monkeypatch.setattr(
            "resources.lib.tmdb.episode_stills",
            lambda tmdb_id, season: s2 if (tmdb_id == 37854 and season == 2) else {},
        )
        h.episodes()

        assert len(captured) == 16  # the TMDB season's count, not the whole 1100
        first_label = captured[0][1].label
        # Displayed season-local (1.) but titled from the ABSOLUTE TMDB episode (62)
        assert first_label.startswith("1. ") and "Arc2 Ep62" in first_label
        assert "episode=62" in captured[0][1].getPath()   # absolute play (offset 61 + local 1)
        assert "episode=77" in captured[-1][1].getPath()  # offset 61 + local 16


class TestSortOrder:
    """The `sort_order` setting flips the display order of the seasons list and the
    episode lists; default is newest-first (desc)."""

    def test_descending_is_the_default(self, monkeypatch):
        monkeypatch.setattr(info_routes._ADDON, "getSetting", lambda key: "")
        assert info_routes._sort_descending() is True

    def test_explicit_asc_disables_descending(self, monkeypatch):
        monkeypatch.setattr(info_routes._ADDON, "getSetting", lambda key: "asc")
        assert info_routes._sort_descending() is False

    def test_explicit_desc_enables_descending(self, monkeypatch):
        monkeypatch.setattr(info_routes._ADDON, "getSetting", lambda key: "DESC")
        assert info_routes._sort_descending() is True

    def test_ordered_reverses_when_descending(self, monkeypatch):
        monkeypatch.setattr(info_routes, "_sort_descending", lambda: True)
        assert info_routes._ordered([1, 2, 3]) == [3, 2, 1]

    def test_ordered_preserves_when_ascending(self, monkeypatch):
        monkeypatch.setattr(info_routes, "_sort_descending", lambda: False)
        assert info_routes._ordered([1, 2, 3]) == [1, 2, 3]

    def test_seasons_newest_first_by_default(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "seasons", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr("resources.lib.info_routes._sort_descending", lambda: True)
        monkeypatch.setattr("resources.lib.info_routes.franchise_show_title", lambda f, t: "Demon Slayer")
        monkeypatch.setattr(h, "_franchise", lambda m=None: _two_season_franchise(media))
        h.seasons()
        assert len(captured) == 2
        # newest season (S2, mal 99999) on top; S1 (mal 40748) last
        assert captured[0][1].getProperty("mal_id") == "99999"
        assert captured[-1][1].getProperty("mal_id") == "40748"
        assert all(folder for (_u, _li, folder) in captured)

    def test_episodes_newest_first_by_default(self, monkeypatch, captured):
        media = _media()  # episodes=26, nextAiring 8 -> 7 aired
        h = InfoHandler(1, {"info": "episodes", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr("resources.lib.info_routes._sort_descending", lambda: True)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.episodes()
        assert len(captured) == 7
        # latest aired episode (7) on top, episode 1 last
        assert "episode=7" in captured[0][1].getPath()
        assert "episode=1" in captured[-1][1].getPath()

    def test_episodes_oldest_first_when_ascending(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "episodes", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr("resources.lib.info_routes._sort_descending", lambda: False)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.episodes()
        assert len(captured) == 7
        assert "episode=1" in captured[0][1].getPath()
        assert "episode=7" in captured[-1][1].getPath()


class TestTraktUpNext:
    def test_targets_next_unwatched_episode(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media, progress=4)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])  # simple (non-franchise) branch
        h.trakt_upnext()
        assert len(captured) == 1
        path = captured[0][1].getPath()
        # the next-ep item's play path is the deferred info=play route that play()
        # resolves to the exact episode server-side at click time.
        assert "info=play" in path
        assert "mal_id=40748" in path
        assert "episode=5" in path  # progress 4 -> next 5
        assert captured[0][1].getProperty("IsPlayable") == "true"


class TestBaseSeriesTitle:
    def test_strips_season_marker(self):
        from resources.lib.info_routes import _base_series_title
        assert _base_series_title("that time i got reincarnated as a slime season 2") == \
            "that time i got reincarnated as a slime"

    def test_strips_ordinal_season(self):
        from resources.lib.info_routes import _base_series_title
        assert _base_series_title("mushoku tensei jobless reincarnation 2nd season") == \
            "mushoku tensei jobless reincarnation"

    def test_strips_season_and_part(self):
        from resources.lib.info_routes import _base_series_title
        assert _base_series_title("...slime season 2 part ii").endswith("slime")

    def test_strips_cour(self):
        from resources.lib.info_routes import _base_series_title
        assert _base_series_title("Mushoku Tensei: Jobless Reincarnation Cour 2") == \
            "Mushoku Tensei: Jobless Reincarnation"

    def test_no_marker_returns_none(self):
        from resources.lib.info_routes import _base_series_title
        assert _base_series_title("Frieren Beyond Journey's End") is None


class TestWnt2SeasonOffset:
    def _franchise(self):
        # Slime-shaped: S1 single cour, S2 two cours (12 + 12), S3 single cour.
        return [
            {"season": 1, "cours": [{"mal_id": 37430, "episodes": 24}]},
            {"season": 2, "cours": [{"mal_id": 39551, "episodes": 12},
                                    {"mal_id": 41487, "episodes": 12}]},
            {"season": 3, "cours": [{"mal_id": 53580, "episodes": 24}]},
        ]

    def test_first_cour_zero_offset(self, monkeypatch):
        h = InfoHandler(1, {"mal_id": "39551"})
        monkeypatch.setattr(h, "_franchise", lambda m=None: self._franchise())
        assert h._wnt2_season_offset(39551, {}) == (2, 0)

    def test_second_cour_carries_offset(self, monkeypatch):
        h = InfoHandler(1, {"mal_id": "41487"})
        monkeypatch.setattr(h, "_franchise", lambda m=None: self._franchise())
        # Slime S2 Part 2 starts after the 12 episodes of Part 1.
        assert h._wnt2_season_offset(41487, {}) == (2, 12)

    def test_later_season_zero_offset(self, monkeypatch):
        h = InfoHandler(1, {"mal_id": "53580"})
        monkeypatch.setattr(h, "_franchise", lambda m=None: self._franchise())
        assert h._wnt2_season_offset(53580, {}) == (3, 0)

    def test_no_franchise_defaults(self, monkeypatch):
        h = InfoHandler(1, {"mal_id": "1"})
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        assert h._wnt2_season_offset(1, {}) == (1, 0)

    def test_tmdb_split_monolith_defaults(self, monkeypatch):
        h = InfoHandler(1, {"mal_id": "21"})
        split = [{"season": 1, "_tmdb_split": True, "cours": [{"mal_id": 21, "episodes": 1100}]}]
        monkeypatch.setattr(h, "_franchise", lambda m=None: split)
        # Absolute numbering -> season-aware matching N/A; let number-only handle it.
        assert h._wnt2_season_offset(21, {}) == (1, 0)
