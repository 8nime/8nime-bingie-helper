# -*- coding: utf-8 -*-
"""
Tests for franchise.py — multi-season franchise building.

All AniList client calls are mocked. season_map module dicts are injected
directly (no disk or network I/O).
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch

import resources.lib.season_map as season_map
from resources.lib.franchise import (
    _start_sort_key,
    _aired,
    _cour_dict,
    _group,
    collect_tv_franchise,
    iter_cours,
    franchise_show_title,
    franchise_entry_for_season,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def _reset_season_map():
    season_map._BY_ANILIST = {}
    season_map._BY_MAL = {}
    season_map._TVDB_MEMBERS = {}
    season_map._LOADED = True  # prevent disk read


def _inject_season_map(compact):
    season_map._BY_ANILIST = compact.get("by_anilist", {})
    season_map._BY_MAL = compact.get("by_mal", {})
    season_map._TVDB_MEMBERS = compact.get("tvdb_members", {})
    season_map._LOADED = True


def _make_media(mal_id, anilist_id, status="FINISHED", episodes=12,
                year=2019, month=4, day=1):
    return {
        "idMal": mal_id,
        "id": anilist_id,
        "status": status,
        "episodes": episodes,
        "startDate": {"year": year, "month": month, "day": day},
        "format": "TV",
        "title": {
            "romaji": f"Series {anilist_id}",
            "english": f"Series EN {anilist_id}",
            "userPreferred": f"Series {anilist_id}",
        },
        "coverImage": {"extraLarge": "https://example.com/cover.jpg", "large": None},
        "bannerImage": "https://example.com/banner.jpg",
    }


# ---------------------------------------------------------------------------
# _start_sort_key
# ---------------------------------------------------------------------------
class TestStartSortKey:
    def test_full_date(self):
        media = {"startDate": {"year": 2021, "month": 10, "day": 5}, "idMal": 1}
        assert _start_sort_key(media) == (2021, 10, 5, 1)

    def test_missing_date_fields_default_to_zero(self):
        media = {"startDate": {}, "idMal": 999}
        assert _start_sort_key(media) == (0, 0, 0, 999)

    def test_none_start_date(self):
        media = {"startDate": None, "idMal": 42}
        key = _start_sort_key(media)
        assert key[0] == 0  # year default

    def test_sort_order(self):
        early = _make_media(1, 1, year=2019)
        late = _make_media(2, 2, year=2021)
        assert _start_sort_key(early) < _start_sort_key(late)


# ---------------------------------------------------------------------------
# _aired
# ---------------------------------------------------------------------------
class TestAired:
    def test_finished_is_aired(self):
        assert _aired({"status": "FINISHED"}) is True

    def test_releasing_is_aired(self):
        assert _aired({"status": "RELEASING"}) is True

    def test_hiatus_is_aired(self):
        assert _aired({"status": "HIATUS"}) is True

    def test_not_yet_released_not_aired(self):
        assert _aired({"status": "NOT_YET_RELEASED"}) is False

    def test_cancelled_not_aired(self):
        assert _aired({"status": "CANCELLED"}) is False

    def test_empty_status_treated_as_aired(self):
        # empty/missing status -> unknown -> treated as aired (not status or ...)
        assert _aired({"status": ""}) is True

    def test_no_status_key_treated_as_aired(self):
        assert _aired({}) is True


# ---------------------------------------------------------------------------
# _cour_dict
# ---------------------------------------------------------------------------
class TestCourDict:
    def test_basic_fields(self):
        media = _make_media(16498, 16498, year=2019)
        d = _cour_dict(media, season=1)
        assert d["mal_id"] == 16498
        assert d["anilist_id"] == 16498
        assert d["season"] == 1
        assert d["episodes"] == 12
        assert d["media"] is media

    def test_zero_episodes(self):
        media = _make_media(16498, 16498)
        media["episodes"] = None
        d = _cour_dict(media, season=1)
        assert d["episodes"] == 0

    def test_tmdb_fields(self):
        media = _make_media(16498, 16498)
        d = _cour_dict(media, season=1, tmdb_id=99, tmdb_season=2)
        assert d["tmdb_id"] == 99
        assert d["tmdb_season"] == 2


# ---------------------------------------------------------------------------
# _group
# ---------------------------------------------------------------------------
class TestGroup:
    def test_single_cour_single_season(self):
        media = _make_media(16498, 16498)
        cours = [_cour_dict(media, season=1)]
        groups = _group(cours)
        assert len(groups) == 1
        assert groups[0]["season"] == 1
        assert groups[0]["episodes"] == 12

    def test_two_cours_same_season_aggregated(self):
        m1 = _make_media(16498, 16498, episodes=13, year=2019)
        m2 = _make_media(20958, 20958, episodes=13, year=2019, month=7)
        cours = [_cour_dict(m1, season=2), _cour_dict(m2, season=2)]
        groups = _group(cours)
        assert len(groups) == 1
        assert groups[0]["episodes"] == 26
        assert len(groups[0]["cours"]) == 2

    def test_two_cours_different_seasons(self):
        m1 = _make_media(16498, 16498, year=2019)
        m2 = _make_media(20958, 20958, year=2021)
        cours = [_cour_dict(m1, season=1), _cour_dict(m2, season=2)]
        groups = _group(cours)
        assert len(groups) == 2
        assert groups[0]["season"] == 1
        assert groups[1]["season"] == 2

    def test_groups_ordered_by_season(self):
        m1 = _make_media(20958, 20958, year=2021)
        m2 = _make_media(16498, 16498, year=2019)
        # Deliberately insert season 2 before season 1.
        cours = [_cour_dict(m1, season=2), _cour_dict(m2, season=1)]
        groups = _group(cours)
        assert groups[0]["season"] == 1
        assert groups[1]["season"] == 2

    def test_representative_is_first_cour_by_start(self):
        m_early = _make_media(100, 100, year=2019, month=1)
        m_late = _make_media(101, 101, year=2019, month=7)
        cours = [_cour_dict(m_late, season=1), _cour_dict(m_early, season=1)]
        groups = _group(cours)
        assert groups[0]["mal_id"] == 100  # earliest cour is representative

    def test_tmdb_id_picked_from_cours(self):
        m1 = _make_media(16498, 16498)
        c1 = _cour_dict(m1, season=1, tmdb_id=12345, tmdb_season=1)
        groups = _group([c1])
        assert groups[0]["tmdb_id"] == 12345
        assert groups[0]["tmdb_season"] == 1


# ---------------------------------------------------------------------------
# iter_cours
# ---------------------------------------------------------------------------
class TestIterCours:
    def test_flat_list_across_groups(self):
        m1 = _make_media(16498, 16498, year=2019)
        m2 = _make_media(20958, 20958, year=2021)
        franchise = _group([_cour_dict(m1, season=1), _cour_dict(m2, season=2)])
        flat = iter_cours(franchise)
        assert len(flat) == 2
        assert flat[0]["mal_id"] == 16498
        assert flat[1]["mal_id"] == 20958

    def test_empty_franchise_returns_empty(self):
        assert iter_cours([]) == []


# ---------------------------------------------------------------------------
# franchise_show_title
# ---------------------------------------------------------------------------
class TestFranchiseShowTitle:
    def test_returns_first_resolved_title(self):
        m1 = _make_media(16498, 16498)
        franchise = _group([_cour_dict(m1, season=1)])
        title = franchise_show_title(franchise, lambda m: m.get("title", {}).get("english", "Unknown"))
        assert "EN" in title

    def test_empty_franchise_returns_empty(self):
        assert franchise_show_title([], lambda m: "X") == ""

    def test_skips_unknown_title(self):
        m1 = _make_media(16498, 16498)
        m2 = _make_media(20958, 20958)
        franchise = _group([_cour_dict(m1, season=1), _cour_dict(m2, season=2)])

        def title_fn(m):
            return "Unknown" if m.get("id") == 16498 else "Real Title"

        title = franchise_show_title(franchise, title_fn)
        assert title == "Real Title"


# ---------------------------------------------------------------------------
# franchise_entry_for_season
# ---------------------------------------------------------------------------
class TestFranchiseEntryForSeason:
    @pytest.fixture
    def franchise(self):
        m1 = _make_media(16498, 16498, year=2019)
        m2 = _make_media(20958, 20958, year=2021)
        return _group([_cour_dict(m1, season=1), _cour_dict(m2, season=2)])

    def test_returns_correct_group(self, franchise):
        entry = franchise_entry_for_season(franchise, 1)
        assert entry is not None
        assert entry["season"] == 1

    def test_returns_none_for_missing_season(self, franchise):
        assert franchise_entry_for_season(franchise, 99) is None

    def test_returns_none_for_zero(self, franchise):
        assert franchise_entry_for_season(franchise, 0) is None

    def test_returns_none_for_invalid(self, franchise):
        assert franchise_entry_for_season(franchise, "abc") is None

    def test_string_season_number_works(self, franchise):
        entry = franchise_entry_for_season(franchise, "2")
        assert entry is not None
        assert entry["season"] == 2


# ---------------------------------------------------------------------------
# collect_tv_franchise — integration with mocked client + season_map
# ---------------------------------------------------------------------------
class TestCollectTvFranchise:
    def setup_method(self):
        _reset_season_map()

    def test_returns_empty_when_no_mal_id(self):
        client = MagicMock()
        assert collect_tv_franchise(client, {}) == []
        assert collect_tv_franchise(client, None) == []

    def test_returns_empty_when_no_tvdb_mapping(self):
        _reset_season_map()  # empty maps -> lookup returns (None, None)
        client = MagicMock()
        client.get_franchise_cache.return_value = None
        media = _make_media(16498, 16498)
        result = collect_tv_franchise(client, media)
        assert result == []

    def test_returns_cached_franchise_without_api_call(self):
        client = MagicMock()
        cached = [{"season": 1, "mal_id": 16498, "media": {}, "episodes": 12, "cours": []}]
        client.get_franchise_cache.return_value = cached
        media = _make_media(16498, 16498)
        result = collect_tv_franchise(client, media)
        assert result is cached
        # get_media must NOT have been called
        client.get_media.assert_not_called()

    def test_two_season_franchise_built_from_map(self):
        """Full pipeline: season_map lookup -> fribb_cours -> _group -> result."""
        compact = load_fixture("franchise_map.json")
        _inject_season_map(compact)

        m1 = _make_media(16498, 16498, year=2019)
        m2 = _make_media(20958, 20958, year=2021)

        client = MagicMock()
        client.get_franchise_cache.return_value = None

        def fake_get_media(mal_id=None, anilist_id=None):
            if mal_id == 16498 or anilist_id == 16498:
                return m1
            if mal_id == 20958 or anilist_id == 20958:
                return m2
            return None

        client.get_media.side_effect = fake_get_media
        client.get_franchise_media.return_value = None

        media = _make_media(16498, 16498)
        result = collect_tv_franchise(client, media)

        assert len(result) == 2
        seasons = {g["season"] for g in result}
        assert seasons == {1, 2}
        assert result[0]["episodes"] == 12
        assert result[1]["episodes"] == 12

    def test_result_is_memoized_on_success(self):
        compact = load_fixture("franchise_map.json")
        _inject_season_map(compact)

        m1 = _make_media(16498, 16498)
        m2 = _make_media(20958, 20958, year=2021)

        client = MagicMock()
        client.get_franchise_cache.return_value = None

        def fake_get_media(mal_id=None, anilist_id=None):
            if mal_id in (16498,) or anilist_id in (16498,):
                return m1
            if mal_id in (20958,) or anilist_id in (20958,):
                return m2
            return None

        client.get_media.side_effect = fake_get_media
        client.get_franchise_media.return_value = None

        collect_tv_franchise(client, _make_media(16498, 16498))
        # set_franchise_cache must have been called at least once
        client.set_franchise_cache.assert_called()

    def test_not_yet_released_cour_excluded(self):
        compact = load_fixture("franchise_map.json")
        _inject_season_map(compact)

        m_finished = _make_media(16498, 16498, status="FINISHED")
        m_nyr = _make_media(20958, 20958, status="NOT_YET_RELEASED")

        client = MagicMock()
        client.get_franchise_cache.return_value = None

        def fake_get_media(mal_id=None, anilist_id=None):
            if mal_id == 16498 or anilist_id == 16498:
                return m_finished
            if mal_id == 20958 or anilist_id == 20958:
                return m_nyr
            return None

        client.get_media.side_effect = fake_get_media
        client.get_franchise_media.return_value = None

        result = collect_tv_franchise(client, _make_media(16498, 16498))
        # Only the FINISHED cour should appear
        assert len(result) == 1
        assert result[0]["mal_id"] == 16498
