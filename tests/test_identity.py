# -*- coding: utf-8 -*-
"""Tests for identity.py — surrogate ids + forward/reverse tmdb_id mapping.

Like test_season_map, these inject directly into season_map's in-process dicts;
no disk I/O, no network. Records use the FORMAT-3 layout:
  by_anilist/by_mal[id] = [tvdb_id, tvdb_season, tmdb_id, tmdb_season, ap_slug]
  tvdb_members[tvdb][i] = [anilist, mal, tvdb_season, is_tv, tmdb_id, tmdb_season]
"""
import pytest

import resources.lib.identity as identity
import resources.lib.season_map as season_map


def _reset_map(by_anilist=None, by_mal=None, tvdb_members=None):
    season_map._BY_ANILIST = by_anilist or {}
    season_map._BY_MAL = by_mal or {}
    season_map._TVDB_MEMBERS = tvdb_members or {}
    season_map._LOADED = True
    season_map._invalidate_reverse_indexes()


class TestSurrogate:
    def test_anilist_round_trip(self):
        s = identity.encode_surrogate("anilist", 16498)
        assert identity.is_surrogate(s)
        assert identity.decode_surrogate(s) == ("anilist", 16498)

    def test_mal_round_trip(self):
        s = identity.encode_surrogate("mal", 12345)
        assert identity.is_surrogate(s)
        assert identity.decode_surrogate(s) == ("mal", 12345)

    def test_anilist_and_mal_ranges_disjoint(self):
        a = identity.encode_surrogate("anilist", identity.MAL_TAG - 1)  # max anilist
        m = identity.encode_surrogate("mal", 0)
        assert a < m  # whole anilist range sits below the mal range
        assert identity.decode_surrogate(a) == ("anilist", identity.MAL_TAG - 1)
        assert identity.decode_surrogate(m) == ("mal", 0)

    def test_real_tmdb_id_not_surrogate(self):
        assert not identity.is_surrogate(12345)
        assert not identity.is_surrogate(identity.SURROGATE_BASE - 1)
        assert identity.is_surrogate(identity.SURROGATE_BASE)

    def test_encode_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            identity.encode_surrogate("anilist", identity.MAL_TAG)

    def test_is_surrogate_handles_garbage(self):
        assert identity.is_surrogate("nope") is False
        assert identity.is_surrogate(None) is False


class TestForward:
    def test_real_tmdb_when_mapped(self):
        _reset_map(by_anilist={"16498": [76669, 1, 12345, 1, None]})
        assert identity.to_tmdb_id(anilist_id=16498) == 12345

    def test_surrogate_when_unmapped(self):
        _reset_map(by_anilist={"101922": [359556, 1, None, None, None]})
        out = identity.to_tmdb_id(anilist_id=101922)
        assert identity.is_surrogate(out)
        assert identity.decode_surrogate(out) == ("anilist", 101922)

    def test_surrogate_prefers_anilist(self):
        _reset_map()
        out = identity.to_tmdb_id(anilist_id=111, mal_id=222)
        assert identity.decode_surrogate(out) == ("anilist", 111)

    def test_surrogate_mal_fallback(self):
        _reset_map()
        out = identity.to_tmdb_id(mal_id=222)
        assert identity.decode_surrogate(out) == ("mal", 222)

    def test_none_when_no_ids(self):
        _reset_map()
        assert identity.to_tmdb_id() is None

    def test_deterministic(self):
        _reset_map()
        assert identity.to_tmdb_id(anilist_id=111) == identity.to_tmdb_id(anilist_id=111)


class TestReverse:
    def test_surrogate_decodes_offline(self):
        _reset_map()  # no Fribb data needed for surrogate decode
        s = identity.encode_surrogate("anilist", 16498)
        assert identity.reverse_ids(s) == {"anilist": 16498, "mal": None}

    def test_mal_surrogate_decodes(self):
        _reset_map()
        s = identity.encode_surrogate("mal", 555)
        assert identity.reverse_ids(s) == {"anilist": None, "mal": 555}

    def test_real_tmdb_single_cour(self):
        _reset_map(tvdb_members={"76669": [[16498, 16498, 1, 1, 12345, 1]]})
        assert identity.reverse_ids(12345) == {"anilist": 16498, "mal": 16498}

    def test_real_tmdb_season_disambiguation(self):
        _reset_map(tvdb_members={"76669": [
            [16498, 16498, 1, 1, 12345, 1],
            [20958, 20958, 2, 1, 12345, 2],
        ]})
        assert identity.reverse_ids(12345, season=2) == {"anilist": 20958, "mal": 20958}

    def test_real_tmdb_no_season_picks_base(self):
        _reset_map(tvdb_members={"76669": [
            [20958, 20958, 2, 1, 12345, 2],
            [16498, 16498, 1, 1, 12345, 1],
        ]})
        assert identity.reverse_ids(12345) == {"anilist": 16498, "mal": 16498}

    def test_unknown_tmdb_returns_none(self):
        _reset_map(tvdb_members={})
        assert identity.reverse_ids(99999) is None

    def test_monolith_reverse_from_by_mal_fallback(self):
        # One Piece: recorded in by_mal with tmdb 37854 but NOT in tvdb_members, so
        # members_for_tmdb misses -> the forward-index fallback must recover mal 21.
        _reset_map(by_mal={"21": [81797, 1, 37854, 1, "one-piece"]}, tvdb_members={})
        assert season_map.members_for_tmdb(37854) == []  # tvdb-members reverse misses
        assert identity.reverse_ids(37854) == {"anilist": None, "mal": 21}

    def test_monolith_resolve_mal_id_from_tmdb_param(self):
        # The skin's One Piece Play sends tmdb_id (no mal_id) -> must resolve to 21.
        _reset_map(by_mal={"21": [81797, 1, 37854, 1, "one-piece"]}, tvdb_members={})
        params = {"info": "trakt_upnext", "tmdb_id": "37854", "tmdb_type": "tv"}
        assert identity.resolve_mal_id(params, client=None) == 21

    def test_garbage_returns_none(self):
        assert identity.reverse_ids(None) is None
        assert identity.reverse_ids("x") is None


class _FakeClient:
    def __init__(self, media_by_anilist=None, resolve_result=None):
        self._media_by_anilist = media_by_anilist or {}
        self._resolve_result = resolve_result
        self.resolve_calls = []

    def get_media(self, mal_id=None, anilist_id=None):
        if anilist_id is not None:
            return self._media_by_anilist.get(int(anilist_id))
        return None

    def resolve_mal_id(self, params):
        self.resolve_calls.append(params)
        return self._resolve_result


class TestResolveMalId:
    def test_explicit_mal_id_wins(self):
        c = _FakeClient()
        assert identity.resolve_mal_id({"mal_id": "40748", "tmdb_id": "999"}, c) == 40748

    def test_surrogate_mal(self):
        c = _FakeClient()
        s = identity.encode_surrogate("mal", 40748)
        assert identity.resolve_mal_id({"tmdb_id": str(s)}, c) == 40748

    def test_surrogate_anilist_fetches_media(self):
        c = _FakeClient(media_by_anilist={101922: {"idMal": 40748}})
        s = identity.encode_surrogate("anilist", 101922)
        assert identity.resolve_mal_id({"tmdb_id": str(s)}, c) == 40748

    def test_real_tmdb_reverse_with_season(self):
        _reset_map(tvdb_members={"76669": [
            [16498, 16498, 1, 1, 12345, 1],
            [20958, 20958, 2, 1, 12345, 2],
        ]})
        c = _FakeClient()
        assert identity.resolve_mal_id({"tmdb_id": "12345", "season": "2"}, c) == 20958

    def test_falls_back_to_client_resolve(self):
        _reset_map(tvdb_members={})
        c = _FakeClient(resolve_result=555)
        out = identity.resolve_mal_id({"query": "naruto"}, c)
        assert out == 555
        assert c.resolve_calls  # delegated to the client resolver
