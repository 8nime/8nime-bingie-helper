# -*- coding: utf-8 -*-
"""Authoritative AniList/MAL -> TVDB-season lookup, sourced online from GitHub.

Why online (not bundled): the only file that carries both AniList/MAL ids *and*
the TVDB season in one place is Fribb/anime-lists `anime-list-full.json`. We do
NOT ship it in the addon. Instead the background service downloads it (gzip on
the wire -> ~1.2 MB, not 7 MB), distils a compact ~420 KB map, and caches that
under the addon's profile data dir. Re-downloads are gated two ways so we almost
never pay the transfer:

  * TTL  -- we only even *check* upstream every few days.
  * SHA  -- we ask the GitHub commits API for the file's latest commit SHA (a
            tiny request) and skip the bulk download unless it changed.

The plugin processes only ever READ the cache (no network on the lookup path, so
the UI never blocks). If the cache is missing/stale the franchise builder simply
falls back to its AniList relation walk.
"""
import json
import os
import threading
import time

ADDON_ID = "plugin.video.8nime.bingie.helper"
RAW_URL = "https://raw.githubusercontent.com/Fribb/anime-lists/master/anime-list-full.json"
COMMITS_API = (
    "https://api.github.com/repos/Fribb/anime-lists/commits"
    "?path=anime-list-full.json&per_page=1"
)
TV_TYPES = {"TV", "TV_SHORT"}
# Only check upstream this often (seconds). Seasons change slowly and brand-new
# cours are healed live by the relation-walk forward-extend, so weekly is plenty.
CHECK_INTERVAL = 7 * 24 * 3600
# Compact-cache schema version. Bump when the record layout changes so an old
# cache is rebuilt on next refresh even if the upstream SHA is unchanged.
FORMAT = 2

_LOCK = threading.Lock()
_LOADED = False
_BY_ANILIST = {}
_BY_MAL = {}
_TVDB_MEMBERS = {}
_META = {}


# --------------------------------------------------------------------------- #
# Pure data layer (no Kodi deps -- importable by the dev/validation script).
# --------------------------------------------------------------------------- #
def _season_of(entry):
    season = entry.get("season")
    if not isinstance(season, dict):
        return None
    for key in ("tvdb", "tmdb"):
        val = season.get(key)
        if isinstance(val, int):
            return val
    return None


def _tmdb_of(entry):
    """Return (tmdb_tv_id, tmdb_season) for an entry, or (None, None).

    Fribb stores themoviedb_id as {'tv': id} / {'movie': id} (and occasionally a
    bare int). We only want the TV id, since stills/taxonomy come from TMDB's TV
    endpoints. tmdb_season is the season number under TMDB's own numbering.
    """
    raw = entry.get("themoviedb_id")
    tmdb_id = None
    if isinstance(raw, dict):
        tv = raw.get("tv")
        if isinstance(tv, int):
            tmdb_id = tv
    elif isinstance(raw, int):
        tmdb_id = raw
    season = entry.get("season")
    tmdb_season = season.get("tmdb") if isinstance(season, dict) else None
    if not isinstance(tmdb_season, int):
        tmdb_season = None
    return tmdb_id, tmdb_season


def build_compact(data):
    """Distil Fribb's anime-list-full into the compact lookup structure.

    Record layout (FORMAT 2):
      by_anilist/by_mal[id] = [tvdb_id, tvdb_season, tmdb_id, tmdb_season]
      tvdb_members[tvdb_id] = [[anilist, mal, tvdb_season, is_tv, tmdb_id, tmdb_season], ...]
    tmdb_id / tmdb_season may be null when Fribb has no TMDB mapping.
    """
    by_anilist = {}
    by_mal = {}
    tvdb_members = {}
    for entry in data:
        tvdb_id = entry.get("tvdb_id")
        if not isinstance(tvdb_id, int):
            continue
        season = _season_of(entry)
        if season is None:
            continue
        anilist_id = entry.get("anilist_id")
        mal_id = entry.get("mal_id")
        tmdb_id, tmdb_season = _tmdb_of(entry)
        is_tv = 1 if (entry.get("type") or "").upper() in TV_TYPES else 0
        if isinstance(anilist_id, int):
            by_anilist[str(anilist_id)] = [tvdb_id, season, tmdb_id, tmdb_season]
        if isinstance(mal_id, int):
            by_mal[str(mal_id)] = [tvdb_id, season, tmdb_id, tmdb_season]
        tvdb_members.setdefault(str(tvdb_id), []).append(
            [
                anilist_id if isinstance(anilist_id, int) else None,
                mal_id if isinstance(mal_id, int) else None,
                season,
                is_tv,
                tmdb_id,
                tmdb_season,
            ]
        )
    return {"by_anilist": by_anilist, "by_mal": by_mal, "tvdb_members": tvdb_members}


# --------------------------------------------------------------------------- #
# Runtime cache (Kodi profile dir).
# --------------------------------------------------------------------------- #
def _cache_path():
    try:
        import xbmcvfs

        base = xbmcvfs.translatePath("special://profile/addon_data/%s/" % ADDON_ID)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".%s" % ADDON_ID)
    return os.path.join(base, "season_map.json")


def _log(msg, level=None):
    try:
        import xbmc

        xbmc.log("[AniListBingieHelper] season_map: %s" % msg, level or xbmc.LOGINFO)
    except Exception:
        pass


def _load():
    global _LOADED, _BY_ANILIST, _BY_MAL, _TVDB_MEMBERS, _META
    if _LOADED:
        return
    _LOADED = True
    try:
        with open(_cache_path(), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        _BY_ANILIST = raw.get("by_anilist") or {}
        _BY_MAL = raw.get("by_mal") or {}
        _TVDB_MEMBERS = raw.get("tvdb_members") or {}
        _META = raw.get("_meta") or {}
    except Exception:
        _BY_ANILIST, _BY_MAL, _TVDB_MEMBERS, _META = {}, {}, {}, {}


def _save(compact, sha):
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    payload = dict(compact)
    payload["_meta"] = {
        "source": "Fribb/anime-lists anime-list-full.json",
        "format": FORMAT,
        "sha": sha,
        "checked_at": int(time.time()),
        "anilist_keys": len(compact.get("by_anilist") or {}),
        "tvdb_series": len(compact.get("tvdb_members") or {}),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    os.replace(tmp, path)
    # Refresh in-memory view for this process.
    global _BY_ANILIST, _BY_MAL, _TVDB_MEMBERS, _META, _LOADED
    _BY_ANILIST = payload["by_anilist"]
    _BY_MAL = payload["by_mal"]
    _TVDB_MEMBERS = payload["tvdb_members"]
    _META = payload["_meta"]
    _LOADED = True


def _read_meta():
    try:
        with open(_cache_path(), "r", encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("_meta") or {}
    except Exception:
        return {}


def _stamp_checked_at(now):
    """Update only the checked_at timestamp in the existing cache file."""
    try:
        path = _cache_path()
        with open(path, "r", encoding="utf-8") as fh:
            cur = json.load(fh)
        cur.setdefault("_meta", {})["checked_at"] = now
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, separators=(",", ":"))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Online refresh (service-only; never called from the lookup path).
# --------------------------------------------------------------------------- #
def _latest_sha(session):
    resp = session.get(COMMITS_API, timeout=20, headers={"Accept": "application/vnd.github+json"})
    resp.raise_for_status()
    commits = resp.json()
    if commits:
        return commits[0].get("sha")
    return None


def refresh(force=False):
    """Update the cached map if upstream changed. Returns True if rewritten."""
    with _LOCK:
        meta = _read_meta()
        now = int(time.time())
        # A schema (FORMAT) bump invalidates the cache regardless of TTL/SHA so the
        # richer records are rebuilt on the next service tick.
        stale_format = int(meta.get("format") or 1) != FORMAT
        if force or stale_format:
            force = True
        if not force and meta and (now - int(meta.get("checked_at") or 0)) < CHECK_INTERVAL:
            return False  # TTL not elapsed -> don't even hit the network
        try:
            import requests
        except Exception:
            return False
        session = requests.Session()
        try:
            sha = _latest_sha(session)
        except Exception as exc:
            _log("commit check failed: %s" % exc)
            sha = None
        if not stale_format and sha and meta.get("sha") == sha:
            # Unchanged upstream: stamp checked_at so we wait another full TTL.
            _stamp_checked_at(now)
            return False
        try:
            resp = session.get(RAW_URL, timeout=120)  # gzip on the wire (~1.2 MB)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            _log("download failed: %s" % exc)
            return False
        compact = build_compact(data)
        if not compact.get("tvdb_members"):
            return False
        _save(compact, sha)
        _log("updated map: %d series, sha=%s" % (len(compact["tvdb_members"]), (sha or "?")[:8]))
        return True


def refresh_async():
    """Kick a non-blocking refresh (used by the background service)."""
    threading.Thread(target=refresh, name="anilist-season-map", daemon=True).start()


# --------------------------------------------------------------------------- #
# Lookups (read-only, offline).
# --------------------------------------------------------------------------- #
def available():
    _load()
    return bool(_TVDB_MEMBERS)


def lookup(anilist_id=None, mal_id=None):
    """Return (tvdb_id, tvdb_season) for an AniList/MAL id, or (None, None)."""
    _load()
    for value, table in ((anilist_id, _BY_ANILIST), (mal_id, _BY_MAL)):
        if value is not None and _intable(value):
            hit = table.get(str(int(value)))
            if hit:
                return hit[0], hit[1]
    return None, None


def tmdb_lookup(anilist_id=None, mal_id=None):
    """Return (tmdb_tv_id, tmdb_season) for an AniList/MAL id, or (None, None)."""
    _load()
    for value, table in ((anilist_id, _BY_ANILIST), (mal_id, _BY_MAL)):
        if value is not None and _intable(value):
            hit = table.get(str(int(value)))
            if hit and len(hit) >= 4:
                return hit[2], hit[3]
    return None, None


def members(tvdb_id):
    """Return franchise members for a TVDB series.

    Each member: {anilist, mal, season (tvdb), is_tv, tmdb_id, tmdb_season}.
    tmdb_id / tmdb_season may be None when Fribb carries no TMDB mapping.
    """
    _load()
    if tvdb_id is None or not _intable(tvdb_id):
        return []
    out = []
    for rec in _TVDB_MEMBERS.get(str(int(tvdb_id))) or []:
        try:
            out.append(
                {
                    "anilist": rec[0],
                    "mal": rec[1],
                    "season": int(rec[2]),
                    "is_tv": bool(rec[3]),
                    "tmdb_id": rec[4] if len(rec) > 4 else None,
                    "tmdb_season": rec[5] if len(rec) > 5 else None,
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    return out


def _intable(value):
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False
