# -*- coding: utf-8 -*-
"""Local watched store (AniList-independent) + the guarded AniList progress sync."""
from resources.lib import watched
from resources.lib.api import AniListClient


class TestLocalWatchedStore:
    def test_mark_and_read_round_trip(self):
        assert watched.watched_episodes(40748) == set()
        assert watched.mark_watched(40748, 3) is True
        assert watched.mark_watched(40748, 5) is True
        assert watched.watched_episodes(40748) == {3, 5}
        assert watched.is_watched(40748, 3) is True
        assert watched.is_watched(40748, 4) is False

    def test_mark_is_idempotent(self):
        assert watched.mark_watched(1, 2) is True
        assert watched.mark_watched(1, 2) is False  # already recorded
        assert watched.watched_episodes(1) == {2}

    def test_persists_across_cache_reset(self):
        watched.mark_watched(7, 9)
        watched.reset()  # drop in-process cache -> must reload from disk
        assert watched.is_watched(7, 9) is True

    def test_ignores_bad_episode(self):
        assert watched.mark_watched(2, "x") is False
        assert watched.mark_watched(2, 0) is False
        assert watched.watched_episodes(2) == set()


class TestUpdateProgress:
    def _client(self, monkeypatch, *, token=True, entry=None, total=12, posted=None):
        c = AniListClient.__new__(AniListClient)
        monkeypatch.setattr(c, "has_token", lambda: token)
        monkeypatch.setattr(c, "_entry", lambda mid: entry)
        monkeypatch.setattr(c, "get_media", lambda mal_id=None, anilist_id=None: {"episodes": total})
        monkeypatch.setattr("resources.lib.api.clear_all_caches", lambda **k: None)

        def _post(query, variables=None, use_cache=True):
            if posted is not None:
                posted.append(variables)
            return {"SaveMediaListEntry": {"id": 1, "progress": variables["progress"], "status": variables["status"]}}

        monkeypatch.setattr(c, "_post", _post)
        return c

    def test_advances_and_sets_current(self, monkeypatch):
        posted = []
        c = self._client(monkeypatch, entry={"progress": 2, "status": "CURRENT"}, total=12, posted=posted)
        ok, status = c.update_progress(101922, 3)
        assert ok and status == "progress"
        assert posted[0]["progress"] == 3 and posted[0]["status"] == "CURRENT"

    def test_completes_at_final_episode(self, monkeypatch):
        posted = []
        c = self._client(monkeypatch, entry={"progress": 11, "status": "CURRENT"}, total=12, posted=posted)
        c.update_progress(101922, 12)
        assert posted[0]["status"] == "COMPLETED"

    def test_never_regresses(self, monkeypatch):
        posted = []
        c = self._client(monkeypatch, entry={"progress": 8, "status": "CURRENT"}, posted=posted)
        ok, status = c.update_progress(101922, 5)
        assert ok is False and status == "no_advance" and posted == []

    def test_no_token_is_noop(self, monkeypatch):
        c = self._client(monkeypatch, token=False)
        assert c.update_progress(101922, 3) == (False, "not_logged_in")
