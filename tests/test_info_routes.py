# -*- coding: utf-8 -*-
"""Tests for the More-Info routes: the self-sufficient details bundle, the seasons
list, and server-side-resolved next-episode. Output is captured by intercepting
xbmcplugin.addDirectoryItem (the stub is a no-op)."""
import pytest
import xbmcplugin

from resources.lib.info_routes import InfoHandler
import resources.lib.info_routes as info_routes
import resources.lib.season_map as season_map
from resources.lib import progress, resume


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
    def __init__(self, media, progress=0, on_list=False, has_token=False, rating=""):
        self._media = media
        self._progress = progress
        self._on_list = on_list
        self._has_token = has_token
        self._rating = rating

    def resolve_mal_id(self, params):
        return self._media.get("idMal")

    def get_media(self, mal_id=None, anilist_id=None):
        return self._media

    def has_token(self):
        return self._has_token

    def list_state(self, media_id):
        return {"planning": self._on_list, "rating": self._rating}


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

    def test_onmylist_true_when_on_planning(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "details", "mal_id": "40748"})
        h.client = FakeClient(media, on_list=True, has_token=True)
        monkeypatch.setattr("resources.lib.info_routes.franchise_show_title", lambda f, t: "Demon Slayer")
        monkeypatch.setattr(h, "_franchise", lambda m=None: _two_season_franchise(media))
        h.details()
        assert captured[0][1].getProperty("OnMyList") == "true"

    def test_onmylist_empty_when_not_on_planning(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "details", "mal_id": "40748"})
        h.client = FakeClient(media, on_list=False, has_token=True)
        monkeypatch.setattr("resources.lib.info_routes.franchise_show_title", lambda f, t: "Demon Slayer")
        monkeypatch.setattr(h, "_franchise", lambda m=None: _two_season_franchise(media))
        h.details()
        assert captured[0][1].getProperty("OnMyList") == ""

    def test_onmylist_set_under_cacheonly(self, monkeypatch, captured):
        # The skin's 17195 detail loader ALWAYS calls details with cacheonly=true,
        # so OnMyList/MyRating must be set on the cached load too (was the bug:
        # gating it behind a live load left the button stuck on "Add to Favorite").
        media = _media()
        h = InfoHandler(1, {"info": "details", "mal_id": "40748", "cacheonly": "true"})
        h.client = FakeClient(media, on_list=True, has_token=True)
        h.details()
        assert captured[0][1].getProperty("OnMyList") == "true"

    def test_myrating_reflected_on_detail(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "details", "mal_id": "40748", "cacheonly": "true"})
        h.client = FakeClient(media, on_list=False, has_token=True, rating="like")
        h.details()
        assert captured[0][1].getProperty("MyRating") == "like"

    def test_onmylist_empty_without_token(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "details", "mal_id": "40748", "cacheonly": "true"})
        h.client = FakeClient(media, on_list=True, has_token=False)
        h.details()
        assert captured[0][1].getProperty("OnMyList") == ""


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


class TestUpcomingEntry:
    """A not-yet-aired entry (e.g. Mushoku Tensei S3, premieres 2026-07-06) has no
    aired episodes -- show a non-playable 'Premieres <date>' row, not a blank list."""

    def test_not_yet_released_shows_premiere_placeholder(self, monkeypatch, captured):
        media = {
            "idMal": 59193, "id": 178789, "format": "TV",
            "status": "NOT_YET_RELEASED", "episodes": None,
            "startDate": {"year": 2026, "month": 7, "day": 6},
            "title": {"romaji": "Mushoku Tensei III"},
            "nextAiringEpisode": {"episode": 1},
        }
        h = InfoHandler(1, {"info": "episodes", "mal_id": "59193"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: None)
        h.episodes()
        assert len(captured) == 1
        li = captured[0][1]
        assert li.label == "Premieres Jul 6, 2026"
        assert li.getProperty("IsPlayable") == "false"

    def test_aired_show_lists_episodes_not_placeholder(self, monkeypatch, captured):
        media = _media()  # RELEASING-style, 7 aired (nextAiringEpisode 8)
        media["status"] = "RELEASING"
        h = InfoHandler(1, {"info": "episodes", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: None)
        monkeypatch.setattr("resources.lib.tmdb.episode_stills", lambda *a, **k: {})
        h.episodes()
        assert len(captured) == 7
        assert all("Premieres" not in c[1].label for c in captured)


class TestEpisodeProgressBar:
    """The episode-thumbnail progress bar reflects the ACTUAL watched fraction:
    a partial Kodi resume point for the in-progress episode (drives the skin's
    PercentPlayed bar), playcount for completed episodes (the skin's full bar), and
    neither for unwatched episodes."""

    def _by_episode(self, captured):
        out = {}
        for _url, li, _folder in captured:
            for part in (li.getPath() or "").split("&"):
                if part.startswith("episode="):
                    out[int(part.split("=")[1])] = li
        return out

    def _run(self, monkeypatch, captured, media):
        h = InfoHandler(1, {"info": "episodes", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        monkeypatch.setattr("resources.lib.tmdb.episode_stills", lambda *a, **k: {})
        h.episodes()
        return self._by_episode(captured)

    def test_in_progress_episode_gets_partial_resume_point(self, monkeypatch, captured):
        resume.set_point(101922, 3, 600, 1440)  # stopped 10 min into a 24 min episode (anilist id)
        items = self._run(monkeypatch, captured, _media())
        tag = items[3].getVideoInfoTag()
        assert tag.isResumable() is True
        assert tag.getPercentPlayed() == 42  # round(600/1440*100) -> partial bar
        assert items[3]._info["video"]["playcount"] == 0

    def test_completed_episode_full_bar_no_resume(self, monkeypatch, captured):
        progress.apply_anilist(101922, 40748, 2, total=26)  # eps 1-2 completed
        items = self._run(monkeypatch, captured, _media())
        assert items[1]._info["video"]["playcount"] == 1
        assert items[1].getVideoInfoTag().isResumable() is False

    def test_unwatched_episode_has_no_bar(self, monkeypatch, captured):
        items = self._run(monkeypatch, captured, _media())
        assert items[5]._info["video"]["playcount"] == 0
        assert items[5].getVideoInfoTag().isResumable() is False

    def test_resume_point_overrides_stale_watched_mark(self, monkeypatch, captured):
        # A live, unfinished resume point is authoritative: even if the episode-level
        # progress (e.g. AniList sync) counts ep2 as watched, a partway position wins
        # -> partial bar, not the full "completed" bar (the Re:Zero S4E5 case).
        resume.set_point(101922, 2, 600, 1440)
        progress.apply_anilist(101922, 40748, 2, total=26)
        items = self._run(monkeypatch, captured, _media())
        assert items[2]._info["video"]["playcount"] == 0
        assert items[2].getVideoInfoTag().isResumable() is True
        assert items[2].getVideoInfoTag().getPercentPlayed() == 42


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

    def test_episodes_register_native_sort_methods(self, monkeypatch, captured):
        # NONE first => default follows the helper's newest-first emit order; Episode
        # and Date are offered in the drawer for the user to switch to.
        calls = []
        monkeypatch.setattr(xbmcplugin, "addSortMethod", lambda h, m: calls.append(m))
        media = _media()
        h = InfoHandler(1, {"info": "episodes", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.episodes()
        assert calls and calls[0] == xbmcplugin.SORT_METHOD_NONE
        assert xbmcplugin.SORT_METHOD_EPISODE in calls
        assert xbmcplugin.SORT_METHOD_DATEADDED in calls

    def test_seasons_keep_insertion_order(self, monkeypatch, captured):
        calls = []
        monkeypatch.setattr(xbmcplugin, "addSortMethod", lambda h, m: calls.append(m))
        media = _media()
        h = InfoHandler(1, {"info": "seasons", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.seasons()
        # NONE first (default = newest-first emit order) + Year/Label for the drawer.
        assert calls[0] == xbmcplugin.SORT_METHOD_NONE
        assert xbmcplugin.SORT_METHOD_VIDEO_YEAR in calls


class TestSharedTmdbSeason:
    """Re:Zero shape: every anime season maps to the SAME TMDB id + season because
    TMDB lumps the whole show into one season with absolute episode numbering
    (id 65942 season 1 = 85 episodes spanning all 4 seasons). Each season's episode
    list must index TMDB by the cumulative offset, not restart at 1 -- otherwise
    every season showed season-1 stills/plots."""

    def _media(self, mal, eps):
        return {"idMal": mal, "id": mal, "format": "TV", "episodes": eps,
                "title": {"english": "Re:Zero"}}

    def _franchise(self):
        counts = {1: 25, 2: 25, 3: 16, 4: 19}
        groups = []
        for season, eps in counts.items():
            m = self._media(1000 + season, eps)
            cour = {"media": m, "mal_id": m["idMal"], "season": season,
                    "episodes": eps, "tmdb_id": 65942, "tmdb_season": 1}
            groups.append({"season": season, "mal_id": m["idMal"], "media": m,
                           "episodes": eps, "cours": [cour],
                           "tmdb_id": 65942, "tmdb_season": 1})
        return groups

    def _tmdb_eps(self):
        return {n: {"still": "http://img/%d.jpg" % n, "name": "TMDB ep %d" % n,
                    "plot": "p%d" % n, "aired": ""} for n in range(1, 86)}

    def _run(self, monkeypatch, captured, season, mal):
        franchise = self._franchise()
        media = franchise[season - 1]["media"]
        h = InfoHandler(1, {"info": "episodes", "mal_id": str(mal), "season": str(season)})
        h.client = FakeClient(media)
        monkeypatch.setattr("resources.lib.info_routes._sort_descending", lambda: False)
        monkeypatch.setattr("resources.lib.info_routes.franchise_show_title", lambda f, t: "Re:Zero")
        monkeypatch.setattr(h, "_franchise", lambda m=None: franchise)
        monkeypatch.setattr(
            "resources.lib.tmdb.episode_stills",
            lambda tid, season: self._tmdb_eps() if (tid == 65942 and season == 1) else {},
        )
        h.episodes()
        return captured

    def test_third_season_offset(self, monkeypatch, captured):
        self._run(monkeypatch, captured, 3, 1003)
        assert len(captured) == 16
        # S3 ep1 -> TMDB absolute ep 51 (offset 25 + 25), last -> 66
        assert "TMDB ep 51" in captured[0][1].label
        assert "TMDB ep 66" in captured[-1][1].label

    def test_fourth_season_offset(self, monkeypatch, captured):
        self._run(monkeypatch, captured, 4, 1004)
        assert len(captured) == 19
        # S4 ep1 -> TMDB absolute ep 67 (offset 25 + 25 + 16), NOT ep 1
        assert "TMDB ep 67" in captured[0][1].label
        assert "TMDB ep 85" in captured[-1][1].label
        # display number stays season-local
        assert captured[0][1].label.startswith("1. ")

    def test_first_season_unshifted(self, monkeypatch, captured):
        self._run(monkeypatch, captured, 1, 1001)
        assert len(captured) == 25
        assert "TMDB ep 1" in captured[0][1].label
        assert "TMDB ep 25" in captured[-1][1].label


class TestTraktUpNext:
    # _media() has AniList id 101922 / idMal 40748. Progress now lives in the unified
    # store keyed by AniList id, so tests seed it via progress.apply_anilist(...).
    def test_targets_next_unwatched_episode(self, monkeypatch, captured):
        media = _media()
        progress.apply_anilist(101922, 40748, 4, total=26)  # synced progress 4
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media)
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

    def test_nothing_watched_plays_episode_one(self, monkeypatch, captured):
        media = _media()
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media)  # nothing in the store -> progress 0
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.trakt_upnext()
        assert "episode=1" in captured[0][1].getPath()

    def test_caught_up_replays_last_released(self, monkeypatch, captured):
        # 7 aired (nextAiringEpisode 8), watched all 7 -> no next episode exists yet,
        # so Play falls back to the last released episode (7), not the unaired 8.
        media = _media()
        progress.apply_anilist(101922, 40748, 7, total=26)
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.trakt_upnext()
        assert "episode=7" in captured[0][1].getPath()

    def test_local_completion_resumes_without_anilist_login(self, monkeypatch, captured):
        # No AniList login, but local completions still land in the progress store
        # (keyed by the media's AniList id, present even without login) -> Play resumes
        # ep 4 instead of dead-ending on ep 1.
        progress.mark_watched(101922, 40748, 3)
        media = _media()
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.trakt_upnext()
        assert "episode=4" in captured[0][1].getPath()

    def test_progress_store_never_regresses(self, monkeypatch, captured):
        # A local completion (ep 2) then a higher AniList sync (5) -> the store keeps the
        # max, so Play resumes ep 6 (progress never rolls back).
        progress.mark_watched(101922, 40748, 2)
        progress.apply_anilist(101922, 40748, 5, total=26)
        media = _media()
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.trakt_upnext()
        assert "episode=6" in captured[0][1].getPath()

    def test_resume_point_targets_in_progress_episode_not_next(self, monkeypatch, captured):
        # ep5 counts as watched at the episode level (AniList progress 5) but has a live
        # partway resume point -> Play resumes ep5, not ep6, and the item is resumable
        # so the skin renders "Resume 5" instead of "Play 6".
        progress.apply_anilist(101922, 40748, 5, total=26)
        resume.set_point(101922, 5, 600, 1440)
        media = _media()
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.trakt_upnext()
        li = captured[0][1]
        assert "episode=5" in li.getPath()
        assert li.getVideoInfoTag().isResumable() is True  # skin shows "Resume 5"

    def test_no_resume_point_targets_next_and_not_resumable(self, monkeypatch, captured):
        # Without a resume point the Play button advances normally and is NOT resumable
        # (skin shows "Play N").
        progress.apply_anilist(101922, 40748, 5, total=26)
        media = _media()
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media)
        monkeypatch.setattr(h, "_franchise", lambda m=None: [])
        h.trakt_upnext()
        li = captured[0][1]
        assert "episode=6" in li.getPath()
        assert li.getVideoInfoTag().isResumable() is False  # skin shows "Play 6"

    def test_franchise_advances_past_finished_season(self, monkeypatch, captured):
        # S1 fully aired (26 eps) + fully watched -> advance to S2; S2 has 11 eps,
        # watched 3 -> resume at S2 ep 4. Progress keyed by each cour's AniList id.
        s1 = {"idMal": 40748, "id": 1, "episodes": 26, "title": {"english": "S1"}}
        s2 = {"idMal": 99999, "id": 2, "episodes": 11, "title": {"english": "S2"}}
        progress.apply_anilist(1, 40748, 26, total=26)
        progress.apply_anilist(2, 99999, 3, total=11)
        franchise = [
            {"season": 1, "cours": [{"mal_id": 40748, "media": s1, "season": 1}]},
            {"season": 2, "cours": [{"mal_id": 99999, "media": s2, "season": 2}]},
        ]
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(s1)
        monkeypatch.setattr(h, "_franchise", lambda m=None: franchise)
        monkeypatch.setattr(info_routes, "franchise_show_title", lambda f, t: "Show")
        h.trakt_upnext()
        path = captured[0][1].getPath()
        assert "mal_id=99999" in path
        assert "episode=4" in path

    def test_resumes_latest_watched_when_opening_unwatched_earlier_season(self, monkeypatch, captured):
        # User opened S1 (never watched) but is mid-S2 (ep 5 of 11). "Resume latest
        # watched" -> jump to S2 ep 6, NOT S1 ep 1.
        s1 = {"idMal": 40748, "id": 1, "episodes": 26, "title": {"english": "S1"}}
        s2 = {"idMal": 99999, "id": 2, "episodes": 11, "title": {"english": "S2"}}
        progress.apply_anilist(2, 99999, 5, total=11)  # S1 untouched, S2 in progress
        franchise = [
            {"season": 1, "cours": [{"mal_id": 40748, "media": s1, "season": 1}]},
            {"season": 2, "cours": [{"mal_id": 99999, "media": s2, "season": 2}]},
        ]
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})  # opened S1
        h.client = FakeClient(s1)
        monkeypatch.setattr(h, "_franchise", lambda m=None: franchise)
        monkeypatch.setattr(info_routes, "franchise_show_title", lambda f, t: "Show")
        h.trakt_upnext()
        path = captured[0][1].getPath()
        assert "mal_id=99999" in path
        assert "episode=6" in path

    def test_fast_path_skips_franchise_when_viewed_cour_in_progress(self, monkeypatch, captured):
        # Opening the season you're watching resolves directly without collecting the
        # franchise (the slow path) -- _franchise must not even be called.
        media = _media()  # 7 aired (nextAiringEpisode 8)
        progress.apply_anilist(101922, 40748, 4, total=26)
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media)
        franchise_calls = []
        monkeypatch.setattr(h, "_franchise", lambda m=None: franchise_calls.append(1) or [])
        h.trakt_upnext()
        assert "episode=5" in captured[0][1].getPath()
        assert franchise_calls == []  # fast path: franchise never collected

    def test_monolith_skips_franchise(self, monkeypatch, captured):
        # A 1000-ep monolith with no progress resolves ep 1 directly -- never collects
        # the franchise (no TMDB season split on the Play path).
        media = _media()
        media["episodes"] = 1000
        media.pop("nextAiringEpisode", None)
        h = InfoHandler(1, {"info": "trakt_upnext", "mal_id": "40748"})
        h.client = FakeClient(media)
        franchise_calls = []
        monkeypatch.setattr(h, "_franchise", lambda m=None: franchise_calls.append(1) or [])
        h.trakt_upnext()
        assert "episode=1" in captured[0][1].getPath()
        assert franchise_calls == []


class TestPlayResume:
    def test_no_episode_is_resume_aware(self, monkeypatch):
        # The spotlight/hero Play routes through play() with no episode -> it must
        # resume the same way the More-Info Play (trakt_upnext) does.
        media = _media()  # 7 aired
        progress.apply_anilist(101922, 40748, 4, total=26)
        h = InfoHandler(1, {"info": "play", "mal_id": "40748"})
        h.client = FakeClient(media)
        seen = {}

        def fake_resolve(**kwargs):
            seen["episode"] = kwargs.get("episode")
            return None  # short-circuit before actual playback

        monkeypatch.setattr(info_routes, "resolve_play_path", fake_resolve)
        monkeypatch.setattr(info_routes, "log_missing_plugin", lambda *a, **k: None)
        monkeypatch.setattr(xbmcplugin, "setResolvedUrl", lambda *a, **k: None)
        h.play()
        assert seen["episode"] == "5"  # progress 4 -> resume ep 5


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
