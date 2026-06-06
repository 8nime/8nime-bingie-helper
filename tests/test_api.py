# -*- coding: utf-8 -*-
"""
Tests for api.py — AniListClient GraphQL query construction and response parsing.

No live network calls. requests.Session.post is monkey-patched per test to
return fixture JSON.
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def _mock_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    resp.headers = {}
    return resp


# We need to patch the cache so tests are hermetic (no disk I/O).
import resources.lib.api as api_module
from resources.lib.api import (
    AniListClient,
    _depth_ok,
    _capped_has_next,
    _clean_credits,
    ANIME_VIDEO_FORMATS,
    current_season_year,
    next_season_year,
    previous_season_year,
    media_type_from_tmdb,
)


# ---------------------------------------------------------------------------
# Pure helper functions (no network, no Kodi)
# ---------------------------------------------------------------------------
class TestDepthOk:
    def test_within_limit(self):
        assert _depth_ok(1, 50) is True
        assert _depth_ok(100, 50) is True  # 5000 exactly

    def test_exceeds_limit(self):
        assert _depth_ok(101, 50) is False
        assert _depth_ok(2, 2501) is False

    def test_invalid_values_treated_as_ok(self):
        assert _depth_ok(None, 50) is True
        assert _depth_ok("x", 50) is True


class TestCappedHasNext:
    def test_has_next_and_within_depth(self):
        assert _capped_has_next(1, 50, True) is True

    def test_has_next_but_next_page_exceeds_depth(self):
        # page=100, per_page=50 => next page (101*50=5050) > 5000
        assert _capped_has_next(100, 50, True) is False

    def test_no_api_next(self):
        assert _capped_has_next(1, 50, False) is False

    def test_false_api_next_at_safe_depth(self):
        assert _capped_has_next(1, 50, False) is False


class TestCleanCredits:
    def _node(self, status, fmt, id_=1):
        return {"status": status, "format": fmt, "id": id_}

    def test_filters_not_yet_released(self):
        nodes = [self._node("NOT_YET_RELEASED", "TV", 1)]
        assert _clean_credits(nodes) == []

    def test_filters_manga_format(self):
        nodes = [self._node("FINISHED", "MANGA", 1)]
        assert _clean_credits(nodes) == []

    def test_keeps_tv_format(self):
        nodes = [self._node("FINISHED", "TV", 1)]
        result = _clean_credits(nodes)
        assert len(result) == 1

    def test_keeps_movie_format(self):
        nodes = [self._node("FINISHED", "MOVIE", 2)]
        assert len(_clean_credits(nodes)) == 1

    def test_deduplicates_by_id(self):
        nodes = [
            self._node("FINISHED", "TV", 1),
            self._node("FINISHED", "OVA", 1),  # same id -> duplicate
        ]
        assert len(_clean_credits(nodes)) == 1

    def test_none_input_returns_empty(self):
        assert _clean_credits(None) == []

    def test_all_video_formats_kept(self):
        nodes = [self._node("FINISHED", fmt, i) for i, fmt in enumerate(ANIME_VIDEO_FORMATS)]
        assert len(_clean_credits(nodes)) == len(ANIME_VIDEO_FORMATS)


class TestSeasonYear:
    def test_current_season_returns_tuple(self):
        season, year = current_season_year()
        assert season in ("WINTER", "SPRING", "SUMMER", "FALL")
        assert year.isdigit()

    def test_next_season_differs_from_current(self):
        cur_s, _ = current_season_year()
        nxt_s, _ = next_season_year()
        assert cur_s != nxt_s

    def test_previous_season_differs_from_current(self):
        cur_s, _ = current_season_year()
        prev_s, _ = previous_season_year()
        assert cur_s != prev_s

    def test_season_cycle(self):
        order = ["WINTER", "SPRING", "SUMMER", "FALL"]
        cur_s, _ = current_season_year()
        nxt_s, _ = next_season_year()
        cur_idx = order.index(cur_s)
        nxt_idx = order.index(nxt_s)
        assert nxt_idx == (cur_idx + 1) % 4

    def test_previous_season_cycle(self):
        order = ["WINTER", "SPRING", "SUMMER", "FALL"]
        cur_s, _ = current_season_year()
        prev_s, _ = previous_season_year()
        cur_idx = order.index(cur_s)
        prev_idx = order.index(prev_s)
        assert prev_idx == (cur_idx - 1) % 4


class TestMediaTypeFromTmdb:
    def test_movie_type(self):
        media_type, formats = media_type_from_tmdb("movie")
        assert media_type == "ANIME"
        assert "MOVIE" in formats

    def test_tv_type(self):
        media_type, formats = media_type_from_tmdb("tv")
        assert media_type == "ANIME"
        assert "TV" in formats

    def test_unknown_type(self):
        media_type, formats = media_type_from_tmdb("unknown")
        assert media_type == "ANIME"
        assert formats is None


# ---------------------------------------------------------------------------
# AniListClient with mocked HTTP
# ---------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    """A client with cache disabled (in-memory cache is bypassed by mocking)."""
    with patch("resources.lib.api.get_api_cache") as mock_cache_fn, \
         patch("resources.lib.api.get_anilist_token", return_value=""), \
         patch("resources.lib.api.has_anilist_token", return_value=False):

        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_cache.get_stale.return_value = None
        mock_cache_fn.return_value = mock_cache

        # Reload the module-level ADDON / cache singletons don't matter;
        # we just need a fresh client instance.
        c = AniListClient.__new__(AniListClient)
        c._session = MagicMock()
        c._session.headers = {}
        return c


class TestAniListClientSearch:
    def test_search_returns_media_list(self, client):
        fixture = load_fixture("graphql_search_response.json")
        client._session.post.return_value = _mock_response(fixture)

        with patch.object(api_module._CACHE, "get", return_value=None), \
             patch.object(api_module._CACHE, "set"):
            # Patch the instance cache directly
            client_cache = MagicMock()
            client_cache.get.return_value = None
            client_cache.get_stale.return_value = None

            with patch("resources.lib.api._CACHE", client_cache):
                media, has_next = client.search("Demon Slayer", "ANIME")

        assert len(media) == 1
        assert media[0]["idMal"] == 40748
        assert has_next is False

    def test_search_sends_correct_variables(self, client):
        fixture = load_fixture("graphql_search_response.json")
        client._session.post.return_value = _mock_response(fixture)

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache):
            client.search("Demon Slayer", "ANIME", formats=["TV"], page=2, per_page=10)

        call_args = client._session.post.call_args
        payload = call_args[1]["json"]  # requests.post(..., json=payload)
        variables = payload["variables"]
        assert variables["search"] == "Demon Slayer"
        assert variables["type"] == "ANIME"
        assert variables["format"] == ["TV"]
        assert variables["page"] == 2
        assert variables["perpage"] == 10

    def test_search_returns_empty_on_api_error(self, client):
        client._session.post.return_value = _mock_response(
            {"errors": [{"message": "Not found"}]}, status_code=200
        )
        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache):
            media, has_next = client.search("nothing", "ANIME")

        assert media == []
        assert has_next is False

    def test_search_depth_guard_blocks_deep_pages(self, client):
        """page * per_page > 5000 must return ([], False) without any HTTP call."""
        # 101 * 50 = 5050 > 5000
        media, has_next = client.search("test", "ANIME", page=101, per_page=50)
        assert media == []
        assert has_next is False
        client._session.post.assert_not_called()


class TestAniListClientGetMedia:
    def test_get_media_by_mal_id(self, client):
        fixture = load_fixture("graphql_detail_response.json")
        client._session.post.return_value = _mock_response(fixture)

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache), \
             patch.dict("resources.lib.api._MEDIA_CACHE", {}):
            media = client.get_media(mal_id=40748)

        assert media is not None
        assert media["idMal"] == 40748
        assert media["id"] == 101922

    def test_get_media_sends_mal_id_variable(self, client):
        fixture = load_fixture("graphql_detail_response.json")
        client._session.post.return_value = _mock_response(fixture)

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache), \
             patch.dict("resources.lib.api._MEDIA_CACHE", {}):
            client.get_media(mal_id=40748)

        payload = client._session.post.call_args[1]["json"]
        assert payload["variables"]["idMal"] == 40748
        assert payload["variables"]["type"] == "ANIME"

    def test_get_media_returns_none_without_ids(self, client):
        result = client.get_media()
        assert result is None
        client._session.post.assert_not_called()

    def test_get_media_uses_in_process_cache(self, client):
        media_data = {"id": 101922, "idMal": 40748, "title": {"english": "DS"}}
        with patch.dict("resources.lib.api._MEDIA_CACHE", {40748: media_data}):
            result = client.get_media(mal_id=40748)
        assert result is media_data
        client._session.post.assert_not_called()


class TestAniListClientBrowse:
    def test_browse_returns_media_and_has_next(self, client):
        page_data = {
            "data": {
                "Page": {
                    "pageInfo": {"hasNextPage": True},
                    "media": [{"id": 1, "idMal": 1}],
                }
            }
        }
        client._session.post.return_value = _mock_response(page_data)

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache):
            media, has_next = client.browse({"type": "ANIME", "page": 1, "perpage": 50})

        assert len(media) == 1
        # page=1, per_page=50 => next page (2*50=100) is within 5000 => has_next=True
        assert has_next is True

    def test_browse_trending_uses_trending_query(self, client):
        page_data = {"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": []}}}
        client._session.post.return_value = _mock_response(page_data)

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache):
            client.browse({"type": "ANIME"}, trending=True)

        payload = client._session.post.call_args[1]["json"]
        assert "TRENDING_DESC" in payload["query"]

    def test_browse_non_trending_uses_base_query(self, client):
        page_data = {"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": []}}}
        client._session.post.return_value = _mock_response(page_data)

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache):
            client.browse({"type": "ANIME"}, trending=False)

        payload = client._session.post.call_args[1]["json"]
        assert "TRENDING_DESC" not in payload["query"]

    def test_browse_depth_guard(self, client):
        media, has_next = client.browse({"type": "ANIME", "page": 200, "perpage": 50})
        assert media == []
        assert has_next is False
        client._session.post.assert_not_called()


class TestAniListClientRecommendations:
    def test_returns_media_list(self, client):
        rec_data = {
            "data": {
                "Media": {
                    "recommendations": {
                        "pageInfo": {"hasNextPage": False},
                        "edges": [
                            {"node": {"mediaRecommendation": {"id": 999, "idMal": 999}}}
                        ],
                    }
                }
            }
        }
        client._session.post.return_value = _mock_response(rec_data)

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache):
            items, has_next = client.get_recommendations(40748)

        assert len(items) == 1
        assert items[0]["idMal"] == 999
        assert has_next is False

    def test_filters_null_recommendations(self, client):
        rec_data = {
            "data": {
                "Media": {
                    "recommendations": {
                        "pageInfo": {"hasNextPage": False},
                        "edges": [
                            {"node": {"mediaRecommendation": None}},
                            {"node": {"mediaRecommendation": {"id": 888, "idMal": 888}}},
                        ],
                    }
                }
            }
        }
        client._session.post.return_value = _mock_response(rec_data)

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache):
            items, _ = client.get_recommendations(40748)

        assert len(items) == 1


class TestAniListClientResolveMalId:
    def test_returns_mal_id_directly_from_params(self, client):
        result = client.resolve_mal_id({"mal_id": "40748"})
        assert result == 40748

    def test_returns_tmdb_id_as_mal_id(self, client):
        result = client.resolve_mal_id({"tmdb_id": "12345"})
        assert result == 12345

    def test_non_digit_ignored(self, client):
        fixture = load_fixture("graphql_search_response.json")
        client._session.post.return_value = _mock_response(fixture)

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None

        with patch("resources.lib.api._CACHE", cache):
            # mal_id is not a digit, anilist_id missing, so falls through to query search
            result = client.resolve_mal_id({"mal_id": "abc", "query": "Demon Slayer"})

        assert result == 40748

    def test_returns_none_for_empty_params(self, client):
        result = client.resolve_mal_id({})
        assert result is None
