# -*- coding: utf-8 -*-
from urllib.parse import urlencode

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.api import AniListClient, media_type_from_tmdb
from resources.lib.constants import PLUGIN_URL
from resources.lib.episodes import (
    signature,
    streaming_covers,
    thumb_for_episode,
    thumbnails_from_media,
)
from resources.lib.franchise import (
    collect_tv_franchise,
    franchise_entry_for_season,
    franchise_show_title,
    iter_cours,
)
from resources.lib.listitems import (
    build_cast_item,
    build_crew_item,
    build_detail_item,
    build_episode_item,
    build_item,
    build_items,
    build_poster_item,
    build_review_item,
    build_season_item,
    build_video_item,
    _title,
)
from resources.lib.playback import (
    PLAYBACK_OTAKU,
    get_playback_key,
    log_missing_plugin,
    resolve_play_path,
)
from resources.lib import season_map, tmdb


class InfoHandler:
    def __init__(self, handle, params):
        self.handle = handle
        self.params = params
        self.client = AniListClient()
        self.cacheonly = self.params.get("cacheonly", "").lower() == "true"

    def _mal_id(self):
        return self.client.resolve_mal_id(self.params)

    def _limit(self):
        try:
            return int(self.params.get("limit") or self.params.get("length") or 20)
        except (TypeError, ValueError):
            return 20

    def _finish(self, items, content="videos", folders=None):
        folders = folders or set()
        for idx, li in enumerate(items):
            xbmcplugin.addDirectoryItem(self.handle, li.getPath(), li, idx in folders)
        xbmcplugin.setContent(self.handle, content)
        xbmcplugin.endOfDirectory(self.handle, succeeded=True)
        return True

    def _media(self):
        mal_id = self._mal_id()
        if not mal_id:
            return None
        return self.client.get_media(mal_id=mal_id)

    def details(self):
        media = self._media()
        if not media:
            xbmcplugin.endOfDirectory(self.handle, succeeded=self.cacheonly)
            return True
        items = []
        detail = build_detail_item(media)
        if detail:
            items.append(detail)
        folders = set()
        if not self.cacheonly:
            mal_id = media.get("idMal")
            is_movie = (media.get("format") or "").upper() in ("MOVIE", "ONE_SHOT")
            if not is_movie and mal_id:
                items.append(
                    build_season_item(mal_id, _title(media), media.get("episodes") or 0)
                )
                folders.add(1)
        content = "movies" if (media.get("format") or "").upper() == "MOVIE" else "tvshows"
        return self._finish(items, content, folders)

    def cast(self):
        media = self._media()
        if not media:
            return self._finish([], "actors")
        items = []
        for edge in (media.get("characters") or {}).get("edges") or []:
            role = edge.get("role") or ""
            char_node = edge.get("node") or {}
            char_name = (char_node.get("name") or {}).get("userPreferred") or ""
            for va in edge.get("voiceActors") or []:
                li = build_cast_item(va, char_name or role)
                if li:
                    items.append(li)
        return self._finish(items[: self._limit()], "actors")

    def crew(self):
        media = self._media()
        if not media:
            return self._finish([], "actors")
        items = []
        for edge in (media.get("staff") or {}).get("edges") or []:
            node = edge.get("node") or {}
            li = build_crew_item(node, edge.get("role") or "")
            if li:
                items.append(li)
        for edge in (media.get("studios") or {}).get("edges") or []:
            node = edge.get("node") or {}
            if node.get("name"):
                fake = {"id": node.get("id"), "name": {"userPreferred": node["name"]}, "image": {}}
                li = build_crew_item(fake, "Studio")
                if li:
                    items.append(li)
        return self._finish(items[: self._limit()], "actors")

    def videos(self):
        media = self._media()
        if not media:
            return self._finish([], "videos")
        li = build_video_item(media)
        return self._finish([li] if li else [], "videos")

    def recommendations(self):
        mal_id = self._mal_id()
        if not mal_id:
            return self._finish([])
        media, _ = self.client.get_recommendations(mal_id, per_page=self._limit())
        return self._finish(build_items(media))

    def reviews(self):
        mal_id = self._mal_id()
        if not mal_id:
            return self._finish([])
        reviews, _ = self.client.get_reviews(mal_id, per_page=self._limit())
        items = []
        for rev in reviews:
            li = build_review_item(rev)
            if li:
                items.append(li)
        if not items:
            media = self.client.get_media(mal_id=mal_id)
            if media and media.get("description"):
                items.append(
                    build_review_item(
                        {
                            "summary": "Synopsis",
                            "body": media.get("description"),
                            "user": {"name": "AniList"},
                        }
                    )
                )
        return self._finish(items, "videos")

    def posters(self):
        media = self._media()
        if not media:
            return self._finish([], "images")
        items = []
        li = build_poster_item(media, "Cover")
        if li:
            items.append(li)
        banner = media.get("bannerImage")
        if banner:
            banner_item = build_poster_item({"coverImage": {"extraLarge": banner}, "idMal": media.get("idMal")}, "Banner")
            if banner_item:
                items.append(banner_item)
        return self._finish(items, "images")

    def _episode_total(self, media):
        total = media.get("episodes")
        if total:
            return int(total)
        status = (media.get("status") or "").upper()
        next_ep = int((media.get("nextAiringEpisode") or {}).get("episode") or 0)
        if next_ep:
            return next_ep
        if status == "RELEASING":
            return 24
        return 12

    def _franchise(self, media=None):
        media = media or self._media()
        if not media:
            return []
        return collect_tv_franchise(self.client, media)

    def _build_episode_list(
        self, media, mal_id=None, season=1, show_title=None, season_offset=0,
        suppress=False, tmdb_id=None, tmdb_season=None,
    ):
        mal_id = mal_id or media.get("idMal")
        if not mal_id or not media:
            return []
        season = int(season or 1)
        total = self._episode_total(media)
        cour_title = _title(media)
        title = show_title or cour_title
        if total < 1:
            return []

        # Only list episodes that have actually AIRED. AniList's
        # nextAiringEpisode.episode is the first NOT-yet-aired episode, so a
        # RELEASING cour has aired = next_ep - 1; FINISHED cours carry no
        # nextAiringEpisode and list the full total. Without this the planned
        # (unaired) episodes were shown.
        next_ep = int((media.get("nextAiringEpisode") or {}).get("episode") or 0)
        last = min(total, (next_ep - 1) if next_ep else total)
        if last < 1:
            return []

        # Primary source for stills + episode names/plots is TMDB (real per-episode
        # art for anime, which AniList lacks for many seasons), indexed by the
        # season-local episode number (season_offset + local ep). For a standalone
        # (non-franchise) show, resolve the mapping straight from the Fribb map.
        if not tmdb_id:
            tmdb_id, tmdb_season = season_map.tmdb_lookup(media.get("id"), mal_id)
        tmdb_eps = {}
        if tmdb_id and tmdb_season:
            try:
                tmdb_eps = tmdb.episode_stills(tmdb_id, tmdb_season)
            except Exception:
                tmdb_eps = {}

        # AniList streamingEpisodes fallback: numbered per SEASON (restarting each
        # season) with the season's full listing stapled onto every cour. Pick the
        # offset that actually carries stills, else drop to show art.
        thumbs = {} if suppress else thumbnails_from_media(media)
        offset = 0
        if thumbs:
            if streaming_covers(thumbs, total, season_offset):
                offset = season_offset
            elif streaming_covers(thumbs, total, 0):
                offset = 0
            else:
                thumbs = {}

        items = []
        for ep in range(1, last + 1):
            meta = tmdb_eps.get(season_offset + ep) or {}
            thumb = meta.get("still") or thumb_for_episode(thumbs, ep, offset)
            items.append(
                build_episode_item(
                    mal_id,
                    ep,
                    title,
                    total,
                    season=season,
                    media=media,
                    thumb_url=thumb,
                    play_title=cour_title,
                    ep_name=meta.get("name"),
                    ep_plot=meta.get("plot"),
                    ep_aired=meta.get("aired"),
                )
            )
        return items

    def _tmdb_season_count(self, group):
        """TMDB episode count for a season group, or 0 when unmapped/unavailable."""
        tmdb_id = group.get("tmdb_id")
        tmdb_season = group.get("tmdb_season")
        if not tmdb_id or not tmdb_season:
            return 0
        try:
            data = tmdb.get_season(tmdb_id, tmdb_season) or {}
            return len(data.get("episodes") or [])
        except Exception:
            return 0

    def _stream_plan(self, franchise):
        """Per-cour streamingEpisodes plan: (offsets, suppressed).

        offsets[id(cour)] = episodes of prior cours WITHIN THE SAME SEASON, because
        AniList restarts streamingEpisodes numbering at each season; the offset must
        reset on every season boundary, not accumulate across the franchise.

        suppressed holds cours whose season reuses an EARLIER season's listing
        verbatim (AniList often staples season 1's Crunchyroll listing onto every
        entry, so later seasons carry no real stills of their own). Those seasons
        fall back to show art instead of displaying wrong-season images.
        """
        offsets = {}
        suppressed = set()
        seen_sigs = set()
        for group in franchise:
            cours = group.get("cours") or []
            sig = ()
            for cour in cours:
                s = signature(thumbnails_from_media(cour.get("media") or {}))
                if s:
                    sig = s
                    break
            duplicate = bool(sig) and sig in seen_sigs
            if sig:
                seen_sigs.add(sig)
            running = 0
            for cour in cours:
                offsets[id(cour)] = running
                running += int(cour.get("episodes") or 0)
                if duplicate:
                    suppressed.add(id(cour))
        return offsets, suppressed

    def flatseasons(self):
        """All franchise episodes in one flat list across cours."""
        media = self._media()
        if not media:
            return self._finish([], "episodes")
        franchise = self._franchise(media)
        if not franchise:
            items = self._build_episode_list(media)
            return self._finish(items, "episodes")
        show_title = franchise_show_title(franchise, _title)
        offsets, suppressed = self._stream_plan(franchise)
        items = []
        for cour in iter_cours(franchise):
            cour_media = cour.get("media") or media
            items.extend(
                self._build_episode_list(
                    cour_media,
                    mal_id=cour.get("mal_id") or cour_media.get("idMal"),
                    season=cour.get("season"),
                    show_title=show_title,
                    season_offset=offsets.get(id(cour), 0),
                    suppress=id(cour) in suppressed,
                    tmdb_id=cour.get("tmdb_id"),
                    tmdb_season=cour.get("tmdb_season"),
                )
            )
        return self._finish(items, "episodes")

    def seasons(self):
        media = self._media()
        if not media or not media.get("idMal"):
            return self._finish([], "seasons")
        franchise = self._franchise(media)
        if not franchise:
            li = build_season_item(
                media["idMal"],
                _title(media),
                self._episode_total(media),
            )
            return self._finish([li] if li else [], "seasons", {0})
        show_title = franchise_show_title(franchise, _title)
        items = []
        folders = set()
        for group in franchise:
            season = group.get("season") or 1
            cour_media = group.get("media") or media
            # Prefer TMDB's per-season episode count (taxonomy source); fall back to
            # summing the AniList cours (split-cour seasons add their parts).
            season_total = self._tmdb_season_count(group)
            if not season_total:
                season_total = sum(
                    self._episode_total(c.get("media") or {}) for c in group.get("cours") or []
                ) or self._episode_total(cour_media)
            li = build_season_item(
                group.get("mal_id") or cour_media.get("idMal"),
                show_title,
                season_total,
                season=season,
                label=f"Season {season}",
                media=cour_media,
            )
            items.append(li)
            folders.add(len(items) - 1)
        return self._finish(items, "seasons", folders)

    def episodes(self):
        mal_id = self._mal_id()
        if not mal_id:
            return self._finish([], "episodes")
        media = self.client.get_media(mal_id=mal_id)
        if not media:
            return self._finish([], "episodes")
        franchise = self._franchise(media)
        season_param = self.params.get("season")
        if franchise and season_param:
            group = franchise_entry_for_season(franchise, season_param)
            if group:
                show_title = franchise_show_title(franchise, _title)
                offsets, suppressed = self._stream_plan(franchise)
                items = []
                # A season may aggregate several cours (split cours). Each cour
                # keeps its own mal_id + local 1..N numbering so playback resolves
                # correctly; the still thumbnail uses a season-local offset so the
                # season's streamingEpisodes listing indexes correctly.
                for cour in group.get("cours") or []:
                    cour_media = cour.get("media") or media
                    items.extend(
                        self._build_episode_list(
                            cour_media,
                            mal_id=cour.get("mal_id") or cour_media.get("idMal"),
                            season=cour.get("season"),
                            show_title=show_title,
                            season_offset=offsets.get(id(cour), 0),
                            suppress=id(cour) in suppressed,
                            tmdb_id=cour.get("tmdb_id"),
                            tmdb_season=cour.get("tmdb_season"),
                        )
                    )
                return self._finish(items, "episodes")
        items = self._build_episode_list(media, mal_id)
        return self._finish(items, "episodes")

    def collection(self):
        media = self._media()
        if not media:
            return self._finish([])
        items = []
        for edge in (media.get("relations") or {}).get("edges") or []:
            rel_media = edge.get("node")
            if rel_media and rel_media.get("idMal"):
                li = build_item(rel_media)
                if li:
                    items.append(li)
        return self._finish(items[: self._limit()])

    def relations(self):
        return self.collection()

    def trakt_upnext(self):
        mal_id = self._mal_id()
        if not mal_id:
            return self._finish([], "episodes")
        media = self.client.get_media(mal_id=mal_id)
        if not media:
            return self._finish([], "episodes")
        franchise = self._franchise(media)
        show_title = franchise_show_title(franchise, _title) if franchise else _title(media)
        if franchise:
            for cour in iter_cours(franchise):
                cour_mal = cour.get("mal_id")
                cour_media = cour.get("media") or {}
                total = self._episode_total(cour_media)
                progress = self.client.get_progress(cour_mal)
                next_ep = progress + 1
                if total and next_ep > total:
                    continue
                if not total and next_ep < 1:
                    next_ep = 1
                next_ep = max(1, next_ep)
                li = build_episode_item(
                    cour_mal,
                    next_ep,
                    show_title,
                    total,
                    season=cour.get("season") or 1,
                    play_title=_title(cour_media),
                )
                return self._finish([li] if li else [], "episodes")
        progress = self.client.get_progress(mal_id)
        next_ep = max(1, progress + 1)
        total = media.get("episodes") or next_ep
        if next_ep > total and total:
            next_ep = 1
        li = build_episode_item(mal_id, next_ep, show_title, total)
        return self._finish([li] if li else [], "episodes")

    def play(self):
        """Resolve playback through the configured plugin at click time."""
        log_missing_plugin()
        mal_id = self._mal_id()
        media = self._media() if mal_id else None
        episode = self.params.get("episode")
        title = self.params.get("title") or (_title(media) if media else "")
        tmdb_type = (self.params.get("tmdb_type") or "").lower()
        is_movie = tmdb_type == "movie" or (media and (media.get("format") or "").upper() in ("MOVIE", "ONE_SHOT"))

        path = resolve_play_path(
            media=media,
            mal_id=mal_id,
            episode=episode,
            title=title,
            is_movie=is_movie,
        )
        if not path:
            # Don't fail silently — tell the user why nothing played (no configured
            # source / unmapped title / missing plugin), instead of a dead click.
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
            xbmcgui.Dialog().notification(
                "8nime", "No playback source available for this title.",
                xbmcgui.NOTIFICATION_WARNING, 4000)
            return False

        # Otaku resolves to a playable endpoint (plugin://.../play[/_movie]) that
        # Kodi can redirect-to-play via setResolvedUrl. Search-based backends
        # (WatchNixtoons2 / Fanime) instead return a results DIRECTORY, which
        # setResolvedUrl can't play ("nothing happens") — open it so the user
        # picks a source.
        if get_playback_key() == PLAYBACK_OTAKU:
            xbmcplugin.setResolvedUrl(self.handle, True, xbmcgui.ListItem(path=path))
            return True

        # Search-based backend (WNT2/Fanime): we can't resolve+play directly, only
        # open its search results. Tell the user a search launched (the click
        # otherwise feels dead). NOTE: whether the backend then finds/plays the
        # title happens after this handoff and is outside our visibility — only
        # Otaku resolves in-process and surfaces its own playback errors.
        xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
        backend = {"watchnixtoons2": "WatchNixtoons2", "fanime_f": "Fanime"}.get(
            get_playback_key(), "the configured source")
        xbmcgui.Dialog().notification(
            "8nime", "Searching {0}…".format(backend), xbmcgui.NOTIFICATION_INFO, 3000)
        xbmc.executebuiltin('ActivateWindow(Videos,{0},return)'.format(path))
        return True

    def stars_in_movies(self):
        return self._staff_media(character=True, movie_only=True)

    def stars_in_tvshows(self):
        return self._staff_media(character=True, movie_only=False)

    def crew_in_movies(self):
        return self._staff_media(character=False, movie_only=True)

    def crew_in_tvshows(self):
        return self._staff_media(character=False, movie_only=False)

    def crew_in_both(self):
        staff_id = self.params.get("tmdb_id")
        filter_key = (self.params.get("filter_key") or "").lower()
        filter_value = (self.params.get("filter_value") or "").lower()
        if staff_id and str(staff_id).isdigit():
            character = filter_value == "cast"
            if filter_key == "job" and filter_value == "creator":
                character = False
            items, _ = self.client.get_staff_media(
                int(staff_id),
                character=character,
                per_page=self._limit(),
            )
            if not items and not character:
                items, _ = self.client.get_staff_media(
                    int(staff_id),
                    character=True,
                    per_page=self._limit(),
                )
            return self._finish(build_items(items))
        # No staff id (the live-enriched info dialog only carries the name): look
        # the person up by name and return their credits, rather than searching
        # media titles for a person's name (which finds nothing).
        query = self.params.get("query", "")
        if query:
            items, _ = self.client.get_staff_media_by_name(query, per_page=self._limit())
            return self._finish(build_items(items))
        return self._finish([])

    def _staff_media(self, character=True, movie_only=False):
        staff_id = self.params.get("tmdb_id")
        if not staff_id or not str(staff_id).isdigit():
            return self._finish([])
        items, _ = self.client.get_staff_media(int(staff_id), character=character, per_page=self._limit())
        if movie_only:
            items = [m for m in items if (m.get("format") or "").upper() in ("MOVIE", "ONE_SHOT")]
        else:
            items = [m for m in items if (m.get("format") or "").upper() not in ("MOVIE", "ONE_SHOT")]
        return self._finish(build_items(items))

    def discover_extended(self):
        """Handle studio/year discover params from patched skin paths."""
        tmdb_type = self.params.get("tmdb_type", "tv")
        media_type, formats = media_type_from_tmdb(tmdb_type)
        variables = {"type": media_type, "page": 1, "perpage": self._limit()}
        if formats:
            variables["format"] = formats

        studio = (
            self.params.get("with_studio")
            or self.params.get("with_companies")
            or self.params.get("with_networks")
        )
        if studio:
            media, _ = self.client.browse_studio(studio, media_type, formats, per_page=self._limit())
            return self._finish(build_items(media))

        year = (
            self.params.get("primary_release_year")
            or self.params.get("first_air_date_year")
            or self.params.get("year")
        )
        if year:
            variables["year"] = f"{year}%"
            media, _ = self.client.browse(variables)
            return self._finish(build_items(media))

        return None
