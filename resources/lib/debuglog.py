# -*- coding: utf-8 -*-
"""Versioned, toggleable debug tracing.

Instrumentation across the addon calls ``dbg(...)``. It is a no-op (one cached
settings read) unless the ``debug_logging`` setting is on, so it stays in the code
permanently AND keeps kodi.log clean in normal use. When on, it appends timestamped
lines to ``8nime.debug`` in the addon profile dir (a dedicated trace file, not
kodi.log) -- so any future "why is X slow/empty" is one settings toggle away, no code
edits or redeploys.
"""
import os
import time

import xbmcaddon
import xbmcvfs

from resources.lib.constants import ADDON_ID

_ADDON = xbmcaddon.Addon()


def enabled():
    try:
        return _ADDON.getSetting("debug_logging") == "true"
    except Exception:
        return False


def _path():
    try:
        base = xbmcvfs.translatePath("special://profile/addon_data/%s/" % ADDON_ID)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".%s" % ADDON_ID)
    return os.path.join(base, "8nime.debug")


def dbg(msg):
    """Append a timestamped trace line to 8nime.debug when debug_logging is on."""
    if not enabled():
        return
    try:
        line = "%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
        path = _path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass
