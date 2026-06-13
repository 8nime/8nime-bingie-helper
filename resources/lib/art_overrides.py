# -*- coding: utf-8 -*-
"""Per-title artwork overrides for the More-Info 'Change artwork' button (G6).

AniList ships one cover + one banner per title, so the chooser lets the user pick
which image is used as the poster/fanart. Choices persist to addon_data and are
read by listitems._build_art. Loaded once per process; invalidated on write.
"""
import json
import os

ADDON_ID = "plugin.video.8nime.bingie.helper"
_CACHE = None


def _path():
    try:
        import xbmcvfs

        base = xbmcvfs.translatePath("special://profile/addon_data/%s/" % ADDON_ID)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".%s" % ADDON_ID)
    return os.path.join(base, "art_overrides.json")


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        with open(_path(), "r", encoding="utf-8") as fh:
            _CACHE = json.load(fh) or {}
    except Exception:
        _CACHE = {}
    return _CACHE


def get(mal_id):
    """Return the {'poster':..., 'fanart':...} override for a mal_id, or {}."""
    if not mal_id:
        return {}
    return _load().get(str(mal_id)) or {}


def set_art(mal_id, poster=None, fanart=None):
    """Persist a poster/fanart override for a mal_id. Returns True on success."""
    if not mal_id:
        return False
    data = dict(_load())
    entry = dict(data.get(str(mal_id)) or {})
    if poster:
        entry["poster"] = poster
    if fanart:
        entry["fanart"] = fanart
    if not entry:
        return False
    data[str(mal_id)] = entry
    path = _path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        return False
    global _CACHE
    _CACHE = data
    return True
