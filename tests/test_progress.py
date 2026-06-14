# -*- coding: utf-8 -*-
"""Tests for the unified AniList-id-keyed progress/watched store (O(1) lookups)."""
from resources.lib import progress


class TestMarkAndLookup:
    def test_mark_sets_progress_and_membership(self):
        progress.mark_watched(101922, 40748, 5, total=26)
        assert progress.progress_of(101922) == 5
        assert progress.total_of(101922) == 26
        assert progress.is_watched(101922, 5) is True
        # contiguous: everything up to progress counts as watched
        assert progress.is_watched(101922, 3) is True
        assert progress.is_watched(101922, 6) is False

    def test_progress_never_regresses(self):
        progress.mark_watched(1, 1, 10)
        progress.mark_watched(1, 1, 4)  # re-watch an earlier ep
        assert progress.progress_of(1) == 10

    def test_non_contiguous_gap_mark(self):
        # Watch ep 8 while progress is 2 -> progress jumps to 8, but 3..7 are only
        # "watched" by the contiguous rule, while 8 is explicit.
        progress.mark_watched(2, None, 2)
        progress.mark_watched(2, None, 8)
        assert progress.progress_of(2) == 8
        assert 8 in progress.watched_set(2)

    def test_get_missing_is_none(self):
        assert progress.get(99999) is None
        assert progress.progress_of(99999) == 0
        assert progress.is_watched(99999, 1) is False


class TestApplyAniList:
    def test_apply_sets_progress_without_watched_bloat(self):
        # A 1000-ep monolith synced at progress 900 stores ONE int, not 900 keys.
        progress.apply_anilist(21, 21, 900, total=1000, updated_at=1234.0)
        doc = progress.get(21)
        assert doc["progress"] == 900
        assert doc["total"] == 1000
        assert doc["watched"] == {}  # no per-episode bloat
        assert progress.is_watched(21, 850) is True  # contiguous rule
        assert progress.is_watched(21, 901) is False

    def test_apply_never_regresses_local_progress(self):
        progress.mark_watched(5, 5, 12)
        progress.apply_anilist(5, 5, 3, total=24)  # AniList behind local
        assert progress.progress_of(5) == 12

    def test_local_mark_beats_stale_sync(self):
        progress.apply_anilist(7, 7, 5, total=12)
        progress.mark_watched(7, 7, 9)
        assert progress.progress_of(7) == 9


class TestRecency:
    def test_recent_orders_by_ts_and_skips_zero_progress(self):
        progress.mark_watched(111, None, 3)
        progress.mark_watched(222, None, 1)  # newer
        progress.apply_anilist(333, None, 0, total=12)  # no progress -> excluded
        recent = progress.recent_anilist_ids()
        assert recent[0] == 222
        assert set(recent) == {111, 222}


class TestPersistence:
    def test_persists_across_reload(self):
        progress.mark_watched(40748, 40748, 7, total=26)
        progress.reset()  # drop in-process cache -> next read hits disk
        assert progress.progress_of(40748) == 7
        assert progress.get(40748)["mal_id"] == 40748

    def test_replace_all_preserves_local_marks_and_higher_progress(self):
        progress.mark_watched(9, 9, 15)  # local ahead
        progress.replace_all({9: {"mal_id": 9, "total": 24, "progress": 10, "watched": {}, "ts": 5.0}})
        doc = progress.get(9)
        assert doc["progress"] == 15  # local progress kept
        assert doc["total"] == 24     # synced total applied
