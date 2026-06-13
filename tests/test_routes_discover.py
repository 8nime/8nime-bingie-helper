# -*- coding: utf-8 -*-
"""discover() genre handling — G7: never silently default an unknown genre to Action."""
from unittest.mock import patch

from resources.lib.routes import RouteHandler


def _vars_recorder(captured):
    def browse(variables, trending=False):
        captured.append(variables)
        return ([], False)
    return browse


def _run(params):
    h = RouteHandler(1, dict(params, info="discover"))
    captured = []
    h.client.browse = _vars_recorder(captured)
    with patch("resources.lib.routes.build_items", return_value=[]):
        h.discover()
    return captured[0] if captured else {}


class TestDiscoverGenre:
    def test_with_id_true_name_used(self):
        v = _run({"with_genres": "Psychological", "with_id": "True", "tmdb_type": "tv"})
        assert v.get("includedGenres") == ["Psychological"]

    def test_with_id_false_name_used(self):
        v = _run({"with_genres": "Mecha", "with_id": "False", "tmdb_type": "tv"})
        assert v.get("includedGenres") == ["Mecha"]

    def test_with_id_true_known_tmdb_id_mapped(self):
        v = _run({"with_genres": "28", "with_id": "True", "tmdb_type": "tv"})
        assert v.get("includedGenres") == ["Action"]

    def test_with_id_true_unknown_numeric_dropped_not_action(self):
        v = _run({"with_genres": "99999", "with_id": "True", "tmdb_type": "tv"})
        assert "includedGenres" not in v
