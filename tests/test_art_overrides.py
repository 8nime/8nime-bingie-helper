# -*- coding: utf-8 -*-
"""Tests for art_overrides.py — the per-title artwork override store (G6)."""
import resources.lib.art_overrides as art_overrides


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(art_overrides, "_path", lambda: str(tmp_path / "art_overrides.json"))
    art_overrides._CACHE = None


def test_get_empty(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert art_overrides.get(40748) == {}


def test_set_and_get(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert art_overrides.set_art(40748, poster="http://p.jpg")
    assert art_overrides.get(40748) == {"poster": "http://p.jpg"}


def test_set_merges_poster_and_fanart(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    art_overrides.set_art(40748, poster="http://p.jpg")
    art_overrides.set_art(40748, fanart="http://f.jpg")
    assert art_overrides.get(40748) == {"poster": "http://p.jpg", "fanart": "http://f.jpg"}


def test_persists_across_reload(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    art_overrides.set_art(40748, poster="http://p.jpg")
    art_overrides._CACHE = None  # force reload from disk
    assert art_overrides.get(40748).get("poster") == "http://p.jpg"


def test_get_falsy_mal_returns_empty(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert art_overrides.get(None) == {}


def test_set_falsy_mal_noop(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert art_overrides.set_art(None, poster="x") is False
