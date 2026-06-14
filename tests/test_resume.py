# -*- coding: utf-8 -*-
"""Tests for the local in-episode resume store + the one-shot playback babysitter.

The babysitter drives an xbmc.Player/Monitor; the stub (tests/kodi_stubs/xbmc.py)
exposes a scriptable playback timeline via xbmc._set_playback so we can simulate a
short play session ending at a chosen position.
"""
import xbmc

from resources.lib import resume, watched


class TestDecisionHelpers:
    def test_should_resume_far_enough_in(self):
        assert resume.should_resume(120, 1400) is True

    def test_no_resume_when_barely_started(self):
        assert resume.should_resume(5, 1400) is False

    def test_no_resume_when_effectively_finished(self):
        # 95% of the way through -> treat as done, don't resume.
        assert resume.should_resume(1330, 1400) is False

    def test_should_resume_unknown_duration(self):
        # No duration known but well past the floor -> still resumable.
        assert resume.should_resume(120, 0) is True

    def test_is_finished_at_threshold(self):
        assert resume.is_finished(1260, 1400) is True
        assert resume.is_finished(1259, 1400) is False

    def test_is_finished_unknown_duration(self):
        assert resume.is_finished(120, 0) is False


class TestStore:
    def test_set_and_get_roundtrip(self):
        resume.set_point(40748, 5, 742.5, 1400.0)
        point = resume.get(40748)
        assert point["ep"] == 5
        assert point["pos"] == 742.5
        assert point["dur"] == 1400.0

    def test_get_missing_is_none(self):
        assert resume.get(40748) is None

    def test_clear_removes_point(self):
        resume.set_point(40748, 5, 742.5, 1400.0)
        resume.clear(40748)
        assert resume.get(40748) is None

    def test_persists_across_reload(self):
        resume.set_point(40748, 3, 300.0, 1400.0)
        resume.reset()  # drop in-process cache -> next read hits disk
        assert resume.get(40748)["ep"] == 3

    def test_recent_mal_ids_most_recent_first(self):
        resume.set_point(111, 1, 100.0, 1400.0)
        resume.set_point(222, 1, 100.0, 1400.0)  # written later -> newer ts
        recent = resume.recent_mal_ids()
        assert recent[0] == 222
        assert set(recent) == {111, 222}


class TestBabysit:
    def test_captures_stop_position(self):
        # Playback ends at 200s of a 1400s episode -> a resume point is stored and the
        # episode is NOT marked watched (completion-based: only ~90% counts).
        xbmc._set_playback([(100, 1400), (200, 1400)])
        resume.babysit("40748", 5)
        point = resume.get(40748)
        assert point["ep"] == 5
        assert point["pos"] == 200
        assert 5 not in watched.watched_episodes(40748)

    def test_finished_episode_marks_watched_and_clears_point(self):
        # Pre-existing resume point; this play runs to ~the end -> watched + cleared.
        resume.set_point(40748, 5, 200.0, 1400.0)
        xbmc._set_playback([(1300, 1400), (1390, 1400)])
        resume.babysit("40748", 5)
        assert resume.get(40748) is None
        assert 5 in watched.watched_episodes(40748)

    def test_seeks_to_saved_position_for_same_episode(self):
        resume.set_point(40748, 5, 742.0, 1400.0)
        pb = xbmc._set_playback([(742, 1400), (800, 1400)])
        resume.babysit("40748", 5)
        assert 742.0 in pb["seek"]

    def test_does_not_seek_for_different_episode(self):
        resume.set_point(40748, 5, 742.0, 1400.0)
        pb = xbmc._set_playback([(10, 1400), (60, 1400)])
        resume.babysit("40748", 6)  # playing a different episode
        assert pb["seek"] == []

    def test_no_playback_is_noop(self):
        xbmc._set_playback([])  # nothing ever plays
        resume.babysit("40748", 5)
        assert resume.get(40748) is None

    def test_superseded_session_does_not_clobber(self, monkeypatch):
        # A newer play owns the session token -> this babysitter must NOT overwrite
        # the (newer) saved point with the position it is sampling.
        resume.set_point(40748, 5, 200.0, 1400.0)
        xbmc._set_playback([(300, 1400), (400, 1400)])
        monkeypatch.setattr(resume, "_read_session", lambda: "a-newer-session")
        resume.babysit("40748", 5)
        assert resume.get(40748)["pos"] == 200.0  # untouched
