# -*- coding: utf-8 -*-
"""TMDB client: per-episode stills + season taxonomy.

Division of labour in this addon:
  * AniList -> discovery (browse/search) and rich metadata (cast, studio, score,
    trailer, genres, synopsis).
  * TMDB    -> the two things AniList is weak at for anime: correct *season
    grouping* and real *per-episode still images*.
  * Fribb map (season_map) -> the AniList/MAL <-> TMDB bridge (themoviedb tv id
    + per-entry tmdb season number).

Key handling: the TMDB v3 key is embedded but obfuscated (not a greppable
literal) so the helper stays self-contained -- no runtime coupling to other
addons. Override with the `tmdb_api_key` setting if you prefer your own.

Network only happens while building a detail/season view (a deliberate user
action), and every response is disk-cached for two weeks, so the browse/search
path never touches TMDB.
"""
import base64
import hashlib
import json
import os
import threading
import time

ADDON_ID = "plugin.video.8nime.bingie.helper"
API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
CACHE_TTL = 14 * 24 * 3600
_MIN_INTERVAL = 0.12

_LOCK = threading.Lock()
_LAST_CALL = [0.0]
_SESSION = [None]
_KEY = [None]
_MEM = {}


# --------------------------------------------------------------------------- #
# Key + low-level plumbing
# --------------------------------------------------------------------------- #
# Default TMDB v3 key (read-only, rate-limited, shared with the TMDb helper
# addons). base64 so it isn't a greppable literal, per the module docstring.
# Override via the `tmdb_api_key` setting or the TMDB_API_KEY env var.
_DEFAULT_KEY = "NGYxMzA3MmE5OTczOWQwNzgwZjM3YTUyNGMxNTk0MWQ="


def _api_key():
    if _KEY[0]:
        return _KEY[0]
    key = ""
    try:
        import xbmcaddon

        key = (xbmcaddon.Addon().getSetting("tmdb_api_key") or "").strip()
    except Exception:
        key = ""
    if not key:
        key = os.environ.get("TMDB_API_KEY", "")
    if not key:
        try:
            key = base64.b64decode(_DEFAULT_KEY).decode("ascii")
        except Exception:
            key = ""
    _KEY[0] = key
    return _KEY[0]


def _log(msg, level=None):
    try:
        import xbmc

        xbmc.log("[AniListBingieHelper] tmdb: %s" % msg, level or xbmc.LOGDEBUG)
    except Exception:
        pass


def _session():
    if _SESSION[0] is None:
        import requests

        _SESSION[0] = requests.Session()
    return _SESSION[0]


def _throttle():
    now = time.time()
    wait = _MIN_INTERVAL - (now - _LAST_CALL[0])
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[0] = time.time()


# --------------------------------------------------------------------------- #
# Disk cache (long TTL; TMDB episode data is effectively static)
# --------------------------------------------------------------------------- #
def _cache_dir():
    try:
        import xbmcvfs

        base = xbmcvfs.translatePath("special://profile/addon_data/%s/tmdb/" % ADDON_ID)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".%s" % ADDON_ID, "tmdb")
    return base


def _cache_path(key):
    return os.path.join(_cache_dir(), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")


def _cache_get(key):
    hit = _MEM.get(key)
    now = time.time()
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    path = _cache_path(key)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if now - float(payload.get("ts") or 0) < CACHE_TTL:
            _MEM[key] = (payload["ts"], payload["data"])
            return payload["data"]
    except Exception:
        pass
    return None


def _cache_put(key, data):
    _MEM[key] = (time.time(), data)
    try:
        os.makedirs(_cache_dir(), exist_ok=True)
        path = _cache_path(key)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"ts": time.time(), "data": data}, fh, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        pass


def _get(path, params=None):
    """GET {API}{path}; cached. Returns parsed JSON dict or None."""
    params = dict(params or {})
    params["api_key"] = _api_key()
    cache_key = path + "?" + "&".join("%s=%s" % (k, params[k]) for k in sorted(params) if k != "api_key")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        with _LOCK:
            _throttle()
            resp = _session().get(API + path, params=params, timeout=20)
        if resp.status_code == 404:
            _cache_put(cache_key, {})  # negative-cache misses
            return {}
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        _log("request failed %s: %s" % (path, exc))
        return None
    _cache_put(cache_key, data)
    return data


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def get_tv(tmdb_id):
    """Show-level payload (name, number_of_seasons, seasons[])."""
    if not tmdb_id:
        return None
    return _get("/tv/%d" % int(tmdb_id)) or None


def get_season(tmdb_id, season_number):
    """Season payload with episodes[] (each: episode_number, name, overview,
    still_path, air_date)."""
    if not tmdb_id or season_number is None:
        return None
    return _get("/tv/%d/season/%d" % (int(tmdb_id), int(season_number))) or None


def image_url(path, size="w780"):
    if not path:
        return None
    return "%s/%s%s" % (IMG, size, path)


def still_url(path, size="w300"):
    return image_url(path, size)


def episode_stills(tmdb_id, season_number, size="w300"):
    """Return {episode_number: {still, name, plot, aired}} for a TMDB season."""
    season = get_season(tmdb_id, season_number)
    out = {}
    if not season:
        return out
    for ep in season.get("episodes") or []:
        num = ep.get("episode_number")
        if not isinstance(num, int):
            continue
        out[num] = {
            "still": still_url(ep.get("still_path"), size),
            "name": ep.get("name") or "",
            "plot": ep.get("overview") or "",
            "aired": ep.get("air_date") or "",
        }
    return out


def aired_seasons(tmdb_id, today=None):
    """Regular seasons (season_number >= 1) that have already started airing.

    A season counts as aired when it has an air_date in the past; seasons with no
    air_date but with episode_count > 0 are included (older/loosely dated shows),
    while clearly future seasons (air_date > today) are excluded -- this is how we
    avoid counting an announced-but-unaired season.
    """
    tv = get_tv(tmdb_id)
    if not tv:
        return []
    today = today or time.strftime("%Y-%m-%d")
    out = []
    for s in tv.get("seasons") or []:
        if (s.get("season_number") or 0) < 1:
            continue
        air = s.get("air_date") or ""
        if air and air > today:
            continue
        if not air and not (s.get("episode_count") or 0):
            continue
        out.append(s)
    return out
