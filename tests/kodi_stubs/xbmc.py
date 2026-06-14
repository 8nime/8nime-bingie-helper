# -*- coding: utf-8 -*-
"""Minimal xbmc stub for running addon code outside Kodi."""

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4


def log(msg, level=LOGINFO):
    pass


def sleep(ms):
    # No-op in tests: real waiting only slows the suite (e.g. default.py's
    # post-refresh spinner-settle sleep). Tests assert behaviour, not timing.
    pass


def translatePath(path):
    return path


def getCondVisibility(condition):
    return False


def executebuiltin(cmd):
    pass


def getInfoLabel(label):
    return ""


# --- Player/Monitor: scriptable playback timeline for resume-babysitter tests ---
# Tests set `_playback` to {"frames": [(pos, dur), ...], "seek": []}. Each
# Monitor.waitForAbort() consumes one frame; when frames run out, isPlaying() is
# False (playback ended). seekTime() records the requested offsets.
_playback = None


def _set_playback(frames, seek=None):
    global _playback
    _playback = {"frames": list(frames), "seek": seek if seek is not None else []}
    return _playback


class Monitor:
    def waitForAbort(self, timeout=0):
        if _playback and _playback["frames"]:
            _playback["frames"].pop(0)
        return False

    def abortRequested(self):
        return False


class Player:
    def isPlaying(self):
        return bool(_playback and _playback["frames"])

    def getTime(self):
        if _playback and _playback["frames"]:
            return _playback["frames"][0][0]
        return 0.0

    def getTotalTime(self):
        if _playback and _playback["frames"]:
            return _playback["frames"][0][1]
        return 0.0

    def seekTime(self, seconds):
        if _playback is not None:
            _playback["seek"].append(seconds)
