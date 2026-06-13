# -*- coding: utf-8 -*-
"""Tests for default.py — the RunScript entry: arg parsing (G1/G3) + sync (G2)."""
import sys

import resources.lib.identity as identity
import default as default_mod


class TestMergeQuery:
    def test_sets_param_and_resets_page(self):
        url = "plugin://plugin.video.8nime.bingie.helper/?info=dir_tv&page=4"
        out = default_mod._merge_query(url, {"search": "naruto"})
        assert "info=dir_tv" in out
        assert "search=naruto" in out
        assert "page=" not in out  # page reset

    def test_empty_value_removes_param(self):
        url = "plugin://plugin.video.8nime.bingie.helper/?info=dir_tv&search=old"
        out = default_mod._merge_query(url, {"search": ""})
        assert "search" not in out
        assert "info=dir_tv" in out

    def test_preserves_other_params(self):
        url = "plugin://plugin.video.8nime.bingie.helper/?info=dir_tv&search=x"
        out = default_mod._merge_query(url, {"sort": "score"})
        assert "search=x" in out
        assert "sort=score" in out


class TestMainDispatch:
    def test_positional_sync_trakt_dispatches(self, monkeypatch):
        # G1: sync_trakt is a bare positional token; it must still reach the handler
        # (the old parser dropped it -> fell through to the description popup).
        called = {}
        monkeypatch.setattr(default_mod, "sync_trakt_rating", lambda args: called.update(args))
        monkeypatch.setattr(
            sys, "argv",
            ["default.py", "sync_trakt", "tmdb_id=900101922", "tmdb_type=tv", "sync_type=like"],
        )
        default_mod.main()
        assert called.get("sync_type") == "like"
        assert called.get("tmdb_id") == "900101922"

    def test_cache_refresh_positional_sets_sync_type(self, monkeypatch):
        # G3: cache_refresh is positional; it must become sync_type=cache_refresh.
        captured = {}
        monkeypatch.setattr(default_mod, "sync_trakt_rating", lambda args: captured.update(args))
        monkeypatch.setattr(
            sys, "argv", ["default.py", "sync_trakt", "cache_refresh", "tmdb_id=85937"],
        )
        default_mod.main()
        assert captured.get("sync_type") == "cache_refresh"

    def test_description_kv_still_dispatches(self, monkeypatch):
        called = {}
        monkeypatch.setattr(default_mod, "show_description", lambda **kw: called.update(kw))
        monkeypatch.setattr(sys, "argv", ["default.py", "description=Naruto", "tmdb_type=tv"])
        default_mod.main()
        assert called.get("query") == "Naruto"


class TestSyncTraktRating:
    def test_reverse_maps_surrogate_tmdb_id_to_mal(self, monkeypatch):
        # G2: the skin sends a tmdb_id (here a surrogate), not a mal_id; the handler
        # must reverse-map it before scoring.
        scored = {}

        class FakeClient:
            def has_token(self):
                return True

            def get_media(self, mal_id=None, anilist_id=None):
                return None

            def resolve_mal_id(self, params):
                return None

            def save_media_score(self, mal_id, sync_type):
                scored["mal_id"] = mal_id
                scored["sync_type"] = sync_type
                return True, sync_type

        monkeypatch.setattr(default_mod, "AniListClient", FakeClient)
        monkeypatch.setattr(default_mod, "bump_widget_reload", lambda: None)
        surrogate = identity.encode_surrogate("mal", 40748)
        default_mod.sync_trakt_rating({"tmdb_id": str(surrogate), "sync_type": "like"})
        assert scored == {"mal_id": 40748, "sync_type": "like"}

    def test_cache_refresh_needs_no_token(self, monkeypatch):
        busted = {}
        monkeypatch.setattr(default_mod, "clear_all_caches", lambda expired_only=False: busted.setdefault("cleared", True))
        monkeypatch.setattr(default_mod, "bump_widget_reload", lambda: None)
        default_mod.sync_trakt_rating({"sync_type": "cache_refresh"})
        assert busted.get("cleared")


class TestG6Handlers:
    def test_select_artwork_stores_override(self, monkeypatch, tmp_path):
        import resources.lib.art_overrides as art_overrides
        monkeypatch.setattr(art_overrides, "_path", lambda: str(tmp_path / "ao.json"))
        art_overrides._CACHE = None
        media = {
            "idMal": 40748,
            "coverImage": {"extraLarge": "http://cover.jpg"},
            "bannerImage": "http://banner.jpg",
        }

        class FakeClient:
            def resolve_mal_id(self, params):
                return 40748

            def get_media(self, mal_id=None, anilist_id=None):
                return media

        monkeypatch.setattr(default_mod, "AniListClient", FakeClient)
        monkeypatch.setattr(default_mod, "bump_widget_reload", lambda: None)
        # Dialog().select stub returns 0 -> first option = "Use cover as poster".
        default_mod.select_artwork({"mal_id": "40748"})
        assert art_overrides.get(40748).get("poster") == "http://cover.jpg"

    def test_refresh_details_busts_cache(self, monkeypatch):
        busted = {}
        monkeypatch.setattr(default_mod, "clear_all_caches", lambda expired_only=False: busted.setdefault("c", True))
        monkeypatch.setattr(default_mod, "bump_widget_reload", lambda: None)
        default_mod.refresh_details({})
        assert busted.get("c")

    def test_positional_select_artwork_dispatches(self, monkeypatch):
        called = {}
        monkeypatch.setattr(default_mod, "select_artwork", lambda args: called.update(args))
        monkeypatch.setattr(sys, "argv", ["default.py", "select_artwork", "tmdb_id=900101922", "tmdb_type=tv"])
        default_mod.main()
        assert called.get("tmdb_id") == "900101922"

    def test_positional_refresh_details_dispatches(self, monkeypatch):
        called = {}
        monkeypatch.setattr(default_mod, "refresh_details", lambda args: called.setdefault("hit", True))
        monkeypatch.setattr(sys, "argv", ["default.py", "refresh_details", "tmdb_id=85937"])
        default_mod.main()
        assert called.get("hit")


class TestAniListLoginDispatch:
    def test_login_action_runs_and_reloads(self, monkeypatch):
        from resources.lib import anilist_login
        flags = {}
        monkeypatch.setattr(anilist_login, "prompt_login", lambda: flags.setdefault("login", True) or True)
        monkeypatch.setattr(default_mod, "bump_widget_reload", lambda: flags.setdefault("reload", True))
        monkeypatch.setattr(sys, "argv", ["default.py", "anilist_login=true"])
        default_mod.main()
        assert flags.get("login") and flags.get("reload")

    def test_login_no_reload_when_login_fails(self, monkeypatch):
        from resources.lib import anilist_login
        flags = {}
        monkeypatch.setattr(anilist_login, "prompt_login", lambda: False)
        monkeypatch.setattr(default_mod, "bump_widget_reload", lambda: flags.setdefault("reload", True))
        monkeypatch.setattr(sys, "argv", ["default.py", "anilist_login=true"])
        default_mod.main()
        assert "reload" not in flags

    def test_logout_action_runs_and_reloads(self, monkeypatch):
        from resources.lib import anilist_login
        flags = {}
        monkeypatch.setattr(anilist_login, "logout", lambda: flags.setdefault("logout", True) or True)
        monkeypatch.setattr(default_mod, "bump_widget_reload", lambda: flags.setdefault("reload", True))
        monkeypatch.setattr(sys, "argv", ["default.py", "anilist_logout=true"])
        default_mod.main()
        assert flags.get("logout") and flags.get("reload")
