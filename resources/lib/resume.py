# -*- coding: utf-8 -*-
"""Local in-episode resume points (playback position), independent of AniList.

A small JSON store under the addon profile dir records WHERE in an episode the user
stopped, keyed by AniList media id (the same key the progress store uses, so the two
local stores share one key space). This is per-device (local only) -- AniList holds the
episode-level progress; this layer adds the seconds-into-the-episode that AniList can't
represent.

How it is captured: there is no permanent background service. When playback starts,
``info_routes.play()`` fires a one-shot ``RunScript(... action=resumewatch ...)`` that
launches ``babysit()`` below. That script lives only for the duration of the episode:
it seeks to any saved position once playback starts, samples the position every few
seconds, and the moment playback ends it writes the last position (or clears it, if
the episode finished) and exits. Reading ``Player().getTime()`` only inside the stop
callback is unreliable (Kodi has usually zeroed it by then), which is why we keep the
last sampled value.

Store format: {str(anilist_id): {"ep": int, "pos": float, "dur": float, "ts": float}}
-- a single in-progress resume point per show (the only one "resume" needs).
"""
import os
import time

import xbmc

from resources.lib import progress, store

# Don't offer a resume below this many seconds in -- starting over is fine.
MIN_RESUME_SECS = 30.0
# At/after this fraction of the episode it counts as finished: clear, don't resume.
FINISH_FRACTION = 0.90
# How often the babysitter samples the playback position (seconds).
POLL_SECS = 10
# How long to wait for playback to actually start before giving up (seconds).
START_TIMEOUT_SECS = 30

_CACHE = None  # in-process {str(anilist_id): {"ep": int, "pos": float, "dur": float, "ts": float}}


def _store_path():
    return store.store_path("resume.json")


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    _CACHE = {}
    raw = store.read_json(_store_path(), {}) or {}
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        _CACHE[str(key)] = {
            "ep": int(val.get("ep") or 0),
            "pos": float(val.get("pos") or 0.0),
            "dur": float(val.get("dur") or 0.0),
            "ts": float(val.get("ts") or 0.0),
        }
    return _CACHE


def _save(data):
    store.atomic_write_json(_store_path(), data)


def should_resume(pos, dur):
    """True when `pos` is worth resuming to (far enough in, not effectively finished)."""
    try:
        pos = float(pos)
        dur = float(dur or 0)
    except (TypeError, ValueError):
        return False
    if pos < MIN_RESUME_SECS:
        return False
    if dur > 0 and pos >= dur * FINISH_FRACTION:
        return False
    return True


def is_finished(pos, dur):
    """True when playback reached the end (>= FINISH_FRACTION of a known duration)."""
    try:
        pos = float(pos)
        dur = float(dur or 0)
    except (TypeError, ValueError):
        return False
    return dur > 0 and pos >= dur * FINISH_FRACTION


def get(anilist_id):
    """Resume point dict for an AniList id, or None when there's nothing to resume."""
    if not anilist_id:
        return None
    return _load().get(str(anilist_id))


def set_point(anilist_id, episode, pos, dur):
    """Record where the user stopped within an episode. Persists immediately."""
    if not anilist_id:
        return
    try:
        episode = int(episode)
        pos = float(pos)
        dur = float(dur or 0)
    except (TypeError, ValueError):
        return
    data = _load()
    data[str(anilist_id)] = {"ep": episode, "pos": pos, "dur": dur, "ts": time.time()}
    _save(data)


def clear(anilist_id):
    """Drop the resume point for an AniList id (episode finished / not worth resuming)."""
    if not anilist_id:
        return
    data = _load()
    if data.pop(str(anilist_id), None) is not None:
        _save(data)


def recent_anilist_ids(limit=40):
    """AniList ids with an active resume point, most-recently-played first.

    Used to keep partially-watched shows (no episode finished yet) in Continue
    Watching now that watched-marking is completion-based."""
    data = _load()
    ordered = sorted(data.items(), key=lambda kv: kv[1].get("ts") or 0, reverse=True)
    out = []
    for key, _ in ordered:
        try:
            out.append(int(key))
        except (TypeError, ValueError):
            continue
        if len(out) >= limit:
            break
    return out


def reset():
    """Test hook: drop the in-process cache so the next read reloads from disk."""
    global _CACHE
    _CACHE = None


def _session_path():
    return os.path.join(os.path.dirname(_store_path()), "resume_session")


def _write_session(token):
    try:
        os.makedirs(os.path.dirname(_session_path()), exist_ok=True)
        with open(_session_path(), "w", encoding="utf-8") as handle:
            handle.write(token)
    except Exception:
        pass


def _read_session():
    try:
        with open(_session_path(), encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return ""


def _mark_finished(anilist_id, episode, mal_id):
    """Completion: record the episode in the unified O(1) progress store + advance
    AniList. Runs only at ~90% playback (completion-based, not optimistic). ``anilist_id``
    is the store key, so without it there is nothing to record against (every real media
    item carries an AniList id); ``mal_id`` is stored as a secondary field on the doc."""
    if not anilist_id:
        return
    try:
        progress.mark_watched(int(anilist_id), mal_id, episode)
    except Exception:
        pass
    try:
        from resources.lib.api import AniListClient
        AniListClient().update_progress(int(anilist_id), episode)
    except Exception:
        pass


def babysit(anilist_id, episode, mal_id=None):
    """One-shot, per-play position + completion tracker (NOT a permanent service).

    Launched via RunScript when an episode starts. Seeks to a saved position (same
    episode) once playback begins, samples the position while it plays, then on stop:
    if ~finished, marks the episode watched (local + AniList) and clears the resume
    point; if partway, stores the resume position; otherwise clears it. Holds a
    Player only for this one playback session and then exits.
    """
    if not anilist_id:
        return
    try:
        episode = int(episode)
    except (TypeError, ValueError):
        return

    player = xbmc.Player()
    monitor = xbmc.Monitor()

    # Read the pre-play resume point BEFORE we start overwriting it this session.
    saved = get(anilist_id)

    # Claim the playback session. If a newer play starts (its babysitter writes a
    # fresh token), this one bails instead of capturing the new episode's position
    # under our key -- the per-play babysitters can briefly overlap otherwise.
    token = "%s:%s:%f" % (anilist_id, episode, time.time())
    _write_session(token)

    # Wait for playback to actually begin (the provider resolve can take seconds).
    waited = 0
    while not player.isPlaying() and waited < START_TIMEOUT_SECS:
        if monitor.waitForAbort(1):
            return
        waited += 1
    if not player.isPlaying():
        return

    # Resume: seek to the saved position for THIS episode, once -- but only if it's
    # plausibly the SAME stream we recorded against. A scraper re-resolve can land a
    # different/short encode; seeking past its end would instantly trip is_finished and
    # falsely mark the episode watched, so we bail on a large duration mismatch and
    # never seek past the finish threshold.
    if saved and saved.get("ep") == episode and should_resume(saved.get("pos"), saved.get("dur")):
        try:
            live_dur = float(player.getTotalTime() or 0)
        except Exception:
            live_dur = 0.0
        pos = float(saved["pos"])
        saved_dur = float(saved.get("dur") or 0)
        ref_dur = live_dur or saved_dur
        mismatch = bool(live_dur and saved_dur and abs(live_dur - saved_dur) > max(60.0, 0.2 * saved_dur))
        if not mismatch and (not ref_dur or pos < ref_dur * FINISH_FRACTION):
            try:
                player.seekTime(pos)
            except Exception:
                pass

    last_pos, last_dur = 0.0, 0.0
    while player.isPlaying():
        if _read_session() != token:
            return  # a newer play took over -> leave its position alone
        try:
            last_pos = float(player.getTime())
            last_dur = float(player.getTotalTime())
        except Exception:
            pass
        if monitor.waitForAbort(POLL_SECS):
            break

    if _read_session() != token:
        return  # superseded between the last sample and stop -> don't clobber

    # Playback ended -> persist the outcome.
    if is_finished(last_pos, last_dur):
        _mark_finished(anilist_id, episode, mal_id)  # completion-based watched mark
        clear(anilist_id)
    elif should_resume(last_pos, last_dur):
        set_point(anilist_id, episode, last_pos, last_dur)
    else:
        clear(anilist_id)
