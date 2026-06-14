# -*- coding: utf-8 -*-
"""Local watched-episode tracking — independent of AniList.

A small JSON store under the addon profile dir records which episodes the user has
played (and when), keyed by mal_id. This makes the watched indicator AND the
Continue Watching row work for everyone (not just AniList-logged-in users); when a
token IS present, AniList progress/CURRENT is unioned in on top (see api/info_routes).

Store format: {str(mal_id): {"eps": [int...], "ts": <unix float>}}. An older
list-only format ({mal_id: [eps]}) is migrated transparently on load.
Episode numbers are the PLAY episode (cour-local for a normal cour, absolute for a
TMDB-split monolith) -- the same number play() records and the episode item carries.
"""
import json
import os
import time

import xbmcvfs

from resources.lib.constants import ADDON_ID

_CACHE = None  # in-process {str(mal_id): {"eps": set(int), "ts": float}}


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
    try:
        path = _store_path()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                raw = json.load(handle) or {}
            for key, val in raw.items():
                if isinstance(val, dict):  # current format
                    eps = set(int(e) for e in val.get("eps", []))
                    ts = float(val.get("ts") or 0)
                else:  # legacy list-only format
                    eps = set(int(e) for e in val)
                    ts = 0.0
                _CACHE[str(key)] = {"eps": eps, "ts": ts}
    except Exception:
        _CACHE = {}
    return _CACHE


def _save(data):
    try:
        path = _store_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        serializable = {
            k: {"eps": sorted(v["eps"]), "ts": v["ts"]}
            for k, v in data.items() if v.get("eps")
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(serializable, handle)
    except Exception:
        pass


def watched_episodes(mal_id):
    """Set of locally-watched episode numbers for a mal_id (empty set if none)."""
    if not mal_id:
        return set()
    entry = _load().get(str(mal_id))
    return set(entry["eps"]) if entry else set()


def is_watched(mal_id, episode):
    try:
        return int(episode) in watched_episodes(mal_id)
    except (TypeError, ValueError):
        return False


def mark_watched(mal_id, episode):
    """Record an episode as watched locally (with a timestamp). Persists immediately.

    Returns True when newly recorded, False when already present / invalid."""
    if not mal_id:
        return False
    try:
        episode = int(episode)
    except (TypeError, ValueError):
        return False
    if episode < 1:
        return False
    data = _load()
    entry = data.setdefault(str(mal_id), {"eps": set(), "ts": 0.0})
    new = episode not in entry["eps"]
    entry["eps"].add(episode)
    entry["ts"] = time.time()  # bump recency even on a re-watch
    _save(data)
    return new


def recent_mal_ids(limit=40):
    """mal_ids with locally-watched episodes, most-recently-watched first."""
    data = _load()
    ordered = sorted(data.items(), key=lambda kv: kv[1].get("ts") or 0, reverse=True)
    out = []
    for key, val in ordered:
        if not val.get("eps"):
            continue
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
