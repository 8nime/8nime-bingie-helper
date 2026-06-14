# -*- coding: utf-8 -*-
"""Shared on-disk JSON store helpers: profile-dir resolution + crash-safe read/write.

The progress/resume stores are written from more than one process (the boot service
vs. the per-play babysitter launched via RunScript), and a plain ``open(w)`` truncates
the file before ``json.dump`` finishes -- a crash or kill mid-write would corrupt it.

  * ``atomic_write_json`` writes to a temp file in the same directory and ``os.replace``s
    it into place (atomic on the same filesystem), so a reader never sees a half-written
    file.
  * ``read_json`` renames a corrupt file aside (``<path>.corrupt``) and logs, instead of
    silently discarding it -- so a single bad write never wipes the user's watch state
    without a trace.
"""
import json
import os

import xbmc
import xbmcvfs

from resources.lib.constants import ADDON_ID


def profile_dir():
    """The add-on's userdata profile dir (falls back to ~/.<addon_id> off-Kodi)."""
    try:
        return xbmcvfs.translatePath("special://profile/addon_data/%s/" % ADDON_ID)
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".%s" % ADDON_ID)


def store_path(filename):
    return os.path.join(profile_dir(), filename)


def read_json(path, default=None):
    """Load JSON from ``path``. Missing -> ``default``. Corrupt -> rename to
    ``<path>.corrupt`` (+ log) and return ``default`` so the bad file is recoverable
    rather than silently lost."""
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError) as exc:
        try:
            os.replace(path, path + ".corrupt")
        except OSError:
            pass
        try:
            xbmc.log("[8nime] corrupt store %s (%s) -> kept as .corrupt" % (path, exc),
                     xbmc.LOGWARNING)
        except Exception:
            pass
        return default


def atomic_write_json(path, data):
    """Write ``data`` as JSON to ``path`` atomically (temp file + ``os.replace``).
    Best-effort: logs and swallows on failure so a write error never breaks playback."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.tmp.%d" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            xbmc.log("[8nime] failed to write store %s (%s)" % (path, exc), xbmc.LOGWARNING)
        except Exception:
            pass
