# -*- coding: utf-8 -*-
"""Local watched-episode tracking — independent of AniList.

A small JSON store under the addon profile dir records which episodes the user has
played, keyed by mal_id. This makes the watched indicator work for everyone (not
just AniList-logged-in users); when a token IS present, AniList progress is unioned
in on top (see info_routes). Episode numbers are the PLAY episode (cour-local for a
normal cour, absolute for a TMDB-split monolith) -- the same number the play() route
records and the episode item carries -- so the two always line up.
"""
import json
import os

import xbmcvfs

from resources.lib.constants import ADDON_ID

_CACHE = None  # in-process {str(mal_id): set(int)} cache


def _store_path():
    try:
        base = xbmcvfs.translatePath("special://profile/addon_data/%s/" % ADDON_ID)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".%s" % ADDON_ID)
    return os.path.join(base, "watched.json")


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    _CACHE = {}
    path = _store_path()
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                raw = json.load(handle) or {}
            _CACHE = {str(k): set(int(e) for e in v) for k, v in raw.items()}
    except Exception:
        _CACHE = {}
    return _CACHE


def _save(data):
    path = _store_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        serializable = {k: sorted(v) for k, v in data.items() if v}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(serializable, handle)
    except Exception:
        pass


def watched_episodes(mal_id):
    """Set of locally-watched episode numbers for a mal_id (empty set if none)."""
    if not mal_id:
        return set()
    return set(_load().get(str(mal_id), set()))


def is_watched(mal_id, episode):
    try:
        return int(episode) in watched_episodes(mal_id)
    except (TypeError, ValueError):
        return False


def mark_watched(mal_id, episode):
    """Record an episode as watched locally. Idempotent; persists immediately."""
    if not mal_id:
        return False
    try:
        episode = int(episode)
    except (TypeError, ValueError):
        return False
    if episode < 1:
        return False
    data = _load()
    eps = data.setdefault(str(mal_id), set())
    if episode in eps:
        return False
    eps.add(episode)
    _save(data)
    return True


def reset():
    """Test hook: drop the in-process cache so the next read reloads from disk."""
    global _CACHE
    _CACHE = None
