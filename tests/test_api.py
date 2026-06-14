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

    def test_browse_season_includes_not_yet_released(self, client):
        # Seasonal rows (this/next season) must NOT exclude NOT_YET_RELEASED, else
        # early-season + upcoming lineups come back empty (the live-test bug).
        page_data = {"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": []}}}
        client._session.post.return_value = _mock_response(page_data)
        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None
        with patch("resources.lib.api._CACHE", cache):
            client.browse({"type": "ANIME", "season": "SUMMER", "year": "2026%", "page": 1, "perpage": 50})
        variables = client._session.post.call_args[1]["json"]["variables"]
        # [] (not None) -- AniList 500s on status_not_in: null but accepts [].
        assert variables["statusNotIn"] == []

    def test_browse_global_excludes_not_yet_released(self, client):
        # Season-less (global popular/discover) browses keep excluding unreleased.
        page_data = {"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": []}}}
        client._session.post.return_value = _mock_response(page_data)
        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None
        with patch("resources.lib.api._CACHE", cache):
            client.browse({"type": "ANIME", "page": 1, "perpage": 50})
        variables = client._session.post.call_args[1]["json"]["variables"]
        assert variables["statusNotIn"] == ["NOT_YET_RELEASED"]

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

    def test_tmdb_id_is_not_cast_to_mal_id(self, client):
        # tmdb_id and mal_id are disjoint id spaces. A bare tmdb_id must NOT be
        # returned as a MAL id (that scored the wrong title); tmdb_id is resolved
        # only via the Fribb reverse map in identity.resolve_mal_id, never here.
        result = client.resolve_mal_id({"tmdb_id": "12345"})
        assert result is None

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


class TestAniListClientPost404:
    """AniList answers a not-found MediaList with HTTP 404 + a valid GraphQL body."""

    def test_404_with_data_returns_data_not_raise(self, client):
        # {"errors":[...], "data":{"MediaList": null}} at HTTP 404 is AniList's
        # "no entry" answer -- _post must return the data payload, never raise.
        resp = _mock_response(
            {"errors": [{"message": "Not Found.", "status": 404}],
             "data": {"MediaList": None}},
            status_code=404,
        )
        client._session.post.return_value = resp

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None
        with patch("resources.lib.api._CACHE", cache):
            result = client._post("query { MediaList { progress } }", {"mediaId": 1})

        assert result == {"MediaList": None}
        resp.raise_for_status.assert_not_called()

    def test_404_without_data_still_raises(self, client):
        # A 404 with no usable GraphQL body is a real transport error.
        resp = _mock_response({"message": "gateway"}, status_code=404)
        resp.json.return_value = {"message": "gateway"}
        from requests.exceptions import HTTPError
        resp.raise_for_status.side_effect = HTTPError("404")
        client._session.post.return_value = resp

        cache = MagicMock()
        cache.get.return_value = None
        cache.get_stale.return_value = None
        with patch("resources.lib.api._CACHE", cache):
            result = client._post("query { Page { media { id } } }", {"page": 1})

        # _post swallows the raised HTTPError and returns None (stale cache empty).
        assert result is None


class TestPlanningEntryId:
    def test_returns_entry_id_when_in_planning(self, client):
        client.has_token = MagicMock(return_value=True)
        client._list_entries = MagicMock(
            return_value=[{"id": 5, "media": {"id": 99}}, {"id": 6, "media": {"id": 7}}]
        )
        assert client._planning_entry_id(99) == 5

    def test_none_when_media_absent(self, client):
        client.has_token = MagicMock(return_value=True)
        client._list_entries = MagicMock(return_value=[{"id": 6, "media": {"id": 7}}])
        assert client._planning_entry_id(99) is None

    def test_none_without_token(self, client):
        client.has_token = MagicMock(return_value=False)
        client._list_entries = MagicMock()
        assert client._planning_entry_id(99) is None
        client._list_entries.assert_not_called()


class TestWatchlistLive:
    def test_watchlist_fetches_planning_live(self, client):
        # My List must be live: the PLANNING fetch bypasses the API cache so a
        # just-added favourite shows on navigation.
        client._list_entries = MagicMock(return_value=[])
        client.watchlist()
        assert client._list_entries.call_args.kwargs.get("use_cache") is False


class TestListState:
    def test_planning_and_no_rating(self, client):
        client._entry = MagicMock(return_value={"id": 1, "status": "PLANNING", "score": 0})
        assert client.list_state(99) == {"planning": True, "rating": ""}

    def test_like_from_high_score(self, client):
        client._entry = MagicMock(return_value={"id": 1, "status": "CURRENT", "score": 85})
        assert client.list_state(99) == {"planning": False, "rating": "like"}

    def test_dislike_from_low_score(self, client):
        client._entry = MagicMock(return_value={"id": 1, "status": "CURRENT", "score": 25})
        assert client.list_state(99) == {"planning": False, "rating": "dislike"}

    def test_no_entry(self, client):
        client._entry = MagicMock(return_value=None)
        assert client.list_state(99) == {"planning": False, "rating": ""}


class TestSaveMediaScoreFavorites:
    """favorites/watchlist sync toggles AniList PLANNING membership (My List)."""

    def _client(self, client, on_list, post_result):
        client.has_token = MagicMock(return_value=True)
        client.get_media = MagicMock(return_value={"id": 99, "format": "TV"})
        # PLANNING entries carry their own list-entry id (555 here), which the
        # delete path must key off -- not the media id.
        entries = [{"id": 555, "media": {"id": 99}}] if on_list else [{"id": 7, "media": {"id": 7}}]
        client._list_entries = MagicMock(return_value=entries)
        client._post = MagicMock(return_value=post_result)
        return client

    def test_favorites_adds_when_absent(self, client):
        c = self._client(client, on_list=False, post_result={"SaveMediaListEntry": {"id": 1, "status": "PLANNING"}})
        ok, action = c.save_media_score(40748, "favorites")
        assert ok is True
        assert action == "added"
        # PLANNING save mutation issued with the resolved media id
        variables = c._post.call_args[0][1]
        assert variables == {"mediaId": 99, "status": "PLANNING"}

    def test_favorites_removes_when_present(self, client):
        c = self._client(client, on_list=True, post_result={"DeleteMediaListEntry": {"deleted": True}})
        ok, action = c.save_media_score(40748, "favorites")
        assert ok is True
        assert action == "removed"
        # DeleteMediaListEntry must be keyed by the list-entry id (555), not mediaId.
        assert "DeleteMediaListEntry(id:" in c._post.call_args[0][0]
        assert c._post.call_args[0][1] == {"id": 555}

    def test_watchlist_alias_behaves_like_favorites(self, client):
        c = self._client(client, on_list=False, post_result={"SaveMediaListEntry": {"id": 2}})
        ok, action = c.save_media_score(40748, "watchlist")
        assert (ok, action) == (True, "added")

    def test_favorites_without_token_is_noop(self, client):
        client.has_token = MagicMock(return_value=False)
        ok, reason = client.save_media_score(40748, "favorites")
        assert ok is False
        assert reason == "not_logged_in"

    def test_reset_deletes_by_entry_id(self, client):
        client.has_token = MagicMock(return_value=True)
        client.get_media = MagicMock(return_value={"id": 99, "format": "TV"})
        client._entry_id = MagicMock(return_value=777)
        client._post = MagicMock(return_value={"DeleteMediaListEntry": {"deleted": True}})
        ok, action = client.save_media_score(40748, "reset")
        assert (ok, action) == (True, "reset")
        assert "DeleteMediaListEntry(id:" in client._post.call_args[0][0]
        assert client._post.call_args[0][1] == {"id": 777}

    def test_reset_is_idempotent_when_no_entry(self, client):
        client.has_token = MagicMock(return_value=True)
        client.get_media = MagicMock(return_value={"id": 99, "format": "TV"})
        client._entry_id = MagicMock(return_value=None)
        client._post = MagicMock()
        ok, action = client.save_media_score(40748, "reset")
        assert (ok, action) == (True, "reset")
        client._post.assert_not_called()


class TestSaveMediaScoreRating:
    """like/dislike set the score but must NOT move the title off My List."""

    def _client(self, client, existing_status):
        client.has_token = MagicMock(return_value=True)
        client.get_media = MagicMock(return_value={"id": 99, "format": "TV"})
        entry = {"id": 5, "status": existing_status, "score": 0} if existing_status else None
        client._entry = MagicMock(return_value=entry)
        client._post = MagicMock(return_value={"SaveMediaListEntry": {"id": 5, "score": 85}})
        return client

    def test_like_preserves_existing_planning_status(self, client):
        # Liking a favourited (PLANNING) title keeps it PLANNING -> stays on My List.
        c = self._client(client, "PLANNING")
        ok, action = c.save_media_score(40748, "like")
        assert (ok, action) == (True, "like")
        assert c._post.call_args[0][1] == {"mediaId": 99, "score": 85.0, "status": "PLANNING"}

    def test_like_new_entry_defaults_current(self, client):
        # No existing entry -> a TV title defaults to CURRENT.
        c = self._client(client, None)
        ok, action = c.save_media_score(40748, "like")
        assert (ok, action) == (True, "like")
        assert c._post.call_args[0][1]["status"] == "CURRENT"
        assert c._post.call_args[0][1]["score"] == 85.0

    def test_dislike_preserves_existing_current_status(self, client):
        c = self._client(client, "CURRENT")
        ok, action = c.save_media_score(40748, "dislike")
        assert (ok, action) == (True, "dislike")
        assert c._post.call_args[0][1] == {"mediaId": 99, "score": 25.0, "status": "CURRENT"}


class TestSyncProgress:
    """Boot/login sync: one lean MediaListCollection pull -> the local progress store."""

    def test_populates_store_from_collection(self, client, monkeypatch):
        from resources.lib import progress
        monkeypatch.setattr(api_module, "has_anilist_token", lambda: True)

        def fake_post(query, variables=None, use_cache=True):
            if "Viewer" in query:
                return {"Viewer": {"id": 7}}
            return {"MediaListCollection": {"lists": [
                {"entries": [
                    {"progress": 12, "updatedAt": 100,
                     "media": {"id": 21, "idMal": 21, "episodes": 1000}},
                    {"progress": 3, "updatedAt": 200,
                     "media": {"id": 5, "idMal": 40748, "episodes": 26}},
                ]},
            ]}}

        monkeypatch.setattr(client, "_post", fake_post)
        n = client.sync_progress()
        assert n == 2
        assert progress.progress_of(21) == 12
        assert progress.total_of(21) == 1000
        assert progress.get(5)["mal_id"] == 40748

    def test_no_token_is_noop(self, client, monkeypatch):
        from resources.lib import progress
        monkeypatch.setattr(api_module, "has_anilist_token", lambda: False)
        assert client.sync_progress() == 0
        assert progress.get(21) is None

    def test_sync_clears_resume_finished_elsewhere(self, client, monkeypatch):
        # Synced progress now covers the resumed episode AND is newer than the local
        # resume point -> finished on another device -> drop the stale point.
        from resources.lib import resume
        monkeypatch.setattr(api_module, "has_anilist_token", lambda: True)
        resume.set_point(21, 5, 600.0, 1400.0)

        def fake_post(query, variables=None, use_cache=True):
            if "Viewer" in query:
                return {"Viewer": {"id": 7}}
            return {"MediaListCollection": {"lists": [{"entries": [
                {"progress": 8, "updatedAt": 9999999999,  # past ep5, newer than the point
                 "media": {"id": 21, "idMal": 21, "episodes": 26}},
            ]}]}}

        monkeypatch.setattr(client, "_post", fake_post)
        client.sync_progress()
        assert resume.get(21) is None

    def test_sync_keeps_fresh_rewatch_resume(self, client, monkeypatch):
        # The local resume point is NEWER than the synced completion (an active re-watch)
        # -> it must survive the sync so the episode still resumes.
        from resources.lib import resume
        monkeypatch.setattr(api_module, "has_anilist_token", lambda: True)
        resume.set_point(21, 5, 600.0, 1400.0)

        def fake_post(query, variables=None, use_cache=True):
            if "Viewer" in query:
                return {"Viewer": {"id": 7}}
            return {"MediaListCollection": {"lists": [{"entries": [
                {"progress": 8, "updatedAt": 100,  # old completion, older than the point
                 "media": {"id": 21, "idMal": 21, "episodes": 26}},
            ]}]}}

        monkeypatch.setattr(client, "_post", fake_post)
        client.sync_progress()
        assert resume.get(21) is not None


class TestNextUp:
    """Continue Watching: in-progress entries from the progress store + mid-episode
    resume points, deduped by mal_id, caught-up shows dropped."""

    def _media(self, mal, eps):
        return {"id": mal * 10, "idMal": mal, "episodes": eps, "title": {"english": "T%d" % mal}}

    def test_lists_in_progress_drops_caught_up(self, client, monkeypatch):
        from resources.lib import progress
        progress.apply_anilist(70, 7, 4, total=26, updated_at=200)   # in progress
        progress.apply_anilist(90, 9, 12, total=12, updated_at=300)  # caught up -> dropped
        media = {7: self._media(7, 26), 9: self._media(9, 12)}
        monkeypatch.setattr(client, "get_media",
                            lambda mal_id=None, anilist_id=None: media.get(mal_id))
        items = client.next_up()
        mals = [m["idMal"] for m in items]
        assert 7 in mals and 9 not in mals
        assert next(m for m in items if m["idMal"] == 7)["_progress"] == 4

    def test_resume_point_only_show_appears(self, client, monkeypatch):
        from resources.lib import resume
        resume.set_point(303, 5, 600.0, 1400.0)  # started ep5, nothing finished
        media = {303: {"id": 303, "idMal": 33, "episodes": 24, "title": {}}}
        monkeypatch.setattr(client, "get_media",
                            lambda mal_id=None, anilist_id=None: media.get(anilist_id))
        items = client.next_up()
        assert [m["idMal"] for m in items] == [33]
        assert items[0]["_progress"] == 4  # mid ep5 -> completed up to 4

    def test_dedup_progress_wins_over_resume(self, client, monkeypatch):
        from resources.lib import progress, resume
        progress.apply_anilist(50, 5, 3, total=26, updated_at=100)
        resume.set_point(50, 8, 100.0, 1400.0)  # same AniList id also has a resume point
        media = {5: self._media(5, 26), 50: self._media(5, 26)}
        monkeypatch.setattr(client, "get_media",
                            lambda mal_id=None, anilist_id=None: media.get(mal_id) or media.get(anilist_id))
        items = client.next_up()
        assert [m["idMal"] for m in items].count(5) == 1  # deduped by mal_id
        assert items[0]["_progress"] == 3  # progress tier wins
