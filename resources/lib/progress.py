# -*- coding: utf-8 -*-
"""Unified watched/progress store — keyed by AniList media id, O(1) lookups.

This is the single source of truth the resume/Play path reads, so it must never do
network I/O on a lookup. It is populated two ways:
  * the boot service (service.py) syncs the user's whole AniList list into it ONCE
    at Kodi start (see api.sync_progress) -- if there's an AniList login;
  * local episode completions write into it (resume._mark_finished).

Why AniList id (not mal_id): AniList tracks progress per media entry and its id is
always present, whereas idMal can be null. For a multi-cour franchise each season is
its own AniList entry (its own doc); a TMDB-split monolith (One Piece) is ONE entry
with absolute episode numbers (its display arcs are derived at render time).

Document (flat, per AniList entry):
    {str(anilist_id): {"mal_id": int|None, "total": int, "progress": int,
                       "watched": {str(ep): true}, "ts": float}}
  - progress: furthest watched episode  -> O(1) next-episode = progress + 1
  - watched : explicit per-episode marks -> O(1) "is ep N watched?". Only LOCAL marks
              populate it (the AniList sync sets progress only), so it stays small
              even for a 1000-episode monolith. An episode counts as watched when
              `ep <= progress OR str(ep) in watched`.
  - total   : episode count (caught-up reference)
  - ts      : recency (max of local-mark time and AniList updatedAt) for Continue
              Watching ordering.
Episode numbers use the PLAY numbering the rest of the addon uses: cour-local for a
normal Fribb cour, ABSOLUTE for a TMDB-split monolith.
"""
import time

from resources.lib import store

_CACHE = None  # in-process {str(anilist_id): {...}}


def _store_path():
    return store.store_path("progress.json")


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
            "mal_id": val.get("mal_id"),
            "total": int(val.get("total") or 0),
            "progress": int(val.get("progress") or 0),
            "watched": {str(e): True for e in (val.get("watched") or {})},
            "ts": float(val.get("ts") or 0.0),
        }
    return _CACHE


def _save(data):
    store.atomic_write_json(_store_path(), data)


def _doc(anilist_id):
    if not anilist_id:
        return None
    return _load().get(str(anilist_id))


def get(anilist_id):
    """Full document for an AniList id, or None. O(1)."""
    return _doc(anilist_id)


def progress_of(anilist_id):
    """Furthest watched episode for an AniList id (0 if untracked). O(1)."""
    doc = _doc(anilist_id)
    return int(doc["progress"]) if doc else 0


def total_of(anilist_id):
    """Stored episode count for an AniList id (0 if unknown). O(1)."""
    doc = _doc(anilist_id)
    return int(doc["total"]) if doc else 0


def is_watched(anilist_id, episode):
    """True if `episode` is watched (contiguous up to progress, or an explicit mark)."""
    doc = _doc(anilist_id)
    if not doc:
        return False
    try:
        ep = int(episode)
    except (TypeError, ValueError):
        return False
    return ep <= int(doc["progress"]) or str(ep) in doc["watched"]


def watched_set(anilist_id):
    """Set of explicitly-marked watched episodes (NOT the contiguous 1..progress).

    Callers that render checkmarks should union this with range(1, progress+1)."""
    doc = _doc(anilist_id)
    if not doc:
        return set()
    out = set()
    for e in doc["watched"]:
        try:
            out.add(int(e))
        except (TypeError, ValueError):
            continue
    return out


def apply_anilist(anilist_id, mal_id, progress, total=0, updated_at=0):
    """Merge an AniList list entry into the store (boot/login sync).

    Sets progress (never regresses) + total + mal_id + recency; does NOT populate the
    `watched` map (the contiguous 1..progress range covers synced episodes)."""
    if not anilist_id:
        return
    try:
        progress = int(progress or 0)
    except (TypeError, ValueError):
        progress = 0
    data = _load()
    doc = data.setdefault(str(anilist_id), {"mal_id": None, "total": 0, "progress": 0, "watched": {}, "ts": 0.0})
    if mal_id:
        doc["mal_id"] = int(mal_id)
    if total:
        doc["total"] = int(total)
    doc["progress"] = max(int(doc["progress"]), progress)
    doc["ts"] = max(float(doc["ts"]), float(updated_at or 0))
    _save(data)


def mark_watched(anilist_id, mal_id, episode, total=0):
    """Record a locally-completed episode (resume._mark_finished). Persists immediately.

    Returns True when newly recorded. Bumps progress to the furthest watched episode
    and stamps recency to now."""
    if not anilist_id:
        return False
    try:
        episode = int(episode)
    except (TypeError, ValueError):
        return False
    if episode < 1:
        return False
    reset()  # re-read current disk before the read-modify-write so a concurrent
    data = _load()  # process's write (boot-service sync) isn't clobbered (R3-2)
    doc = data.setdefault(str(anilist_id), {"mal_id": None, "total": 0, "progress": 0, "watched": {}, "ts": 0.0})
    if mal_id:
        doc["mal_id"] = int(mal_id)
    if total:
        doc["total"] = int(total)
    new = str(episode) not in doc["watched"] and episode > int(doc["progress"])
    doc["watched"][str(episode)] = True
    doc["progress"] = max(int(doc["progress"]), episode)
    doc["ts"] = time.time()
    _save(data)
    return new


def recent_anilist_ids(limit=40):
    """AniList ids with progress, most-recently-active first (Continue Watching)."""
    data = _load()
    ordered = sorted(data.items(), key=lambda kv: kv[1].get("ts") or 0, reverse=True)
    out = []
    for key, val in ordered:
        if not int(val.get("progress") or 0):
            continue
        try:
            out.append(int(key))
        except (TypeError, ValueError):
            continue
        if len(out) >= limit:
            break
    return out


def replace_all(docs):
    """Bulk-replace the store from a freshly-built {anilist_id: doc} map (sync).

    Used by the boot sync to write the whole list in one save. Preserves any existing
    local `watched` marks + a higher local progress for an id already present."""
    reset()  # merge against CURRENT disk, not the long-lived service _CACHE snapshot,
    data = _load()  # so a babysit completion mid-sync isn't clobbered (R3-2)
    for key, incoming in (docs or {}).items():
        skey = str(key)
        existing = data.get(skey)
        if existing:
            incoming = dict(incoming)
            # Don't let a sync with idMal=null wipe a previously-known mal_id (the
            # next_up tier-1 cache path keys on it); keep the incoming one if present.
            incoming["mal_id"] = incoming.get("mal_id") or existing.get("mal_id")
            incoming["progress"] = max(int(existing.get("progress") or 0), int(incoming.get("progress") or 0))
            # Keep the higher known episode count: a lean re-sync can return total=0
            # for an ongoing show, which must not regress a previously-known count
            # (the caught-up / last-released logic depends on it).
            incoming["total"] = max(int(existing.get("total") or 0), int(incoming.get("total") or 0))
            incoming["watched"] = dict(existing.get("watched") or {})
            incoming["ts"] = max(float(existing.get("ts") or 0), float(incoming.get("ts") or 0))
        # Normalize to the full doc shape (like _load) so a partial incoming dict can't
        # leave a doc missing keys that progress_of/is_watched/watched_set subscript (R3-7).
        data[skey] = {
            "mal_id": incoming.get("mal_id"),
            "total": int(incoming.get("total") or 0),
            "progress": int(incoming.get("progress") or 0),
            "watched": {str(e): True for e in (incoming.get("watched") or {})},
            "ts": float(incoming.get("ts") or 0.0),
        }
    _save(data)


def reset():
    """Test hook: drop the in-process cache so the next read reloads from disk."""
    global _CACHE
    _CACHE = None
