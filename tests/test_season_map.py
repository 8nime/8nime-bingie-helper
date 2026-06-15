# -*- coding: utf-8 -*-
"""
Tests for season_map.py — Fribb compact-map build + lookup functions.

The offline lookup path (lookup / members / tmdb_lookup) uses module-level
in-process dicts that are populated either from disk or from _save(). We
manipulate those dicts directly in tests so no disk I/O is needed and there
are no network calls.
"""
import json
import os
import tempfile
import pytest

import resources.lib.season_map as season_map


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def _inject(by_anilist=None, by_mal=None, tvdb_members=None):
    """Directly inject data into the module-level in-process maps."""
    season_map._BY_ANILIST = by_anilist or {}
    season_map._BY_MAL = by_mal or {}
    season_map._TVDB_MEMBERS = tvdb_members or {}
    season_map._LOADED = True
    season_map._invalidate_reverse_indexes()


def _reset():
    season_map._BY_ANILIST = {}
    season_map._BY_MAL = {}
    season_map._TVDB_MEMBERS = {}
    season_map._LOADED = False
    season_map._invalidate_reverse_indexes()


def test_load_quarantines_corrupt_file(tmp_path, monkeypatch):
    # R3-5: a genuinely corrupt map is renamed to *.corrupt (recoverable + rebuilt next
    # refresh), not silently re-blanked every load with no trace.
    p = tmp_path / "season_map.json"
    p.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(season_map, "_cache_path", lambda: str(p))
    season_map._LOADED = False
    season_map._load()
    assert season_map._TVDB_MEMBERS == {}
    assert os.path.exists(str(p) + ".corrupt")
    assert not os.path.exists(str(p))


# ---------------------------------------------------------------------------
# build_compact — pure data, no Kodi deps
# ---------------------------------------------------------------------------
class TestBuildCompact:
    def test_basic_tv_entry(self):
        data = [
            {
                "tvdb_id": 76669,
                "anilist_id": 16498,
                "mal_id": 16498,
                "type": "TV",
                "season": {"tvdb": 1, "tmdb": 1},
                "themoviedb_id": {"tv": 12345},
            }
        ]
        result = season_map.build_compact(data)
        assert "16498" in result["by_anilist"]
        assert "16498" in result["by_mal"]
        assert "76669" in result["tvdb_members"]

    def test_record_format_anilist(self):
        data = [
            {
                "tvdb_id": 76669,
                "anilist_id": 16498,
                "mal_id": 16498,
                "type": "TV",
                "season": {"tvdb": 2, "tmdb": 2},
                "themoviedb_id": {"tv": 12345},
            }
        ]
        result = season_map.build_compact(data)
        rec = result["by_anilist"]["16498"]
        # [tvdb_id, tvdb_season, tmdb_id, tmdb_season]
        assert rec[0] == 76669
        assert rec[1] == 2
        assert rec[2] == 12345
        assert rec[3] == 2

    def test_entry_without_tvdb_id_skipped(self):
        data = [{"anilist_id": 999, "mal_id": 999, "type": "TV", "season": {"tvdb": 1}}]
        result = season_map.build_compact(data)
        assert "999" not in result["by_anilist"]

    def test_entry_without_season_recorded_for_id_lookup_only(self):
        # A no-season entry (1:1 with the whole TVDB series, e.g. One Piece) is now
        # recorded in by_anilist/by_mal so tmdb_lookup resolves its real TMDB id
        # (enabling the TMDB season-split), with the season axis defaulted to 1 --
        # but it is NOT added as a tvdb member (that would pollute a shared-tvdb
        # franchise).
        data = [
            {
                "tvdb_id": 12345,
                "anilist_id": 999,
                "mal_id": 999,
                "type": "TV",
                "season": {},
                "themoviedb_id": {"tv": 555},
            }
        ]
        result = season_map.build_compact(data)
        assert result["by_anilist"]["999"] == [12345, 1, 555, None, None]
        assert result["by_mal"]["999"] == [12345, 1, 555, None, None]
        assert "12345" not in result["tvdb_members"]

    def test_non_tv_type_marked_is_tv_false(self):
        data = [
            {
                "tvdb_id": 99999,
                "anilist_id": 55555,
                "mal_id": 55555,
                "type": "MANGA",
                "season": {"tvdb": 1},
                "themoviedb_id": None,
            }
        ]
        result = season_map.build_compact(data)
        members = result["tvdb_members"]["99999"]
        assert len(members) == 1
        # is_tv flag is index 3
        assert members[0][3] == 0  # not a TV type

    def test_tv_type_marked_is_tv_true(self):
        data = [
            {
                "tvdb_id": 76669,
                "anilist_id": 16498,
                "mal_id": 16498,
                "type": "TV",
                "season": {"tvdb": 1},
                "themoviedb_id": None,
            }
        ]
        result = season_map.build_compact(data)
        members = result["tvdb_members"]["76669"]
        assert members[0][3] == 1

    def test_tmdb_movie_id_not_carried(self):
        """Only TV themoviedb_id is stored; movie ids are dropped."""
        data = [
            {
                "tvdb_id": 88888,
                "anilist_id": 44444,
                "mal_id": 44444,
                "type": "TV",
                "season": {"tvdb": 1, "tmdb": 1},
                "themoviedb_id": {"movie": 777},
            }
        ]
        result = season_map.build_compact(data)
        rec = result["by_anilist"]["44444"]
        # tmdb_id should be None because the mapping is a movie id, not tv
        assert rec[2] is None

    def test_fribb_raw_fixture(self):
        raw = load_fixture("fribb_raw.json")
        result = season_map.build_compact(raw)
        # Two TV entries with tvdb_id=76669
        assert "76669" in result["tvdb_members"]
        assert len(result["tvdb_members"]["76669"]) == 2
        # One TV entry with tvdb_id=359556
        assert "359556" in result["tvdb_members"]

    def test_multiple_entries_same_tvdb_grouped(self):
        data = [
            {"tvdb_id": 76669, "anilist_id": 16498, "mal_id": 16498, "type": "TV",
             "season": {"tvdb": 1}, "themoviedb_id": None},
            {"tvdb_id": 76669, "anilist_id": 20958, "mal_id": 20958, "type": "TV",
             "season": {"tvdb": 2}, "themoviedb_id": None},
        ]
        result = season_map.build_compact(data)
        assert len(result["tvdb_members"]["76669"]) == 2


# ---------------------------------------------------------------------------
# lookup — anilist_id / mal_id -> (tvdb_id, tvdb_season)
# ---------------------------------------------------------------------------
class TestLookup:
    def setup_method(self):
        _reset()

    def test_lookup_by_anilist_id(self):
        _inject(by_anilist={"16498": [76669, 1, 12345, 1]})
        tvdb_id, season = season_map.lookup(anilist_id=16498)
        assert tvdb_id == 76669
        assert season == 1

    def test_lookup_by_mal_id(self):
        _inject(by_mal={"16498": [76669, 1, 12345, 1]})
        tvdb_id, season = season_map.lookup(mal_id=16498)
        assert tvdb_id == 76669
        assert season == 1

    def test_lookup_missing_returns_none_none(self):
        _inject()
        assert season_map.lookup(anilist_id=99999) == (None, None)

    def test_lookup_anilist_preferred_over_mal(self):
        _inject(
            by_anilist={"16498": [76669, 1, None, None]},
            by_mal={"16498": [99999, 3, None, None]},
        )
        tvdb_id, season = season_map.lookup(anilist_id=16498, mal_id=16498)
        assert tvdb_id == 76669

    def test_lookup_with_string_id(self):
        """Callers may pass string ids; _intable should accept them."""
        _inject(by_anilist={"16498": [76669, 1, None, None]})
        tvdb_id, _ = season_map.lookup(anilist_id="16498")
        assert tvdb_id == 76669

    def test_lookup_with_invalid_id_returns_none(self):
        _inject(by_anilist={"16498": [76669, 1, None, None]})
        assert season_map.lookup(anilist_id="not_a_number") == (None, None)


# ---------------------------------------------------------------------------
# tmdb_lookup
# ---------------------------------------------------------------------------
class TestTmdbLookup:
    def setup_method(self):
        _reset()

    def test_tmdb_lookup_returns_tmdb_id_and_season(self):
        _inject(by_anilist={"16498": [76669, 1, 12345, 1]})
        tmdb_id, tmdb_season = season_map.tmdb_lookup(anilist_id=16498)
        assert tmdb_id == 12345
        assert tmdb_season == 1

    def test_tmdb_lookup_null_when_no_tmdb_mapping(self):
        _inject(by_anilist={"101922": [359556, 1, None, None]})
        tmdb_id, tmdb_season = season_map.tmdb_lookup(anilist_id=101922)
        assert tmdb_id is None
        assert tmdb_season is None

    def test_tmdb_lookup_missing_id(self):
        _inject()
        assert season_map.tmdb_lookup(anilist_id=999) == (None, None)


# ---------------------------------------------------------------------------
# members — tvdb_id -> list of member dicts
# ---------------------------------------------------------------------------
class TestMembers:
    def setup_method(self):
        _reset()

    def test_members_for_known_tvdb(self):
        _inject(tvdb_members={
            "76669": [
                [16498, 16498, 1, 1, 12345, 1],
                [20958, 20958, 2, 1, 12345, 2],
            ]
        })
        ms = season_map.members(76669)
        assert len(ms) == 2
        assert ms[0]["anilist"] == 16498
        assert ms[0]["mal"] == 16498
        assert ms[0]["season"] == 1
        assert ms[0]["is_tv"] is True
        assert ms[0]["tmdb_id"] == 12345
        assert ms[0]["tmdb_season"] == 1

    def test_members_unknown_tvdb_returns_empty(self):
        _inject()
        assert season_map.members(99999) == []

    def test_members_none_tvdb_returns_empty(self):
        _inject()
        assert season_map.members(None) == []

    def test_members_is_tv_false_for_non_tv(self):
        _inject(tvdb_members={"99999": [[55555, 55555, 1, 0, None, None]]})
        ms = season_map.members(99999)
        assert ms[0]["is_tv"] is False

    def test_members_tmdb_none_when_short_record(self):
        """Records from pre-FORMAT2 cache omit tmdb fields; must default to None."""
        _inject(tvdb_members={"76669": [[16498, 16498, 1, 1]]})
        ms = season_map.members(76669)
        assert ms[0]["tmdb_id"] is None
        assert ms[0]["tmdb_season"] is None

    def test_members_from_franchise_fixture(self):
        compact = load_fixture("franchise_map.json")
        _inject(
            by_anilist=compact["by_anilist"],
            by_mal=compact["by_mal"],
            tvdb_members=compact["tvdb_members"],
        )
        ms = season_map.members(76669)
        assert len(ms) == 2
        seasons = {m["season"] for m in ms}
        assert seasons == {1, 2}


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------
class TestAvailable:
    def setup_method(self):
        _reset()

    def test_available_false_when_empty(self):
        _inject()
        assert season_map.available() is False

    def test_available_true_when_data_present(self):
        _inject(tvdb_members={"76669": [[16498, 16498, 1, 1, None, None]]})
        assert season_map.available() is True


# ---------------------------------------------------------------------------
# members_for_tmdb — reverse index tmdb_id -> [member dicts]
# ---------------------------------------------------------------------------
class TestMembersForTmdb:
    def setup_method(self):
        _reset()

    def test_reverse_lookup_single(self):
        _inject(tvdb_members={"76669": [[16498, 16498, 1, 1, 12345, 1]]})
        ms = season_map.members_for_tmdb(12345)
        assert len(ms) == 1
        assert ms[0]["anilist"] == 16498
        assert ms[0]["tmdb_season"] == 1

    def test_reverse_lookup_groups_all_cours(self):
        _inject(tvdb_members={"76669": [
            [16498, 16498, 1, 1, 12345, 1],
            [20958, 20958, 2, 1, 12345, 2],
        ]})
        ms = season_map.members_for_tmdb(12345)
        assert {m["season"] for m in ms} == {1, 2}

    def test_reverse_lookup_spans_multiple_tvdb_series(self):
        # Same tmdb id can appear under different tvdb series records.
        _inject(tvdb_members={
            "76669": [[16498, 16498, 1, 1, 12345, 1]],
            "88888": [[20958, 20958, 1, 1, 12345, 2]],
        })
        ms = season_map.members_for_tmdb(12345)
        assert len(ms) == 2

    def test_reverse_lookup_ignores_unmapped(self):
        _inject(tvdb_members={"76669": [[16498, 16498, 1, 1, None, None]]})
        assert season_map.members_for_tmdb(12345) == []

    def test_reverse_lookup_unknown_returns_empty(self):
        _inject(tvdb_members={})
        assert season_map.members_for_tmdb(99999) == []

    def test_reverse_index_rebuilds_after_reinject(self):
        _inject(tvdb_members={"76669": [[16498, 16498, 1, 1, 12345, 1]]})
        assert len(season_map.members_for_tmdb(12345)) == 1
        _inject(tvdb_members={"76669": [[1, 1, 1, 1, 999, 1], [2, 2, 2, 1, 999, 2]]})
        assert season_map.members_for_tmdb(12345) == []
        assert len(season_map.members_for_tmdb(999)) == 2
