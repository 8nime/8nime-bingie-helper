# -*- coding: utf-8 -*-
"""Window-state side-effects that the deleted background monitor used to own.

There is NO poll loop. These are called on demand: once per plugin invocation
from the router bootstrap (auth state + a TTL-gated Fribb refresh), and after
script actions in default.py (auth + widget reload). Everything the monitor used
to side-load into Container(17195)/Home properties is now returned inline by each
view's own request (see enrichment.py / the details route).
"""
import os
import time

import xbmcgui

from resources.lib import season_map
from resources.lib.constants import WIDGET_RELOAD_PROP

HOME_WINDOW = 10000
AUTH_PROP = "AniListBingieHelper.HasToken"

_fribb_kicked = False


def _home():
    try:
        return xbmcgui.Window(HOME_WINDOW)
    except Exception:
        return None


def sync_auth_property():
    """Mirror AniList auth state into Window(Home).Property(AniListBingieHelper.HasToken).

    The skin gates the like/dislike buttons (group 701) and the login/logout label
    on this. The monitor used to keep it current; now the router sets it on each
    plugin call and default.py re-syncs it after a login/sync action.
    """
    from resources.lib.auth import has_anilist_token

    win = _home()
    if not win:
        return
    try:
        if has_anilist_token():
            win.setProperty(AUTH_PROP, "1")
        else:
            win.clearProperty(AUTH_PROP)
    except Exception:
        pass


def bump_widget_reload():
    """Write a fresh widget-reload token so widgets re-fetch (gap G4).

    Every widget URL embeds reload=$INFO[Window(Home).Property(
    TMDbBingieHelper.Widgets.Reload)]; changing the value busts Kodi's per-URL
    directory cache. Nothing ever set it before, so widgets never refreshed after
    a rating sync / login / cache clear. Use a monotonic-ish value (sub-second
    time) so even rapid successive calls change it.
    """
    win = _home()
    if not win:
        return
    try:
        win.setProperty(WIDGET_RELOAD_PROP, str(time.time()))
    except Exception:
        pass


def ensure_fribb_fresh():
    """One-shot, cheap-guarded kick of the Fribb season-map refresh (no loop).

    Guarded per-process AND by the cache file's mtime, so the hot browse path
    never parses the ~420 KB map or hits the network when it's already fresh; only
    a missing/stale cache spawns the (self-SHA-gating) async refresh.
    """
    global _fribb_kicked
    if _fribb_kicked:
        return
    _fribb_kicked = True
    try:
        path = season_map._cache_path()
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < season_map.CHECK_INTERVAL:
            return
    except Exception:
        pass
    try:
        season_map.refresh_async()
    except Exception:
        pass
