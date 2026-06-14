# -*- coding: utf-8 -*-
"""Boot service: sync AniList progress into the local O(1) store at Kodi start.

Registered via addon.xml `<extension point="xbmc.service" library="service.py"/>`.
On start it does one progress sync (when an AniList login exists) so the resume/Play
path is a pure local lookup with no network, then idles, re-syncing hourly and exiting
cleanly on Kodi shutdown. With no token it is a no-op (local-only users rely on local
completion marks).
"""
import xbmc

from resources.lib.auth import has_anilist_token
from resources.lib.api import AniListClient

_RESYNC_INTERVAL = 3600  # re-pull the AniList list hourly while Kodi runs


def sync_now():
    """One progress sync (guarded). Safe to call from boot, the resync loop, or login."""
    if not has_anilist_token():
        return 0
    try:
        count = AniListClient().sync_progress()
        xbmc.log("[8nime] progress sync: %d entries" % count, xbmc.LOGINFO)
        return count
    except Exception as exc:
        xbmc.log("[8nime] progress sync failed: %s" % exc, xbmc.LOGWARNING)
        return 0


def main():
    monitor = xbmc.Monitor()
    sync_now()  # once, as soon as Kodi opens
    while not monitor.abortRequested():
        if monitor.waitForAbort(_RESYNC_INTERVAL):
            break
        sync_now()


if __name__ == "__main__":
    main()
