# -*- coding: utf-8 -*-
import re
import time

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import season_map
from resources.lib.api import AniListClient
from resources.lib.constants import PLUGIN_URL
from resources.lib.franchise import collect_tv_franchise
from resources.lib import tmdb
from resources.lib.listitems import build_detail_item
from resources.lib.titles import title_for_media

ADDON = xbmcaddon.Addon()
MONITOR_CONTAINER = 17195
HOME_WINDOW = 10000
VIDEO_INFO_WINDOW = 12003
PLUGIN_PATH = PLUGIN_URL
AUTH_PROP = "AniListBingieHelper.HasToken"
ENRICHED_MAL_PROP = "AniListBingieHelper.EnrichedMalId"
TITLE_PROP = "AniListBingieHelper.Title"
ENRICHMENT_PROPS = (
    "AniList_Rating",
    "TMDb_Rating",
    "Status",
    "cast",
    "studio",
    "Studio",
    "Network",
    "Genre",
    "Creator",
    "Writer",
    ENRICHED_MAL_PROP,
    TITLE_PROP,
)


class AniListBingieService(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self._last_key = None
        self._pending_key = None
        self._client = AniListClient()

    def _infolabel(self, label):
        try:
            return xbmc.getInfoLabel(label)
        except Exception:
            return ""

    def _cond(self, condition):
        try:
            return xbmc.getCondVisibility(condition)
        except Exception:
            return False

    def _info_dialog_open(self):
        # Window.IsVisible is a boolean condition; must use getCondVisibility, not getInfoLabel.
        return self._cond("Window.IsVisible(movieinformation)") or self._cond(
            "Window.IsVisible(DialogVideoInfo.xml)"
        )

    def _active_window_ids(self):
        """Container 17195 lives on the info dialog window and on Home for hubs."""
        ids = []
        if self._info_dialog_open():
            for getter in ("getCurrentWindowDialogId", "getCurrentWindowId"):
                try:
                    wid = getattr(xbmcgui, getter)()
                    if wid and wid not in ids:
                        ids.append(wid)
                except Exception:
                    pass
            if VIDEO_INFO_WINDOW not in ids:
                ids.append(VIDEO_INFO_WINDOW)
        if HOME_WINDOW not in ids:
            ids.append(HOME_WINDOW)
        return ids

    def _window(self, window_id):
        try:
            return xbmcgui.Window(window_id)
        except Exception:
            return None

    def _mal_from_path(self, path):
        if not path or PLUGIN_PATH not in path:
            return None
        match = re.search(r"[?&]mal_id=(\d+)", path)
        if match:
            return int(match.group(1))
        match = re.search(r"[?&]tmdb_id=(\d+)", path)
        if match:
            return int(match.group(1))
        return None

    def _current_mal_id(self):
        if self._info_dialog_open():
            for label in (
                "ListItem.Property(mal_id)",
                "ListItem.UniqueID(mal)",
                "ListItem.Property(tmdb_id)",
                "ListItem.UniqueID(tmdb)",
            ):
                val = self._infolabel(label)
                if val.isdigit():
                    return int(val)
            path = self._infolabel("ListItem.Path") or self._infolabel("ListItem.FolderPath")
            mal_id = self._mal_from_path(path)
            if mal_id:
                return mal_id
            return None

        widget_id = self._infolabel("Window.Property(TMDbBingieHelper.WidgetContainer)")
        if widget_id.isdigit():
            base = f"Container({widget_id}).ListItem."
            for suffix in ("Property(mal_id)", "Property(tmdb_id)"):
                val = self._infolabel(f"{base}{suffix}")
                if val.isdigit():
                    return int(val)
            path = self._infolabel(f"{base}Path")
            mal_id = self._mal_from_path(path)
            if mal_id:
                return mal_id
        return None

    def _item_key(self):
        if self._info_dialog_open():
            return (
                "dialog",
                self._infolabel("ListItem.Property(mal_id)"),
                self._infolabel("ListItem.Property(tmdb_id)"),
                self._infolabel("ListItem.UniqueID(tmdb)"),
                self._infolabel("ListItem.Title"),
                self._infolabel("ListItem.Path"),
            )
        widget_id = self._infolabel("Window.Property(TMDbBingieHelper.WidgetContainer)")
        if widget_id.isdigit():
            base = f"Container({widget_id}).ListItem."
            return (
                "widget",
                widget_id,
                self._infolabel(f"{base}Property(mal_id)"),
                self._infolabel(f"{base}Property(tmdb_id)"),
                self._infolabel(f"{base}Label"),
            )
        return None

    def _update_container(self, li, window_id):
        try:
            win = self._window(window_id)
            if not win:
                return False
            ctrl = win.getControl(MONITOR_CONTAINER)
            ctrl.reset()
            ctrl.addItem(li)
            return True
        except Exception as exc:
            xbmc.log(
                f"[AniListBingieHelper] Monitor container {window_id} update failed: {exc}",
                xbmc.LOGWARNING,
            )
            return False

    def _clear_enrichment(self):
        for window_id in self._active_window_ids():
            try:
                win = self._window(window_id)
                if not win:
                    continue
                ctrl = win.getControl(MONITOR_CONTAINER)
                ctrl.reset()
                for prop in ENRICHMENT_PROPS:
                    win.clearProperty(prop)
            except Exception:
                pass

    def _sync_auth_property(self):
        from resources.lib.auth import has_anilist_token

        for window_id in (HOME_WINDOW,):
            try:
                win = self._window(window_id)
                if not win:
                    continue
                if has_anilist_token():
                    win.setProperty(AUTH_PROP, "1")
                else:
                    win.clearProperty(AUTH_PROP)
            except Exception:
                pass

    def _set_window_properties(self, li, mal_id, window_id):
        try:
            win = self._window(window_id)
            if not win:
                return
            for art_key in ("fanart", "fanart1", "fanart2", "landscape", "poster", "thumb"):
                art = li.getArt(art_key)
                if art:
                    win.setProperty(art_key, art)
            for prop in ENRICHMENT_PROPS:
                if prop == ENRICHED_MAL_PROP:
                    win.setProperty(prop, str(mal_id))
                    continue
                val = li.getProperty(prop)
                if val:
                    win.setProperty(prop, val)
        except Exception as exc:
            xbmc.log(
                f"[AniListBingieHelper] Window {window_id} property sync failed: {exc}",
                xbmc.LOGDEBUG,
            )

    def poll(self):
        key = self._item_key()
        if not key:
            if self._last_key is not None:
                self._clear_enrichment()
                self._last_key = None
                self._pending_key = None
            return
        if key == self._last_key:
            return

        if key != self._pending_key:
            self._pending_key = key

        mal_id = self._current_mal_id()
        if not mal_id:
            if self._info_dialog_open():
                xbmc.log(
                    "[AniListBingieHelper] Info dialog open but no mal_id on ListItem "
                    f"(title={self._infolabel('ListItem.Title')!r}, path={self._infolabel('ListItem.Path')!r})",
                    xbmc.LOGINFO,
                )
                self._last_key = key
            return

        xbmc.log(
            f"[AniListBingieHelper] Resolving mal_id={mal_id} for windows={self._active_window_ids()}",
            xbmc.LOGINFO,
        )
        media = self._client.get_media(mal_id=mal_id)
        if self._item_key() != key:
            return
        if not media:
            xbmc.log(f"[AniListBingieHelper] No media for mal_id={mal_id}", xbmc.LOGWARNING)
            return
        if int(media.get("idMal") or 0) != mal_id:
            return

        li = build_detail_item(media)
        if not li or self._item_key() != key:
            return

        display_title = title_for_media(media)
        if display_title and display_title != "Unknown":
            li.setLabel(display_title)
            li.setLabel2(display_title)
            li.setInfo("video", {"title": display_title})
            li.setProperty(TITLE_PROP, display_title)

        li.setProperty("mal_id", str(mal_id))
        li.setProperty("tmdb_id", str(mal_id))

        # Keep the info-dialog season count identical to the seasons browse view:
        # both derive from the same (aired-only) TV franchise chain.
        try:
            franchise = collect_tv_franchise(self._client, media)
        except Exception:
            franchise = []
        if franchise:
            # The headline season count MUST equal the seasons browse view
            # ("More Episodes"), which lists exactly the franchise groups. Raw
            # tmdb.aired_seasons() can diverge (TMDB may carry a season the
            # NYR-filtered franchise doesn't include, e.g. an announced S3),
            # which is what made the detail say "3 Seasons" while the browse
            # said 2. So the count is always len(franchise).
            total_seasons = len(franchise)
            total_eps = sum(int(e.get("episodes") or 0) for e in franchise)
            # Episode headline still prefers TMDB's per-season counts, but ONLY
            # for the seasons actually in the franchise (keeps it in sync).
            te = 0
            for group in franchise:
                gid = group.get("tmdb_id")
                gseason = group.get("tmdb_season")
                if not gid or not gseason:
                    te = 0
                    break
                try:
                    data = tmdb.get_season(gid, gseason) or {}
                except Exception:
                    te = 0
                    break
                te += len(data.get("episodes") or [])
            if te:
                total_eps = te
            li.setProperty("TotalSeasons", str(total_seasons))
            li.setProperty("n", str(total_seasons))
            if total_eps:
                li.setProperty("TotalEpisodes", str(total_eps))

        updated = False
        for window_id in self._active_window_ids():
            if self._update_container(li, window_id):
                updated = True
            self._set_window_properties(li, mal_id, window_id)

        if updated:
            creator = li.getProperty("Creator") or li.getProperty("Creator.1.name")
            network = li.getProperty("Network.1.Name") or li.getProperty("studio")
            xbmc.log(
                f"[AniListBingieHelper] Enriched mal_id={mal_id} creator={creator!r} network={network!r}",
                xbmc.LOGINFO,
            )
        else:
            xbmc.log(f"[AniListBingieHelper] Failed to update monitor container for mal_id={mal_id}", xbmc.LOGERROR)

        self._last_key = key

    def run(self):
        xbmc.log("[AniListBingieHelper] Service started", xbmc.LOGINFO)
        self._sync_auth_property()
        # Populate/refresh the TVDB season map online (background, TTL+SHA gated).
        season_map.refresh_async()
        last_map_kick = time.time()
        while not self.waitForAbort(0.35):
            try:
                self._sync_auth_property()
                self.poll()
                # refresh() self-throttles to CHECK_INTERVAL; this only re-arms it.
                if time.time() - last_map_kick > 12 * 3600:
                    last_map_kick = time.time()
                    season_map.refresh_async()
            except Exception as exc:
                xbmc.log(f"[AniListBingieHelper] Service poll error: {exc}", xbmc.LOGERROR)
        xbmc.log("[AniListBingieHelper] Service stopped", xbmc.LOGINFO)
