# -*- coding: utf-8 -*-
import re
from urllib.parse import urlencode, quote_plus

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import resume, progress, debuglog
from resources.lib.api import AniListClient, media_type_from_tmdb
from resources.lib.constants import ADDON_ID, PLUGIN_URL
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
    PLAYBACK_WATCHNIXTOONS2,
    PLAYBACK_FANIME_F,
    get_playback_key,
    log_missing_plugin,
    resolve_play_path,
)
from resources.lib import season_map, tmdb, wnt2, fanimef, identity, franchise

# A trailing season/part/cour marker on a cour title ("X Season 2", "X 2nd Season
# Part II", "X Cour 2"). Stripped to recover the base series name for searching.
_SEASON_SUFFIX_RE = re.compile(
    r"\s+(?:season\s+\d+|\d+(?:st|nd|rd|th)\s+season|cour\s+\d+|part\s+(?:\d+|[ivxlc]+))"
    r"(?:\s+part\s+(?:\d+|[ivxlc]+))?\s*$",
    re.IGNORECASE,
)


def _base_series_title(title):
    """The base series name with a trailing season/part marker removed, or None
    when there's no marker (so callers only add a genuinely-different base)."""
    if not title:
        return None
    base = _SEASON_SUFFIX_RE.sub("", title).strip()
    return base if base and base.lower() != title.lower() else None


_ADDON = xbmcaddon.Addon()


def _sort_descending():
    """Display order for the seasons list + episode lists in More Info.

    Controlled by the `sort_order` setting; defaults to newest-first (desc) so the
    latest season/episode sits at the top of the list. Anything other than `asc`
    is treated as desc (matches the settings.xml default)."""
    return (_ADDON.getSetting("sort_order") or "desc").strip().lower() != "asc"


def _ordered(items):
    """Apply the configured display order to an already-ascending item list."""
    return items[::-1] if _sort_descending() else items


class InfoHandler:
    def __init__(self, handle, params):
        self.handle = handle
        self.params = params
        self.client = AniListClient()
        self.cacheonly = self.params.get("cacheonly", "").lower() == "true"

    def _mal_id(self):
        # tmdb_id-aware: inbound calls may carry a real/surrogate tmdb_id (skin
        # buttons, the 17195 details path) instead of mal_id; identity reverse-maps
        # it. mal_id still wins when present; query/anilist_id fall back.
        return identity.resolve_mal_id(self.params, self.client)

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
        self._add_sort_methods(content)
        # cacheToDisc=False: Kodi caches plugin listings to disc by default and
        # serves the stale copy on re-navigation, which masks sort-method/data
        # changes (a listing built with only NONE keeps showing "Unsorted" with no
        # working Sort menu). The helper already caches AniList/TMDB at the data
        # layer, so re-running the route is cheap.
        xbmcplugin.endOfDirectory(self.handle, succeeded=True, cacheToDisc=False)
        return True

    def _add_sort_methods(self, content):
        """Register native Kodi sort methods so the full-screen browse owns ordering.

        A bare SORT_METHOD_NONE is honored for most content but IGNORED for
        episode content -- Kodi's video window force-sorts episodes by number. So
        for episodes we expose the real native methods: "Date added" (mapped from
        each episode's air date) defaults to newest-first, with Episode and Title
        also offered; Kodi remembers the chosen sort + direction per view. Other
        listings (seasons, cast, ...) keep insertion order via NONE.
        """
        if content == "episodes":
            # NONE first => default = the helper's emit order (newest-first via
            # _ordered), the same way the seasons list defaults newest-first. Kodi
            # has no "descending episode" default to register, so relying on a
            # native method as default lands oldest-first ("inverted"). Episode/Date
            # remain as drawer options the user can switch to (Kodi remembers).
            methods = (
                xbmcplugin.SORT_METHOD_NONE,
                xbmcplugin.SORT_METHOD_EPISODE,
                xbmcplugin.SORT_METHOD_DATEADDED,
                xbmcplugin.SORT_METHOD_LABEL,
            )
        elif content == "seasons":
            # NONE first keeps the helper's newest-first emit order as the default;
            # Year/Label give Kodi's sort drawer real options to switch between.
            methods = (
                xbmcplugin.SORT_METHOD_NONE,
                xbmcplugin.SORT_METHOD_VIDEO_YEAR,
                xbmcplugin.SORT_METHOD_LABEL,
            )
        else:
            methods = (xbmcplugin.SORT_METHOD_NONE,)
        for method in methods:
            xbmcplugin.addSortMethod(self.handle, method)

    def _media(self):
        mal_id = self._mal_id()
        if not mal_id:
            return None
        return self.client.get_media(mal_id=mal_id)

    def details(self):
        debuglog.dbg("details START mal=%s cacheonly=%s" % (self.params.get("mal_id"), self.cacheonly))
        media = self._media()
        if not media:
            xbmcplugin.endOfDirectory(self.handle, succeeded=self.cacheonly)
            return True
        is_movie = (media.get("format") or "").upper() in ("MOVIE", "ONE_SHOT")
        detail = build_detail_item(media)
        items = [detail] if detail else []
        folders = set()
        # On-list / rating state for the favourite + like/dislike buttons. Set on
        # EVERY load (incl. cacheonly): the skin's 17195 detail loader only ever
        # calls details with cacheonly=true, so gating this behind a live load left
        # the buttons permanently in their default ("Add to Favorite") state. The
        # PLANNING/MediaList reads are cached, and a toggle busts the cache + bumps
        # the widget-reload token so 17195 re-queries and the label/icon flip.
        if detail and self.client.has_token() and media.get("id"):
            state = self.client.list_state(media["id"])
            detail.setProperty("OnMyList", "true" if state.get("planning") else "")
            detail.setProperty("MyRating", state.get("rating") or "")
        if detail and not is_movie:
            latest = self._latest_episode(media)
            if latest:
                detail.setProperty("LatestEpisode", str(latest))
        # The seasons enumeration + TMDB counts are the slow part, so gate them
        # behind a live (non-cacheonly) load: the dialog opens instantly from
        # cache, and the one request also yields the full seasons list + totals.
        if not self.cacheonly and not is_movie and media.get("idMal"):
            franchise = self._franchise(media)
            if detail:
                self._apply_franchise_totals(detail, media, franchise)
            start = len(items)
            items.extend(self._season_items(media, franchise))
            folders.update(range(start, len(items)))
        content = "movies" if is_movie else "tvshows"
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
        import time as _t
        _s = _t.time()
        debuglog.dbg("_franchise START mal=%s" % media.get("idMal"))
        result = collect_tv_franchise(self.client, media)
        debuglog.dbg("_franchise DONE mal=%s cours=%s in %.2fs" % (media.get("idMal"), len(list(iter_cours(result))) if result else 0, _t.time() - _s))
        return result

    def _build_episode_list(
        self, media, mal_id=None, season=1, show_title=None, season_offset=0,
        suppress=False, tmdb_id=None, tmdb_season=None,
        episode_count=None, play_offset=0, tmdb_offset=0, display_offset=0,
        season_total=None,
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
        if episode_count is not None:
            # TMDB-split season of a monolithic long-runner: `total`/`last` above are
            # the show's ABSOLUTE aired count; this season lists season-local
            # 1..episode_count, capped to whatever of the absolute run has aired
            # past this season's offset.
            last = max(0, min(int(episode_count), last - int(play_offset)))
        if last < 1:
            return []

        # Primary source for stills + episode names/plots is TMDB (real per-episode
        # art for anime, which AniList lacks for many seasons), indexed by
        # tmdb_offset + local ep. tmdb_offset is the cumulative count of prior cours
        # that share this (tmdb_id, tmdb_season): 0 when each season has its own TMDB
        # season, but the absolute position when TMDB lumps the whole franchise into
        # one season (e.g. Re:Zero -> TMDB season 1 numbers all 4 seasons 1..85).
        # For a standalone (non-franchise) show, resolve the mapping from Fribb.
        if not tmdb_id:
            tmdb_id, tmdb_season = season_map.tmdb_lookup(media.get("id"), mal_id)
        tmdb_eps = {}
        if tmdb_id and tmdb_season:
            try:
                tmdb_eps = tmdb.episode_stills(tmdb_id, tmdb_season)
            except Exception as exc:
                debuglog.dbg("episode_stills failed tmdb=%s s=%s: %s" % (tmdb_id, tmdb_season, exc))
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

        is_split = episode_count is not None
        total_eps = int(episode_count) if is_split else total
        if not is_split and season_total:
            total_eps = int(season_total)
        # Watched state from the unified O(1) store (AniList progress synced at boot +
        # local completion marks), keyed by AniList id -- no network here. An episode
        # is watched when it's contiguous up to `progress` OR an explicit local mark.
        # Episodes use the PLAY numbering (cour-local, or absolute for a monolith).
        aid = media.get("id")
        prog = progress.progress_of(aid)
        watched_eps = set(range(1, prog + 1)) if prog else set()
        watched_eps |= progress.watched_set(aid)
        # Local in-episode resume point (one in-progress episode per show, keyed by
        # AniList id like the progress store) so the in-progress episode renders a
        # PARTIAL progress bar (pos/dur) instead of a full one. Numbered by PLAY episode
        # -- the same number babysit() records -- so it lines up with play_episode below.
        resume_pt = resume.get(aid)
        items = []
        for ep in range(1, last + 1):
            if is_split:
                # TMDB numbers a monolithic long-runner's per-season episodes
                # ABSOLUTELY (One Piece Wano S21 -> episode_number 892..1088), not
                # season-local. The cumulative play_offset is derived from the same
                # TMDB episode counts, so play_offset + local == TMDB's absolute
                # number; fall back to a local key for shows TMDB numbers per-season.
                meta = tmdb_eps.get(int(play_offset) + ep) or tmdb_eps.get(ep) or {}
            else:
                meta = tmdb_eps.get(tmdb_offset + ep) or {}
            thumb = meta.get("still") or thumb_for_episode(thumbs, ep, offset)
            # Display the season-local number (ep); for a TMDB-split season PLAY the
            # absolute AniList episode (offset + local) the search/Otaku backends key on.
            play_episode = (int(play_offset) + ep) if is_split else ep
            # Continuous display number across the cours that aggregate into one
            # season (AoT S4 = Part1 1..16 then Part2 17..28) so the episodes view --
            # which force-sorts by number -- doesn't interleave two cours that each
            # restart at 1. play_episode stays cour-local so playback still resolves
            # the right backend episode; split arcs keep their season-local display.
            display_ep = ep if is_split else (int(display_offset) + ep)
            is_watched = play_episode in watched_eps
            # Partial-bar resume point. A live, unfinished local resume point is
            # AUTHORITATIVE: it wins over a coarse episode-level "watched" mark (which
            # may be stale -- e.g. AniList progress that counts a half-watched episode
            # as done), so re-watching a "completed" episode shows the real fraction
            # rather than a full bar.
            resume_pos = resume_dur = 0
            if (resume_pt and int(resume_pt.get("ep") or 0) == play_episode
                    and resume.should_resume(resume_pt.get("pos"), resume_pt.get("dur"))):
                resume_pos = resume_pt.get("pos") or 0
                resume_dur = resume_pt.get("dur") or 0
                is_watched = False  # partway, not done -> partial bar, no full bar
            items.append(
                build_episode_item(
                    mal_id,
                    display_ep,
                    title,
                    total_eps,
                    season=season,
                    media=media,
                    thumb_url=thumb,
                    play_title=cour_title,
                    ep_name=meta.get("name"),
                    ep_plot=meta.get("plot"),
                    ep_aired=meta.get("aired"),
                    play_episode=play_episode,
                    watched=is_watched,
                    resume_pos=resume_pos,
                    resume_dur=resume_dur,
                )
            )
        return items

    def _upcoming_item(self, media):
        """A single non-playable 'Premieres <date>' row for a not-yet-aired entry.

        A NOT_YET_RELEASED season/show has no aired episodes, so its episode list
        comes up empty -- which reads as broken (e.g. Mushoku Tensei S3, premieres
        2026-07-06). Surface a clear upcoming row instead of a blank list. Returns
        None for anything that has aired (the real episode list is used then).
        """
        if (media.get("status") or "").upper() != "NOT_YET_RELEASED":
            return None
        months = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        start = media.get("startDate") or {}
        year = start.get("year")
        month = start.get("month") or 0
        day = start.get("day") or 0
        if year and 1 <= month <= 12 and day:
            when = "%s %d, %d" % (months[month], day, year)
        elif year:
            when = str(year)
        else:
            when = ""
        label = ("Premieres %s" % when) if when else "Not yet aired"
        li = xbmcgui.ListItem(label=label)
        li.setInfo("video", {"title": label, "mediatype": "episode"})
        li.setProperty("IsPlayable", "false")
        li.setProperty("SpecialSort", "top")
        return li

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

    def _latest_episode(self, media):
        """Latest AIRED episode number (0 if none/unknown)."""
        total = int(media.get("episodes") or 0)
        next_ep = int((media.get("nextAiringEpisode") or {}).get("episode") or 0)
        latest = (next_ep - 1) if next_ep else total
        if latest >= 1:
            return latest
        return 1 if (total or next_ep) else 0

    def _apply_franchise_totals(self, detail, media, franchise):
        """Set the headline season/episode counts on the detail item.

        Relocated from the deleted monitor. TotalSeasons MUST equal the franchise
        group count (the seasons browse view); TotalEpisodes prefers TMDB per-season
        counts when EVERY group is mapped, else the AniList per-cour sum.
        """
        if not franchise:
            return
        if any(group.get("_tmdb_split") for group in franchise):
            # Monolithic long-runner split by TMDB seasons: the cours share one
            # media, so sum the per-season TMDB counts already on each group (no
            # extra TMDB calls) rather than _episode_total (the whole show).
            total_eps = sum(int(group.get("episodes") or 0) for group in franchise)
            detail.setProperty("TotalSeasons", str(len(franchise)))
            detail.setProperty("n", str(len(franchise)))
            if total_eps:
                detail.setProperty("TotalEpisodes", str(total_eps))
            return
        total_eps = sum(
            self._episode_total(c.get("media") or {})
            for group in franchise
            for c in group.get("cours") or []
        )
        tmdb_total = 0
        for group in franchise:
            if not group.get("tmdb_id") or not group.get("tmdb_season"):
                tmdb_total = 0
                break
            count = self._tmdb_season_count(group)
            if not count:
                tmdb_total = 0
                break
            tmdb_total += count
        if tmdb_total:
            total_eps = tmdb_total
        detail.setProperty("TotalSeasons", str(len(franchise)))
        detail.setProperty("n", str(len(franchise)))
        if total_eps:
            detail.setProperty("TotalEpisodes", str(total_eps))

    def _season_items(self, media, franchise=None):
        """Per-season folder items for the More-Episodes list (shared by details/seasons).

        Mirrors the franchise grouping + AniList per-cour episode sum (TMDB count
        only as a fallback -- Fribb often records the same tmdb_season for every
        cour, so its per-season count lumps the whole franchise). Each season tile
        carries year/rating/classification via build_season_item(media=...).
        """
        franchise = franchise if franchise is not None else self._franchise(media)
        if not franchise:
            li = build_season_item(
                media["idMal"], _title(media), self._episode_total(media), media=media
            )
            return [li] if li else []
        show_title = franchise_show_title(franchise, _title)
        items = []
        for group in franchise:
            season = group.get("season") or 1
            cour_media = group.get("media") or media
            if group.get("_tmdb_split"):
                # TMDB-split season: every cour points at the same monolithic media,
                # so summing _episode_total would yield the whole show. The cour's
                # own `episodes` already holds the TMDB per-season count.
                season_total = sum(int(c.get("episodes") or 0) for c in group.get("cours") or [])
            else:
                season_total = sum(
                    self._episode_total(c.get("media") or {}) for c in group.get("cours") or []
                )
                if not season_total:
                    season_total = self._tmdb_season_count(group) or self._episode_total(cour_media)
            li = build_season_item(
                group.get("mal_id") or cour_media.get("idMal"),
                show_title,
                season_total,
                season=season,
                label=f"Season {season}",
                media=cour_media,
            )
            if li:
                items.append(li)
        return _ordered(items)

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

    def _tmdb_offsets(self, franchise):
        """Per-cour offset into a SHARED TMDB season.

        Fribb maps every cour of some franchises to the same (tmdb_id, tmdb_season)
        because TMDB lumps the whole show into one season with absolute episode
        numbering -- e.g. Re:Zero's four anime seasons all map to TMDB season 1
        (85 episodes numbered 1..85). The per-episode still/plot lookup must index
        by the cumulative episode count of prior cours that share the same
        (tmdb_id, tmdb_season), NOT the within-season streamingEpisodes offset
        (which resets each season, so every season would show season-1 art).

        A franchise whose seasons each carry a distinct tmdb_season gets 0 for every
        cour (unchanged); a multi-cour single season gets the same within-season
        cumulative as the streaming offset.
        """
        offsets = {}
        running = {}
        for cour in iter_cours(franchise):
            key = (cour.get("tmdb_id"), cour.get("tmdb_season"))
            offsets[id(cour)] = running.get(key, 0)
            running[key] = running.get(key, 0) + int(cour.get("episodes") or 0)
        return offsets

    def flatseasons(self):
        """All franchise episodes in one flat list across cours."""
        media = self._media()
        if not media:
            return self._finish([], "episodes")
        franchise = self._franchise(media)
        if not franchise:
            items = self._build_episode_list(media)
            return self._finish(_ordered(items), "episodes")
        show_title = franchise_show_title(franchise, _title)
        offsets, suppressed = self._stream_plan(franchise)
        tmdb_offsets = self._tmdb_offsets(franchise)
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
                    suppress=(id(cour) in suppressed) or bool(cour.get("_tmdb_split")),
                    tmdb_id=cour.get("tmdb_id"),
                    tmdb_season=cour.get("tmdb_season"),
                    episode_count=cour.get("_episode_count"),
                    play_offset=cour.get("_play_offset", 0),
                    tmdb_offset=tmdb_offsets.get(id(cour), 0),
                )
            )
        return self._finish(_ordered(items), "episodes")

    def seasons(self):
        media = self._media()
        if not media or not media.get("idMal"):
            return self._finish([], "seasons")
        franchise = self._franchise(media)
        title = franchise_show_title(franchise, _title) if franchise else _title(media)
        try:
            xbmcplugin.setPluginCategory(self.handle, title)
        except Exception:
            pass
        items = self._season_items(media, franchise)
        return self._finish(items, "seasons", set(range(len(items))))

    def episodes(self):
        mal_id = self._mal_id()
        debuglog.dbg("episodes START mal=%s" % mal_id)
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
                tmdb_offsets = self._tmdb_offsets(franchise)
                cours = group.get("cours") or []
                # When several cours aggregate into one season (split cours, e.g.
                # AoT S4 = Final Season Part 1 + Part 2), each cour keeps its own
                # mal_id + cour-local play numbering so playback resolves correctly,
                # but the DISPLAY number must run continuously across them (1..16
                # then 17..28) -- otherwise both cours restart at 1 and the
                # force-sorted episodes view interleaves them. season_total makes
                # the "of N" reflect the whole season.
                season_total = sum(
                    self._episode_total(c.get("media") or {}) for c in cours
                ) or None
                items = []
                display_offset = 0
                for cour in cours:
                    cour_media = cour.get("media") or media
                    cour_items = self._build_episode_list(
                        cour_media,
                        mal_id=cour.get("mal_id") or cour_media.get("idMal"),
                        season=cour.get("season"),
                        show_title=show_title,
                        season_offset=offsets.get(id(cour), 0),
                        suppress=(id(cour) in suppressed) or bool(cour.get("_tmdb_split")),
                        tmdb_id=cour.get("tmdb_id"),
                        tmdb_season=cour.get("tmdb_season"),
                        episode_count=cour.get("_episode_count"),
                        play_offset=cour.get("_play_offset", 0),
                        tmdb_offset=tmdb_offsets.get(id(cour), 0),
                        display_offset=display_offset,
                        season_total=season_total,
                    )
                    items.extend(cour_items)
                    display_offset += len(cour_items)
                if not items:
                    season_media = (cours[0].get("media") if cours else None) or media
                    placeholder = self._upcoming_item(season_media)
                    if placeholder:
                        items = [placeholder]
                return self._finish(_ordered(items), "episodes")
        items = self._build_episode_list(media, mal_id)
        if not items:
            placeholder = self._upcoming_item(media)
            if placeholder:
                items = [placeholder]
        return self._finish(_ordered(items), "episodes")

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

    def _is_monolith(self, media):
        """A single AniList entry that TMDB splits into many display arcs (One Piece,
        Naruto, ...). It plays by ABSOLUTE episode number, so it needs no per-cour
        franchise -- detecting it cheaply by episode count lets the Play path skip the
        slow franchise/TMDB-season split that only exists for the seasons display."""
        total = int((media or {}).get("episodes") or 0)
        if not total:
            nxt = int(((media or {}).get("nextAiringEpisode") or {}).get("episode") or 0)
            total = (nxt - 1) if nxt else 0
        return total > franchise._MONOLITH_MIN_EPISODES

    def _resume_episode(self, mal_id, media):
        """Resume-aware next episode for one (cour) mal_id + its media.

        Reads the unified progress store (AniList progress synced at boot + local
        completion marks, keyed by AniList id) and clamps to what has actually been
        released:
          - nothing watched                 -> episode 1
          - released episodes still unwatched -> last-watched + 1
          - caught up to the last release     -> the last released episode

        Returns ``(episode, fully_done, progress)``. ``fully_done`` is True only when
        the cour is fully AIRED *and* fully watched (the franchise logic advances past
        it). ``progress`` is the resolved watched count (0 = untouched) so callers can
        tell "in progress here" from "never started" without recomputing.

        Pure O(1) local lookup -- no network on this path.
        """
        aid = media.get("id")
        prog = progress.progress_of(aid)
        next_air = int((media.get("nextAiringEpisode") or {}).get("episode") or 0)
        total = int(media.get("episodes") or 0)
        last_released = (next_air - 1) if next_air else total
        if prog <= 0:
            episode, fully_done = 1, False
        elif last_released and prog >= last_released:
            # Watched everything released so far. If nothing more will ever air this
            # is a finished title (a franchise advances past it); otherwise it's the
            # currently-airing tail -> stay on the latest released episode.
            episode, fully_done = last_released, not next_air
        else:
            episode, fully_done = prog + 1, False
        # A live, unfinished resume point is authoritative: resume THAT episode rather
        # than advancing to the next one (so a half-watched episode the progress store
        # already counts as done still resumes, and the Play button reads "Resume N"
        # via the skin's IsResumable variable). Never "done" while mid-episode.
        point = resume.get(aid)
        if point and resume.should_resume(point.get("pos"), point.get("dur")):
            episode, fully_done = int(point.get("ep") or episode), False
        return episode, fully_done, prog

    def _has_resume(self, media):
        """True when the entry has a live (unfinished) local resume point. An entry can
        be 'in progress' via a resume point alone -- with NO completed episode yet -- so
        the Play button must treat that as in-progress too, not just `progress > 0`."""
        point = resume.get((media or {}).get("id"))
        return bool(point and resume.should_resume(point.get("pos"), point.get("dur")))

    def _upnext_item(self, mal_id, anilist_id, episode, title, total, **kwargs):
        """Build the Play-button (next-up) listitem, attaching the local resume point
        when `episode` is the in-progress one. That sets ListItem.IsResumable, which the
        skin's PlayOrResume label reads to show "Resume N" instead of "Play N". The
        resume point is keyed by AniList id; the item itself is built from mal_id."""
        point = resume.get(anilist_id)
        if (point and int(point.get("ep") or 0) == int(episode)
                and resume.should_resume(point.get("pos"), point.get("dur"))):
            kwargs["resume_pos"] = point.get("pos") or 0
            kwargs["resume_dur"] = point.get("dur") or 0
        return build_episode_item(mal_id, episode, title, total, **kwargs)

    def trakt_upnext(self):
        debuglog.dbg("trakt_upnext PARAMS=%s" % dict(self.params))
        mal_id = self._mal_id()
        debuglog.dbg("trakt_upnext START mal=%s" % mal_id)
        if not mal_id:
            return self._finish([], "episodes")
        media = self.client.get_media(mal_id=mal_id)
        debuglog.dbg("trakt_upnext got media mal=%s eps=%s" % (mal_id, (media or {}).get("episodes")))
        if not media:
            return self._finish([], "episodes")

        # FAST PATH: if the viewed cour itself is in progress, resume it directly.
        # This is "resume my latest watched" for the common case (opening the season
        # you're on) AND it skips collecting the whole franchise (~0.5s/cour of
        # sequential network) just to populate the Play button.
        viewed_ep, viewed_done, viewed_prog = self._resume_episode(mal_id, media)
        if (viewed_prog > 0 or self._has_resume(media)) and not viewed_done:
            li = self._upnext_item(mal_id, media.get("id"), viewed_ep, _title(media), self._episode_total(media))
            return self._finish([li] if li else [], "episodes")

        # MONOLITH (One Piece etc.): one AniList entry, absolute episodes, no real
        # cours -> resume the entry directly. Skips collecting the franchise / TMDB
        # season split (a slow network call that on the no-progress path used to hang
        # the Play button).
        if self._is_monolith(media):
            debuglog.dbg("trakt_upnext MONOLITH short-circuit mal=%s ep=%s" % (mal_id, viewed_ep))
            li = self._upnext_item(mal_id, media.get("id"), viewed_ep, _title(media), self._episode_total(media))
            return self._finish([li] if li else [], "episodes")

        # The viewed cour is untouched (a sibling season may be the one in progress)
        # or fully finished (advance to the next season) -> consult the franchise.
        debuglog.dbg("trakt_upnext collecting franchise mal=%s ..." % mal_id)
        franchise = self._franchise(media)
        debuglog.dbg("trakt_upnext franchise ready mal=%s cours=%s" % (mal_id, len(list(iter_cours(franchise))) if franchise else 0))
        show_title = franchise_show_title(franchise, _title) if franchise else _title(media)
        if franchise:
            cours = list(iter_cours(franchise))
            # "resume latest watched": the furthest (latest-ordered) cour with any
            # progress, ignoring unwatched earlier seasons.
            latest = None  # (idx, cour, episode, fully_done)
            for idx, cour in enumerate(cours):
                ep, done, prog = self._resume_episode(cour.get("mal_id"), cour.get("media") or {})
                if prog > 0 or self._has_resume(cour.get("media")):
                    latest = (idx, cour, ep, done)
            if latest is not None:
                idx, cour, ep, done = latest
                # Finished that season and a newer one exists -> start the next.
                if done and idx + 1 < len(cours):
                    cour = cours[idx + 1]
                    ep, _, _ = self._resume_episode(cour.get("mal_id"), cour.get("media") or {})
            else:
                # Nothing watched anywhere -> first cour, episode 1.
                cour, ep = (cours[0] if cours else None), 1
            if cour is not None:
                cour_media = cour.get("media") or {}
                li = self._upnext_item(
                    cour.get("mal_id"), cour_media.get("id"), ep, show_title,
                    self._episode_total(cour_media),
                    season=cour.get("season") or 1, play_title=_title(cour_media),
                )
                return self._finish([li] if li else [], "episodes")

        # Non-franchise: resume the viewed title (ep 1 when nothing is watched).
        total = media.get("episodes") or viewed_ep
        li = self._upnext_item(mal_id, media.get("id"), viewed_ep, show_title, total)
        return self._finish([li] if li else [], "episodes")

    def _record_watched(self, mal_id, media, episode, is_movie):
        """Launch the one-shot resume + completion tracker for a starting playback.

        Tracking is COMPLETION-BASED (not optimistic): the babysitter (resume.babysit)
        seeks to any saved position, then on stop marks the episode watched locally +
        advances AniList progress only once ~90% is reached -- otherwise it stores the
        resume position. Marking at completion rather than at play start means a
        half-watched episode stays "unwatched" so Play resumes it (with the seek)
        instead of skipping ahead. Not a permanent service; the script exits when this
        playback ends. Movies track as episode 1."""
        aid = (media or {}).get("id")
        if not aid:
            return  # no AniList id -> nothing to key resume/completion on
        if is_movie:
            ep = 1
        else:
            try:
                ep = int(episode)
            except (TypeError, ValueError):
                return
            if ep < 1:
                return
        try:
            xbmc.executebuiltin(
                "RunScript(%s, action=resumewatch, aid=%s, episode=%s, mal_id=%s)"
                % (ADDON_ID, aid, ep, mal_id or "")
            )
        except Exception as exc:
            debuglog.dbg("resumewatch launch failed aid=%s ep=%s: %s" % (aid, ep, exc))

    def play(self):
        """Resolve playback through the configured plugin at click time."""
        log_missing_plugin()
        mal_id = self._mal_id()
        debuglog.dbg("play START mal=%s episode=%s" % (mal_id, self.params.get("episode")))
        media = self._media() if mal_id else None
        episode = self.params.get("episode")
        title = self.params.get("title") or (_title(media) if media else "")
        tmdb_type = (self.params.get("tmdb_type") or "").lower()
        is_movie = tmdb_type == "movie" or (media and (media.get("format") or "").upper() in ("MOVIE", "ONE_SHOT"))

        # "Play": a show item's Play button routes here with no episode (the
        # spotlight/hero "Play" expectation). Resume-aware -- play last-watched + 1,
        # or the latest released episode if caught up, or episode 1 if nothing is
        # watched -- so it agrees with the More-Info Play (trakt_upnext) button.
        if not is_movie and not episode and media:
            resume_ep, _, _ = self._resume_episode(mal_id, media)
            episode = str(resume_ep)

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
            self._record_watched(mal_id, media, episode, is_movie)
            return True

        # WatchNixtoons2: pin the exact wcostream page ourselves (replicating
        # WNT2's own search/episode-list scrape — and /movie-list for movies) and
        # hand it to WNT2's actionResolve. DIRECT play, no picker. wcostream has
        # no cross-DB id, so we match by title: the Fribb anime-planet slug first
        # (most reliable), then AniList romaji/english. The SELECTED provider must
        # play every media type, so movies + specials route here too, not just
        # episodes (specials carry an episode number and use the episode path).
        if get_playback_key() == PLAYBACK_WATCHNIXTOONS2 and (episode or is_movie):
            li = self._wnt2_play_item(mal_id, media, title, episode, is_movie)
            if li is not None:
                xbmcplugin.setResolvedUrl(self.handle, True, li)
                self._record_watched(mal_id, media, episode, is_movie)
                return True
            # Miss (no title match / scrape miss) — fall through to WNT2 search.

        # FANime F: replicate its animixplay search + episode-list scrape and the
        # echovideo getSources call to land the m3u8 ourselves — DIRECT play, no
        # keyboard/picker, and it sidesteps fanimef's Play_All bug (which ignores
        # the selected episode). We set the final stream item, so OSD info sticks
        # (no second plugin hop). Handles movies too (a movie is a 1-episode
        # series on animixplay).
        if get_playback_key() == PLAYBACK_FANIME_F and (episode or is_movie):
            li = self._fanimef_play_item(mal_id, media, title, episode, is_movie)
            if li is not None:
                xbmcplugin.setResolvedUrl(self.handle, True, li)
                self._record_watched(mal_id, media, episode, is_movie)
                return True
            # Miss — fall through to launching fanimef's own (keyboard) search.

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
        # Quote the path: it's a plugin:// URL with &-joined params incl. an arbitrary
        # title= (anime titles often contain commas/quotes), and executebuiltin splits
        # its argument on commas -- an unquoted comma in the title breaks the call.
        xbmc.executebuiltin('ActivateWindow(Videos,"{0}",return)'.format(path))
        return True

    def _search_titles(self, mal_id, media, title):
        """Ordered search candidates for the scraper backends (WNT2/Fanime):
        the Fribb anime-planet slug first (most reliable), then AniList."""
        titles = []
        anilist_id = media.get("id") if media else None
        slug = season_map.anime_planet_title(anilist_id=anilist_id, mal_id=mal_id)
        if slug:
            titles.append(slug)
        if media:
            names = media.get("title") or {}
            for key in ("romaji", "english"):
                value = names.get(key)
                if value:
                    titles.append(value)
        if title:
            titles.append(title)
        # wcostream's search matches the bare series name -- "X Season 2" returns
        # nothing while "X" returns the aggregated page that carries every season.
        # Append a season-marker-stripped base of each title (AFTER the specific
        # ones, so a genuinely per-season page like Demon Slayer's arcs is still
        # found first); the season-aware episode match then pins the right cour.
        titles.extend(b for b in (_base_series_title(t) for t in list(titles)) if b)
        seen, out = set(), []
        for candidate in titles:
            key = (candidate or "").lower().strip()
            if key and key not in seen:
                seen.add(key)
                out.append(candidate)
        return out

    def _wnt2_season_offset(self, mal_id, media):
        """(wcostream_season, intra_season_episode_offset) for the cour being played.

        wcostream lists every season of a series on one page, so the episode match
        must know which season the AniList cour is and where it starts. The cour's
        franchise season is the target season; the offset is the episode count of
        earlier cours in the SAME season (wcostream numbers a season's cours
        continuously, so Slime "S2 Part 2 ep1" is wcostream "Season 2 ep13").

        Returns (1, 0) when there's no usable franchise (single-cour show) or for a
        TMDB-split monolith (its episode is already absolute -- season-aware matching
        does not apply; the number-only fallback in match_episode handles it).
        """
        # Monolith: absolute episodes, season-aware matching doesn't apply -> (1, 0)
        # WITHOUT collecting the franchise. This keeps the play path off the slow TMDB
        # season split (which previously made One Piece take ages to resolve).
        if self._is_monolith(media):
            return 1, 0
        try:
            groups = self._franchise(media)
        except Exception:
            groups = None
        if not groups or any(g.get("_tmdb_split") for g in groups):
            return 1, 0
        target = int(mal_id or 0)
        for group in groups:
            running = 0
            for cour in group.get("cours") or []:
                if int(cour.get("mal_id") or 0) == target:
                    return int(group.get("season") or 1), running
                running += int(cour.get("episodes") or 0)
        return 1, 0

    def _wnt2_episode_url(self, mal_id, media, title, episode, season=None, offset=None):
        """Resolve the wcostream episode-page URL for an episode, or None."""
        try:
            ep = int(episode)
        except (TypeError, ValueError):
            return None
        titles = self._search_titles(mal_id, media, title)
        if not titles:
            return None
        if season is None or offset is None:
            season, offset = self._wnt2_season_offset(mal_id, media)
        try:
            url, dbg = wnt2.resolve_episode_url(
                titles, ep, wnt2.default_base_url(), season=season, offset=offset
            )
        except Exception as exc:
            xbmc.log("[8nime] WNT2 resolve failed: %s" % exc, xbmc.LOGWARNING)
            return None
        return url

    def _wnt2_play_item(self, mal_id, media, title, episode, is_movie):
        """Build a playable WNT2 ListItem (episode/special or movie), or None.

        Both resolve to a wcostream page played via WNT2's actionResolve; only
        the lookup (episode-list vs /movie-list) and the OSD metadata differ.
        """
        if is_movie:
            titles = self._search_titles(mal_id, media, title)
            if not titles:
                return None
            try:
                url, dbg = wnt2.resolve_movie_url(titles, wnt2.default_base_url())
            except Exception as exc:
                xbmc.log("[8nime] WNT2 movie resolve failed: %s" % exc, xbmc.LOGWARNING)
                return None
            if not url:
                return None
            li = xbmcgui.ListItem(label=title, path=wnt2.actionresolve_url(url))
            li.setInfo("video", {"mediatype": "movie", "title": title})
            return li

        # Resolve the cour's franchise season + intra-season offset once: it pins
        # the right wcostream season for playback AND gives the OSD a correct
        # SxxExx (our play URL carries no season, so params['season'] is absent).
        import time as _time
        _t = _time.time()
        season_n, offset = self._wnt2_season_offset(mal_id, media)
        debuglog.dbg("_wnt2_play_item season_offset=(%s,%s) in %.2fs" % (season_n, offset, _time.time() - _t))
        _t = _time.time()
        ep_url = self._wnt2_episode_url(
            mal_id, media, title, episode, season=season_n, offset=offset
        )
        debuglog.dbg("_wnt2_play_item episode_url resolved in %.2fs url=%s" % (_time.time() - _t, bool(ep_url)))
        if not ep_url:
            return None
        try:
            ep_n = int(episode)
        except (TypeError, ValueError):
            ep_n = 0
        # WNT2's actionResolve copies OSD metadata from the playing ListItem's
        # infolabels, so stamp the real info (a bare item showed a stale "S1:E24").
        ep_label = "{0} - Episode {1}".format(title, ep_n) if ep_n else title
        li = xbmcgui.ListItem(label=ep_label, path=wnt2.actionresolve_url(ep_url))
        li.setInfo("video", {
            "mediatype": "episode",
            "tvshowtitle": title,
            "title": ep_label,
            "season": season_n,
            "episode": ep_n,
        })
        return li

    def _fanimef_play_item(self, mal_id, media, title, episode, is_movie):
        """Resolve a FANime F episode/special or movie to a playable HLS item, or None."""
        titles = self._search_titles(mal_id, media, title)
        if not titles:
            return None
        if is_movie:
            ep_n = 0
            try:
                res, dbg = fanimef.resolve_movie(titles, dub=False)
            except Exception as exc:
                xbmc.log("[8nime] Fanime movie resolve failed: %s" % exc, xbmc.LOGWARNING)
                return None
        else:
            try:
                ep_n = int(episode)
            except (TypeError, ValueError):
                return None
            try:
                res, dbg = fanimef.resolve_episode(titles, ep_n, dub=False)
            except Exception as exc:
                xbmc.log("[8nime] Fanime resolve failed: %s" % exc, xbmc.LOGWARNING)
                return None
        if not res or not res.get("stream"):
            return None

        stream = res["stream"]
        # Mirror fanimef's play_item: HLS via inputstream.adaptive with the
        # echovideo Referer/UA; non-m3u8 sources get the headers appended to the
        # path. We set this directly (no second hop), so the OSD info below holds.
        hdr = "User-Agent={0}&Referer={1}".format(
            quote_plus(res.get("ua") or ""), quote_plus(res.get("referer") or "")
        )
        if is_movie:
            label = title
            info = {"mediatype": "movie", "title": title}
        else:
            try:
                season_n = int(self.params.get("season") or 1)
            except (TypeError, ValueError):
                season_n = 1
            label = "{0} - Episode {1}".format(title, ep_n) if ep_n else title
            info = {
                "mediatype": "episode",
                "tvshowtitle": title,
                "title": label,
                "season": season_n,
                "episode": ep_n,
            }

        if ".m3u8" in stream:
            li = xbmcgui.ListItem(label=label, path=stream)
            li.setMimeType("application/vnd.apple.mpegurl")
            li.setContentLookup(False)
            li.setProperty("inputstream", "inputstream.adaptive")
            li.setProperty("inputstream.adaptive.manifest_type", "hls")
            li.setProperty("inputstream.adaptive.stream_headers", hdr)
            li.setProperty("inputstream.adaptive.manifest_headers", hdr)
            li.setProperty("inputstream.adaptive.original_audio_language", "en")
            li.setProperty("inputstream.adaptive.stream_selection_type", "adaptive")
        else:
            li = xbmcgui.ListItem(label=label, path=stream + "|" + hdr)

        li.setInfo("video", info)
        return li

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
