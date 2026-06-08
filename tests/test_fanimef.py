# -*- coding: utf-8 -*-
"""FANime F resolver tests. No live network — the session and module functions
are mocked; regex/JSON parsing runs on fixture strings."""
import json
from unittest.mock import MagicMock, patch

from resources.lib import fanimef


class TestSearchSeriesParse:
    HTML = (
        '<li><a href="/v1/show" title="Show"><img></a>'
        '<a href="/v1/show" title="Show">Show</a></li>'
        '<li><a href="/v1/show-dub" title="Show"><img></a></li>'
    )

    def _session(self):
        sess = MagicMock()
        resp = MagicMock()
        resp.json.return_value = {"result": self.HTML}
        sess.post.return_value = resp
        return sess

    def test_sub_dedups_and_excludes_dub(self):
        assert fanimef.search_series("show", self._session(), dub=False) == [("/v1/show", "Show")]

    def test_dub_selects_dub_slug(self):
        assert fanimef.search_series("show", self._session(), dub=True) == [("/v1/show-dub", "Show")]


class TestEpisodeListParse:
    def test_zero_indexed_to_one_based(self):
        content = {"eptotal": 2, "0": "https://s/embed-3/K1", "1": "https://s/embed-3/K2"}
        html = 'foo<div id="epslistplace">%s</div>bar' % json.dumps(content)
        sess = MagicMock()
        resp = MagicMock()
        resp.text = html
        sess.get.return_value = resp
        assert fanimef.episode_list("/v1/show", sess) == {
            1: "https://s/embed-3/K1",
            2: "https://s/embed-3/K2",
        }

    def test_missing_block_returns_empty(self):
        sess = MagicMock()
        resp = MagicMock()
        resp.text = "no list here"
        sess.get.return_value = resp
        assert fanimef.episode_list("/v1/show", sess) == {}


class TestResolveStream:
    def test_extracts_key_and_m3u8(self):
        sess = MagicMock()
        resp = MagicMock()
        resp.json.return_value = {"sources": "https://cdn/x.m3u8", "tracks": None}
        sess.get.return_value = resp
        src, tracks = fanimef.resolve_stream("https://s/embed-3/ABC123", sess)
        assert src == "https://cdn/x.m3u8"
        assert "getSources?id=ABC123" in sess.get.call_args[0][0]

    def test_sources_list_takes_file(self):
        sess = MagicMock()
        resp = MagicMock()
        resp.json.return_value = {"sources": [{"file": "https://cdn/y.m3u8"}]}
        sess.get.return_value = resp
        src, _ = fanimef.resolve_stream("https://s/embed-3/K", sess)
        assert src == "https://cdn/y.m3u8"


class TestResolveEpisode:
    def test_resolves_episode(self):
        with patch.object(fanimef, "search_series", return_value=[("/v1/show", "Show Name")]), \
             patch.object(fanimef, "episode_list", return_value={1: "https://s/embed-3/K"}), \
             patch.object(fanimef, "resolve_stream", return_value=("https://cdn/x.m3u8", None)):
            res, dbg = fanimef.resolve_episode(["show name"], 1)
        assert res["stream"] == "https://cdn/x.m3u8"
        assert res["referer"] == fanimef.MEDIA_REFERER

    def test_movie_resolves_as_episode_one(self):
        with patch.object(fanimef, "search_series", return_value=[("/v1/m", "Movie")]), \
             patch.object(fanimef, "episode_list", return_value={1: "https://s/embed-3/K"}) as ep, \
             patch.object(fanimef, "resolve_stream", return_value=("https://cdn/m.m3u8", None)):
            res, dbg = fanimef.resolve_movie(["movie"])
        assert res["stream"] == "https://cdn/m.m3u8"

    def test_no_episode_match_returns_none(self):
        with patch.object(fanimef, "search_series", return_value=[("/v1/show", "Show")]), \
             patch.object(fanimef, "episode_list", return_value={1: "https://s/embed-3/K"}):
            res, dbg = fanimef.resolve_episode(["show"], 99)
        assert res is None
