# -*- coding: utf-8 -*-
"""Tests for parser.py — URL param parsing."""
import pytest
from resources.lib.parser import parse_params


class TestParseParams:
    def test_empty_string_returns_empty_dict(self):
        assert parse_params("") == {}

    def test_none_returns_empty_dict(self):
        assert parse_params(None) == {}

    def test_single_param(self):
        result = parse_params("info=details")
        assert result == {"info": "details"}

    def test_multiple_params(self):
        result = parse_params("info=episodes&mal_id=40748&season=1")
        assert result["info"] == "episodes"
        assert result["mal_id"] == "40748"
        assert result["season"] == "1"

    def test_encoded_values_decoded(self):
        result = parse_params("query=Demon+Slayer&tmdb_type=tv")
        assert result["query"] == "Demon Slayer"
        assert result["tmdb_type"] == "tv"

    def test_percent_encoded_values(self):
        result = parse_params("query=Sword%20Art%20Online")
        assert result["query"] == "Sword Art Online"

    def test_blank_value_preserved(self):
        # keep_blank_values=True means empty string survives
        result = parse_params("info=&mal_id=123")
        assert result["info"] == ""
        assert result["mal_id"] == "123"

    def test_widget_flag(self):
        result = parse_params("info=trakt_trending&widget=true")
        assert result["widget"] == "true"

    def test_page_and_limit(self):
        result = parse_params("info=trakt_popular&page=3&limit=20")
        assert result["page"] == "3"
        assert result["limit"] == "20"

    def test_plugin_url_style_paramstring(self):
        # Real Kodi passes everything after '?' as the paramstring.
        result = parse_params("info=play&mal_id=40748&episode=3&tmdb_type=tv")
        assert result["info"] == "play"
        assert result["mal_id"] == "40748"
        assert result["episode"] == "3"

    def test_list_slug(self):
        result = parse_params("info=trakt_userlist&list_slug=imdb-top-rated-movies")
        assert result["list_slug"] == "imdb-top-rated-movies"

    def test_returns_dict_not_multidict(self):
        # parse_qsl with duplicate keys keeps last; just ensure it's a plain dict.
        result = parse_params("a=1&a=2")
        assert isinstance(result, dict)
