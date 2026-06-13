# -*- coding: utf-8 -*-
from urllib.parse import quote, urlencode

import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib.api import (
    AniListClient,
    current_season_year,
    media_type_from_tmdb,
    next_season_year,
    previous_season_year,
)
from resources.lib.constants import ADDON_ID, PLUGIN_URL
from resources.lib.info_routes import InfoHandler
from resources.lib.listitems import build_item, build_items, build_spotlight_item
from resources.lib.titles import title_for_media

ADDON = xbmcaddon.Addon()


USERLIST_SLUGS = {
    "imdb-top-rated-movies": {"sort": ["SCORE_DESC"], "format": ["MOVIE"]},
    "imdb-top-rated-tv-shows": {"sort": ["SCORE_DESC"], "format": ["TV", "TV_SHORT"]},
    # Airing now: current-season cohort, sorted by what's hot (mirrors AniList
    # "Popular This Season").
    "latest-releases": {
        "seasonal": "this",
        "format": ["MOVIE"],
        "sort": ["POPULARITY_DESC", "SCORE_DESC"],
    },
    "latest-tv-shows": {
        "seasonal": "this",
        "format": ["TV", "TV_SHORT"],
        "sort": ["POPULARITY_DESC", "SCORE_DESC"],
    },
    # Previous-season cohort: a distinct pool from "airing now" (mirrors AniList
    # showing this season vs. last season as separate rows).
    "last-season-tv": {
        "seasonal": "prev",
        "format": ["TV", "TV_SHORT"],
        "sort": ["POPULARITY_DESC", "SCORE_DESC"],
    },
    # All-time popular: no season filter at all, so it never collapses into the
    # current-season rows the way the old season-locked trakt_popular did.
    "all-time-popular-tv": {
        "format": ["TV", "TV_SHORT"],
        "sort": ["POPULARITY_DESC", "SCORE_DESC"],
    },
    "all-time-popular-movies": {
        "format": ["MOVIE"],
        "sort": ["POPULARITY_DESC", "SCORE_DESC"],
    },
    # New movies: this calendar year's films (anime movies don't cohere into
    # seasonal cohorts the way TV does, so year-scope keeps the row populated).
    "new-movies": {
        "year": "this",
        "format": ["MOVIE"],
        "sort": ["POPULARITY_DESC", "SCORE_DESC"],
    },
}

TMDB_GENRE_MAP = {
    "28": "Action",
    "12": "Adventure",
    "16": "Adventure",
    "35": "Comedy",
    "80": "Psychological",
    "99": "Music",
    "18": "Drama",
    "10751": "Slice of Life",
    "14": "Fantasy",
    "36": "Music",
    "27": "Horror",
    "10402": "Music",
    "9648": "Mystery",
    "10749": "Romance",
    "878": "Sci-Fi",
    "10770": "Drama",
    "53": "Thriller",
    "10752": "Mecha",
    "37": "Sports",
    "10759": "Action",
    "10762": "Slice of Life",
    "10763": "Music",
    "10764": "Sports",
    "10765": "Sci-Fi",
    "10766": "Romance",
    "10767": "Slice of Life",
    "10768": "Mecha",
}

# AniList caps perPage at 50; category/full-window browses show this many by
# merging consecutive AniList pages (CATEGORY_VIEW_SIZE / 50 fetches per page).
_ANILIST_PER_PAGE = 50
CATEGORY_VIEW_SIZE = 100

INFO_ROUTES = {
    "details": "details",
    "cast": "cast",
    "crew": "crew",
    "videos": "videos",
    "recommendations": "recommendations",
    "reviews": "reviews",
    "posters": "posters",
    "flatseasons": "flatseasons",
    "seasons": "seasons",
    "episodes": "episodes",
    "collection": "collection",
    "relations": "relations",
    "trakt_upnext": "trakt_upnext",
    # Bingie's info dialog still calls the legacy Trakt reviews/comments path; map
    # it onto the AniList reviews handler so the row populates instead of erroring.
    "trakt_comments": "reviews",
    "play": "play",
    "stars_in_movies": "stars_in_movies",
    "stars_in_tvshows": "stars_in_tvshows",
    "crew_in_movies": "crew_in_movies",
    "crew_in_tvshows": "crew_in_tvshows",
    "crew_in_both": "crew_in_both",
}


class RouteHandler:
    def __init__(self, handle, params):
        self.handle = handle
        self.params = params
        self.client = AniListClient()
        self.is_widget = self.params.get("widget", "").lower() == "true"

    def run(self):
        info = self.params.get("info", "")
        if info in INFO_ROUTES:
            handler = getattr(InfoHandler(self.handle, self.params), INFO_ROUTES[info])
            return handler()

        dispatch = {
            "trakt_trending": self.trakt_trending,
            "trakt_popular": self.trakt_popular,
            "trakt_favorites": self.trakt_favorites,
            "trakt_userlist": self.trakt_userlist,
            "trending_day": self.trakt_trending,
            "random_trending": self.random_trending,
            "random_popular": self.random_popular,
            "discover": self.discover,
            "anilist_nextup": self.anilist_nextup,
            "anilist_upcoming": self.anilist_upcoming,
            "search": self.search,
            "autocomplete": self.autocomplete,
            "dir_movie": self.dir_all,
            "dir_tv": self.dir_all,
            "dir_ova": self.dir_ova,
        }
        handler = dispatch.get(info)
        if handler:
            return handler()
        if info.startswith("dir_"):
            return self.dir_stub(info)
        # Unknown/empty route (e.g. a bare `plugin://.../` probe from a widget):
        # close cleanly as an empty directory. Returning a failed setResolvedUrl
        # here makes Kodi log "Error getting plugin://..." on every such call.
        if self.handle and self.handle != -1:
            xbmcplugin.endOfDirectory(self.handle, succeeded=True, cacheToDisc=False)
            return True
        xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
        return False

    def _page(self):
        try:
            return max(1, int(self.params.get("page", 1)))
        except (TypeError, ValueError):
            return 1

    def _should_paginate(self):
        """Whether to emit a 'Next Page' folder item.

        Suppress it for widgets (home/info rows that never browse) and for any
        path the skin explicitly marked nextpage=false (e.g. the genre/credits
        preview panels in the info dialog, which are <content>-bound lists that
        cannot navigate into a folder item -> the old Next Page produced an empty
        view). Full-window browses (dir_tv/dir_movie) leave nextpage absent and
        still paginate normally.
        """
        if self.is_widget:
            return False
        return self.params.get("nextpage", "").lower() != "false"

    def _limit(self):
        try:
            return int(self.params.get("limit", 50))
        except (TypeError, ValueError):
            return 50

    def _season_vars(self, which="this"):
        if which == "next":
            season, year = next_season_year()
        elif which in ("prev", "last", "previous"):
            season, year = previous_season_year()
        else:
            season, year = current_season_year()
        return season, f"{year}%"

    def _browse(self, variables, trending=False, content="videos", view_size=None):
        # AniList hard-caps perPage at 50, so a larger displayed page (e.g. 100 for
        # category browses) is assembled by merging consecutive AniList pages. With
        # the default view_size (<=50) this is one fetch, identical to before.
        view_size = int(view_size or self._limit())
        fetches = max(1, -(-view_size // _ANILIST_PER_PAGE))  # ceil(view_size / 50)
        view_page = self._page()
        base = dict(variables)
        base.setdefault("isAdult", False)
        base["perpage"] = _ANILIST_PER_PAGE

        media, has_next = [], False
        for i in range(fetches):
            vars_i = dict(base)
            vars_i["page"] = (view_page - 1) * fetches + i + 1
            page_media, has_next = self.client.browse(vars_i, trending=trending)
            media.extend(page_media)
            if not has_next:
                break

        items = build_items(media)
        if items:
            xbmcplugin.addDirectoryItems(self.handle, [(li.getPath(), li, False) for li in items])

        if has_next and self._should_paginate():
            self._add_next_page()

        xbmcplugin.setContent(self.handle, content)
        xbmcplugin.endOfDirectory(self.handle)
        return True

    def _add_next_page(self):
        nxt = dict(self.params)
        nxt["page"] = str(self._page() + 1)
        label = ADDON.getLocalizedString(32001) or "Next Page"
        li = xbmcgui.ListItem(label=label)
        li.setArt({"icon": "DefaultAddonVideo.png"})
        url = f"{PLUGIN_URL}/?{urlencode(nxt)}"
        xbmcplugin.addDirectoryItem(self.handle, url, li, True)

    def _media_vars(self, tmdb_type=None):
        tmdb_type = tmdb_type or self.params.get("tmdb_type", "tv")
        media_type, formats = media_type_from_tmdb(tmdb_type)
        variables = {"type": media_type}
        if formats:
            variables["format"] = formats
        return variables

    def trakt_trending(self):
        # Global trending (TRENDING_DESC across all anime), NOT season-locked.
        # Season-locking previously made this row collapse into the same titles as
        # the season-scoped "Popular" row; a global trending pool is both the
        # Crunchyroll/AniList convention and clearly distinct from all-time popular.
        return self._browse(self._media_vars(), trending=True)

    def trakt_popular(self):
        variables = self._media_vars()
        season, year = self._season_vars("this")
        variables["season"] = season
        variables["year"] = year
        variables["sort"] = ["POPULARITY_DESC", "SCORE_DESC"]
        return self._browse(variables, trending=False)

    def trakt_favorites(self):
        from resources.lib.auth import has_anilist_token

        # My List reflects the AniList PLANNING list, which a favourite toggle
        # mutates moments earlier. cacheToDisc=False stops Kodi serving a stale
        # (e.g. empty, pre-login) listing after the list changes -- the widget's
        # reload= param already busts it, this covers a full-window browse too.
        if not has_anilist_token():
            xbmcplugin.endOfDirectory(self.handle, succeeded=True, cacheToDisc=False)
            return True
        media, has_next = self.client.watchlist(page=self._page(), per_page=self._limit())
        items = build_items(media)
        if items:
            xbmcplugin.addDirectoryItems(self.handle, [(li.getPath(), li, False) for li in items])
        if has_next and self._should_paginate():
            self._add_next_page()
        xbmcplugin.setContent(self.handle, "videos")
        xbmcplugin.endOfDirectory(self.handle, cacheToDisc=False)
        return True

    def trakt_userlist(self):
        slug = self.params.get("list_slug", "")
        variables = self._media_vars()
        preset = USERLIST_SLUGS.get(slug, {})
        if preset.get("format"):
            variables["format"] = preset["format"]
        variables["sort"] = preset.get("sort", ["SCORE_DESC", "POPULARITY_DESC"])
        if preset.get("seasonal"):
            season, year = self._season_vars(preset["seasonal"])
            variables["season"] = season
            variables["year"] = year
        elif preset.get("year"):
            # Year-only scope (no season filter): keeps the row broad/populated.
            _, year = self._season_vars(preset["year"])
            variables["year"] = year
        return self._browse(variables, trending=False)

    def anilist_nextup(self):
        media = self.client.next_up()
        items = build_items(media)
        if items:
            xbmcplugin.addDirectoryItems(self.handle, [(li.getPath(), li, False) for li in items])
        xbmcplugin.setContent(self.handle, "videos")
        xbmcplugin.endOfDirectory(self.handle)
        return True

    def anilist_upcoming(self):
        variables = self._media_vars()
        season, year = self._season_vars("next")
        variables["season"] = season
        variables["year"] = year
        variables["sort"] = ["POPULARITY_DESC", "SCORE_DESC"]
        return self._browse(variables, trending=False)

    def discover(self):
        info = InfoHandler(self.handle, self.params)
        extended = info.discover_extended()
        if extended is not None:
            return extended

        variables = self._media_vars()
        with_genres = self.params.get("with_genres", "")
        with_id = self.params.get("with_id", "False").lower() == "true"
        if with_genres:
            key = with_genres.split(",")[0].strip()
            if with_id:
                # with_id=True historically meant a numeric TMDB genre id. 8nime
                # emits anime genre NAMES in the Genre.N.TMDb_ID slot, so map a
                # known TMDB id, else accept a name as-is. Only a genuinely
                # unknown numeric id is dropped -- never silently default to
                # "Action", which made the genre panel show the wrong genre (G7).
                genre = TMDB_GENRE_MAP.get(key)
                if not genre and not key.isdigit():
                    genre = key
            else:
                genre = key
            if genre:
                variables["includedGenres"] = [genre]
        sort_by = self.params.get("sort_by", "popularity.desc")
        if "score" in sort_by or "vote" in sort_by:
            variables["sort"] = ["SCORE_DESC", "POPULARITY_DESC"]
        else:
            variables["sort"] = ["POPULARITY_DESC", "SCORE_DESC"]
        return self._browse(variables, trending=False)

    def random_trending(self):
        return self._random_single(trending=True)

    def random_popular(self):
        return self._random_single(trending=False)

    def _random_single(self, trending=False):
        variables = self._media_vars()
        season, year = self._season_vars("this")
        variables["season"] = season
        variables["year"] = year
        pick = self.client.random_pick(variables, trending=trending)
        if pick:
            li = build_spotlight_item(pick)
            if li:
                xbmcplugin.addDirectoryItem(self.handle, li.getPath(), li, False)
        xbmcplugin.setContent(self.handle, "videos")
        xbmcplugin.endOfDirectory(self.handle)
        return True

    def search(self):
        query = self.params.get("query", "")
        if not query:
            xbmcplugin.endOfDirectory(self.handle, succeeded=True)
            return True
        tmdb_type = self.params.get("tmdb_type", "both")
        if tmdb_type == "both":
            media_type, formats = "ANIME", None
        else:
            media_type, formats = media_type_from_tmdb(tmdb_type)
        media, has_next = self.client.search(
            query, media_type, formats=formats, page=self._page(), per_page=self._limit()
        )
        items = build_items(media)
        if items:
            xbmcplugin.addDirectoryItems(self.handle, [(li.getPath(), li, False) for li in items])
        if has_next and self._should_paginate():
            self._add_next_page()
        xbmcplugin.setContent(self.handle, "videos")
        xbmcplugin.endOfDirectory(self.handle)
        return True

    def autocomplete(self):
        """AniList-backed search suggestions for the Bingie search box.

        The suggestion container uses each item's Label as the typed term and
        Property(path) to preview results on focus, so every item carries both.
        """
        query = (self.params.get("query") or self.params.get("id") or "").strip()
        if not query:
            xbmcplugin.endOfDirectory(self.handle, succeeded=True)
            return True
        try:
            media, _ = self.client.search(
                query, "ANIME", formats=None, page=1, per_page=10
            )
        except Exception:
            media = []
        base = f"{PLUGIN_URL}/?info=search&widget=true&tmdb_type=both&query="
        seen = set()
        for entry in media or []:
            title = title_for_media(entry)
            if not title or title in seen:
                continue
            seen.add(title)
            preview = base + quote(title)
            li = xbmcgui.ListItem(label=title)
            li.setProperty("path", preview)
            cover = entry.get("coverImage") or {}
            art_url = cover.get("large") or cover.get("extraLarge")
            if art_url:
                li.setArt({"thumb": art_url, "poster": art_url, "icon": art_url})
            xbmcplugin.addDirectoryItem(self.handle, preview, li, True)
        xbmcplugin.setContent(self.handle, "videos")
        xbmcplugin.endOfDirectory(self.handle, succeeded=True)
        return True

    def dir_all(self):
        info = self.params.get("info", "dir_tv")
        tmdb_type = "movie" if info == "dir_movie" else "tv"
        variables = self._media_vars(tmdb_type)
        variables["sort"] = ["POPULARITY_DESC", "SCORE_DESC"]
        return self._browse(variables, trending=False, view_size=CATEGORY_VIEW_SIZE)

    def dir_ova(self):
        """AniList OVA / ONA / Special browse (replaces the old Otaku OVA link)."""
        variables = {
            "type": "ANIME",
            "format": ["OVA", "ONA", "SPECIAL"],
            "sort": ["POPULARITY_DESC", "SCORE_DESC"],
        }
        return self._browse(variables, trending=False, view_size=CATEGORY_VIEW_SIZE)

    def dir_stub(self, info):
        label = info.replace("dir_", "").replace("_", " ").title()
        li = xbmcgui.ListItem(label=label)
        li.setArt({"icon": "DefaultAddonVideo.png"})
        params = dict(self.params)
        if info in ("dir_movie", "dir_tv"):
            params["info"] = info
        else:
            params["info"] = "trakt_popular"
        url = f"{PLUGIN_URL}/?{urlencode(params)}"
        xbmcplugin.addDirectoryItem(self.handle, url, li, True)
        xbmcplugin.endOfDirectory(self.handle)
        return True
