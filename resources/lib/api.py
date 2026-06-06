# -*- coding: utf-8 -*-
import json
import random
import time

import requests
import xbmc
import xbmcaddon

from resources.lib.auth import get_anilist_token, has_anilist_token
from resources.lib.cache import ApiCache, get_api_cache
from resources.lib.constants import ANILIST_API

ADDON = xbmcaddon.Addon()
_CACHE = get_api_cache()
_MEDIA_CACHE = {}
_FRANCHISE_CACHE = {}
_MIN_REQUEST_INTERVAL = 0.35
_LAST_REQUEST_AT = 0.0

# AniList caps pagination at page * perPage <= 5000 entries; deeper requests
# return HTTP 400 "Page depth exceeds maximum allowed". We never advertise a
# Next Page beyond this and refuse to issue the doomed request ourselves.
ANILIST_MAX_DEPTH = 5000


def _depth_ok(page, per_page):
    try:
        return int(page) * int(per_page) <= ANILIST_MAX_DEPTH
    except (TypeError, ValueError):
        return True


def _capped_has_next(page, per_page, api_has_next):
    """True only if AniList reports more AND the next page stays within depth."""
    return bool(api_has_next) and _depth_ok(int(page) + 1, per_page)


# Playable anime video formats. Staff/character connections return everything a
# person is credited on -- including MANGA/NOVEL/ONE_SHOT -- which are not
# playable here, so credit lists are restricted to these.
ANIME_VIDEO_FORMATS = {"TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL"}


def _clean_credits(nodes):
    """Filter a staff credit list to aired, playable anime, de-duplicated.

    Drops NOT_YET_RELEASED (honouring the global no-NYR rule -- the staff
    connections take no status arg, so it must be done here), drops non-video
    formats (manga/novels), and removes duplicate entries that per-role edges
    produce.
    """
    out = []
    seen = set()
    for node in nodes or []:
        if (node.get("status") or "").upper() == "NOT_YET_RELEASED":
            continue
        if (node.get("format") or "").upper() not in ANIME_VIDEO_FORMATS:
            continue
        key = node.get("id") or node.get("idMal")
        if key in seen:
            continue
        seen.add(key)
        out.append(node)
    return out

MEDIA_FIELDS = """
    id
    idMal
    type
    title { romaji english userPreferred }
    coverImage { extraLarge large color }
    bannerImage
    startDate { year month day }
    endDate { year month day }
    description
    synonyms
    format
    episodes
    status
    nextAiringEpisode { airingAt episode }
    source
    genres
    duration
    countryOfOrigin
    averageScore
    trailer { id site }
"""

RELATION_NODE_FIELDS = """
    id
    idMal
    type
    format
    episodes
    status
    startDate { year month day }
    title { romaji english userPreferred }
    coverImage { extraLarge large }
    bannerImage
    staff(perPage: 8, sort: RELEVANCE) {
        edges {
            role
            node {
                id
                name { userPreferred full }
                image { large }
            }
        }
    }
"""

FRANCHISE_MEDIA_QUERY = """
query ($idMal: Int, $id: Int, $type: MediaType) {
    Media(idMal: $idMal, id: $id, type: $type) {
        %s
        relations {
            edges {
                relationType
                node {
                    %s
                }
            }
        }
    }
}
""" % (RELATION_NODE_FIELDS.strip(), RELATION_NODE_FIELDS.strip())

BASE_QUERY = """
query (
    $page: Int = 1,
    $perpage: Int = 50,
    $type: MediaType,
    $isAdult: Boolean = false,
    $format: [MediaFormat],
    $season: MediaSeason,
    $includedGenres: [String],
    $year: String,
    $status: MediaStatus,
    $sort: [MediaSort] = [POPULARITY_DESC, SCORE_DESC]
) {
    Page(page: $page, perPage: $perpage) {
        pageInfo { hasNextPage }
        media(
            type: $type,
            format_in: $format,
            genre_in: $includedGenres,
            season: $season,
            startDate_like: $year,
            sort: $sort,
            status: $status,
            status_not_in: [NOT_YET_RELEASED],
            isAdult: $isAdult
        ) {
            %s
        }
    }
}
""" % MEDIA_FIELDS.strip()

TRENDING_QUERY = """
query ($page: Int = 1, $perpage: Int = 50, $type: MediaType, $format: [MediaFormat], $season: MediaSeason, $year: String) {
    Page(page: $page, perPage: $perpage) {
        pageInfo { hasNextPage }
        media(
            type: $type,
            format_in: $format,
            season: $season,
            startDate_like: $year,
            status_not_in: [NOT_YET_RELEASED],
            sort: [TRENDING_DESC, POPULARITY_DESC]
        ) {
            %s
        }
    }
}
""" % MEDIA_FIELDS.strip()

SEARCH_QUERY = """
query ($page: Int = 1, $perpage: Int = 50, $search: String, $type: MediaType, $format: [MediaFormat]) {
    Page(page: $page, perPage: $perpage) {
        pageInfo { hasNextPage }
        media(search: $search, type: $type, format_in: $format, status_not_in: [NOT_YET_RELEASED], sort: [SEARCH_MATCH, POPULARITY_DESC]) {
            %s
        }
    }
}
""" % MEDIA_FIELDS.strip()

STUDIO_QUERY = """
query ($search: String, $page: Int = 1, $perpage: Int = 50) {
    Studio(search: $search) {
        id
        name
        media(page: $page, perPage: $perpage, sort: [POPULARITY_DESC, START_DATE_DESC]) {
            pageInfo { hasNextPage }
            nodes {
                %s
            }
        }
    }
}
""" % MEDIA_FIELDS.strip()

LIST_COLLECTION_QUERY = """
query ($userId: Int, $status: MediaListStatus, $sort: [MediaListSort]) {
    MediaListCollection(userId: $userId, status: $status, type: ANIME, sort: $sort) {
        lists {
            entries {
                progress
                media {
                    %s
                }
            }
        }
    }
}
""" % MEDIA_FIELDS.strip()

VIEWER_QUERY = """
query { Viewer { id name } }
"""

MEDIA_DETAIL_QUERY = """
query ($idMal: Int, $id: Int, $type: MediaType) {
    Media(idMal: $idMal, id: $id, type: $type) {
        id
        idMal
        type
        title { romaji english userPreferred }
        coverImage { extraLarge large color }
        bannerImage
        startDate { year month day }
        endDate { year month day }
        description
        synonyms
        format
        episodes
        status
        nextAiringEpisode { airingAt episode }
        genres
        duration
        countryOfOrigin
        averageScore
        source
        hashtag
        trailer { id site }
        streamingEpisodes { title thumbnail site }
        stats {
            scoreDistribution { score amount }
            statusDistribution { status amount }
        }
        characters(page: 1, perPage: 25, sort: ROLE) {
            edges {
                role
                node {
                    id
                    name { userPreferred full }
                    image { large }
                }
                voiceActors(language: JAPANESE) {
                    id
                    name { userPreferred full }
                    image { large }
                }
            }
        }
        staff(page: 1, perPage: 25, sort: RELEVANCE) {
            edges {
                role
                node {
                    id
                    name { userPreferred full }
                    image { large }
                }
            }
        }
        studios(isMain: true) {
            edges {
                node { id name }
            }
        }
        relations {
            edges {
                relationType
                node {
                    %s
                }
            }
        }
    }
}
""" % RELATION_NODE_FIELDS.strip()

RECOMMENDATIONS_QUERY = """
query ($idMal: Int, $page: Int, $perpage: Int) {
    Media(idMal: $idMal, type: ANIME) {
        recommendations(page: $page, perPage: $perpage, sort: [RATING_DESC, ID]) {
            pageInfo { hasNextPage }
            edges {
                node {
                    mediaRecommendation {
                        %s
                    }
                }
            }
        }
    }
}
""" % MEDIA_FIELDS.strip()

REVIEWS_QUERY = """
query ($idMal: Int, $page: Int, $perPage: Int) {
    Media(idMal: $idMal, type: ANIME) {
        reviews(page: $page, perPage: $perPage, sort: [ID_DESC]) {
            pageInfo { hasNextPage }
            edges {
                node {
                    summary
                    body
                    score
                    rating
                    createdAt
                    user { name avatar { large } }
                }
            }
        }
    }
}
"""

STAFF_CHARACTER_MEDIA_QUERY = """
query ($id: Int, $page: Int, $perpage: Int) {
    Staff(id: $id) {
        id
        name { userPreferred full }
        image { large }
        characterMedia(page: $page, perPage: $perpage, sort: [POPULARITY_DESC]) {
            pageInfo { hasNextPage }
            nodes { %s }
        }
    }
}
""" % MEDIA_FIELDS.strip()

STAFF_PRODUCTION_MEDIA_QUERY = """
query ($id: Int, $page: Int, $perpage: Int) {
    Staff(id: $id) {
        id
        name { userPreferred full }
        image { large }
        staffMedia(page: $page, perPage: $perpage, sort: [POPULARITY_DESC]) {
            pageInfo { hasNextPage }
            nodes { %s }
        }
    }
}
""" % MEDIA_FIELDS.strip()

# Resolve a creator/staff member by NAME (the skin's Cast & More dialog only
# carries the name when the detail item is live-enriched, with no staff id), then
# return their production credits. Without this the name fallback would search
# media TITLES for a person's name and find nothing.
STAFF_SEARCH_MEDIA_QUERY = """
query ($search: String, $page: Int, $perpage: Int) {
    Staff(search: $search) {
        id
        name { userPreferred full }
        staffMedia(page: $page, perPage: $perpage, sort: [POPULARITY_DESC]) {
            pageInfo { hasNextPage }
            nodes { %s }
        }
    }
}
""" % MEDIA_FIELDS.strip()

PROGRESS_QUERY = """
query ($userId: Int, $mediaId: Int) {
    MediaList(userId: $userId, mediaId: $mediaId, type: ANIME) {
        progress
        status
    }
}
"""


def clear_all_caches(expired_only=False):
    """Clear GraphQL disk/memory cache and in-process media/franchise caches."""
    if expired_only:
        return _CACHE.clear_expired()
    removed = _CACHE.clear_all()
    _MEDIA_CACHE.clear()
    _FRANCHISE_CACHE.clear()
    return removed


class AniListClient:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        token = get_anilist_token()
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    def get_franchise_cache(self, mal_id):
        return _FRANCHISE_CACHE.get(int(mal_id))

    def set_franchise_cache(self, mal_id, franchise):
        _FRANCHISE_CACHE[int(mal_id)] = franchise

    def get_franchise_media(self, mal_id=None, anilist_id=None):
        variables = {"type": "ANIME"}
        if mal_id:
            variables["idMal"] = int(mal_id)
        elif anilist_id:
            variables["id"] = int(anilist_id)
        else:
            return None
        data = self._post(FRANCHISE_MEDIA_QUERY, variables)
        return (data or {}).get("Media")

    def _throttle(self):
        global _LAST_REQUEST_AT
        now = time.time()
        wait = _MIN_REQUEST_INTERVAL - (now - _LAST_REQUEST_AT)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_AT = time.time()

    def _post(self, query, variables=None, use_cache=True):
        cached = _CACHE.get(query, variables) if use_cache else None
        if cached is not None:
            return cached

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        for attempt in range(4):
            self._throttle()
            try:
                resp = self._session.post(ANILIST_API, json=payload, timeout=20)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2 + attempt * 2))
                    xbmc.log(
                        f"[AniListBingieHelper] Rate limited (429), retry in {retry_after}s",
                        xbmc.LOGWARNING,
                    )
                    time.sleep(retry_after)
                    continue
                if resp.status_code >= 400:
                    body = (resp.text or "")[:500]
                    xbmc.log(
                        f"[AniListBingieHelper] API error: HTTP {resp.status_code} "
                        f"vars={variables} body={body}",
                        xbmc.LOGERROR,
                    )
                    resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                xbmc.log(f"[AniListBingieHelper] API error: {exc}", xbmc.LOGERROR)
                stale = _CACHE.get_stale(query, variables) if use_cache else None
                if stale is not None:
                    xbmc.log("[AniListBingieHelper] Serving stale cache after API failure", xbmc.LOGINFO)
                    return stale
                return None

            if data.get("errors"):
                xbmc.log(f"[AniListBingieHelper] GraphQL errors: {data['errors']}", xbmc.LOGERROR)
                stale = _CACHE.get_stale(query, variables) if use_cache else None
                return stale if stale is not None else None

            result = data.get("data")
            if use_cache and result is not None:
                _CACHE.set(query, variables, result)
            return result

        stale = _CACHE.get_stale(query, variables) if use_cache else None
        if stale is not None:
            xbmc.log("[AniListBingieHelper] Serving stale cache after 429 exhaustion", xbmc.LOGINFO)
        return stale

    def browse(self, variables, trending=False):
        cur_page = variables.get("page", 1)
        per_page = variables.get("perpage", 50)
        if not _depth_ok(cur_page, per_page):
            return [], False
        query = TRENDING_QUERY if trending else BASE_QUERY
        data = self._post(query, variables)
        if not data:
            return [], False
        page = data.get("Page") or {}
        has_next = (page.get("pageInfo") or {}).get("hasNextPage")
        return page.get("media") or [], _capped_has_next(cur_page, per_page, has_next)

    def browse_studio(self, studio_name, media_type, formats=None, page=1, per_page=50):
        # AniList's media() has no `studio` argument; studios are reached via the
        # Studio(search:) node. The media connection there carries no status/format
        # filter args, so NOT_YET_RELEASED and format are filtered client-side to
        # match the rest of the addon (aired-only).
        if not _depth_ok(page, per_page):
            return [], False
        data = self._post(
            STUDIO_QUERY,
            {"search": studio_name, "page": page, "perpage": per_page},
        )
        if not data:
            return [], False
        conn = (data.get("Studio") or {}).get("media") or {}
        fmt = {f.upper() for f in (formats or [])}
        items = []
        for node in conn.get("nodes") or []:
            if (node.get("status") or "").upper() == "NOT_YET_RELEASED":
                continue
            if fmt and (node.get("format") or "").upper() not in fmt:
                continue
            items.append(node)
        has_next = (conn.get("pageInfo") or {}).get("hasNextPage")
        return items, _capped_has_next(page, per_page, has_next)

    def search(self, search, media_type, formats=None, page=1, per_page=50):
        variables = {"page": page, "perpage": per_page, "search": search, "type": media_type}
        if formats:
            variables["format"] = formats
        if not _depth_ok(page, per_page):
            return [], False
        data = self._post(SEARCH_QUERY, variables)
        if not data:
            return [], False
        page_data = data.get("Page") or {}
        has_next = (page_data.get("pageInfo") or {}).get("hasNextPage")
        return page_data.get("media") or [], _capped_has_next(page, per_page, has_next)

    def get_media(self, mal_id=None, anilist_id=None):
        cache_key = None
        if mal_id:
            cache_key = int(mal_id)
            if cache_key in _MEDIA_CACHE:
                return _MEDIA_CACHE[cache_key]
        variables = {"type": "ANIME"}
        if mal_id:
            variables["idMal"] = int(mal_id)
        elif anilist_id:
            variables["id"] = int(anilist_id)
        else:
            return None
        data = self._post(MEDIA_DETAIL_QUERY, variables)
        media = (data or {}).get("Media")
        if media and mal_id:
            _MEDIA_CACHE[int(mal_id)] = media
        return media

    def get_recommendations(self, mal_id, page=1, per_page=20):
        data = self._post(
            RECOMMENDATIONS_QUERY,
            {"idMal": int(mal_id), "page": page, "perpage": per_page},
        )
        if not data:
            return [], False
        rec = ((data.get("Media") or {}).get("recommendations") or {})
        edges = rec.get("edges") or []
        items = []
        for edge in edges:
            media = (edge.get("node") or {}).get("mediaRecommendation")
            if media:
                items.append(media)
        has_next = bool((rec.get("pageInfo") or {}).get("hasNextPage"))
        return items, has_next

    def get_reviews(self, mal_id, page=1, per_page=20):
        data = self._post(
            REVIEWS_QUERY,
            {"idMal": int(mal_id), "page": page, "perPage": per_page},
        )
        if not data:
            return [], False
        rev = ((data.get("Media") or {}).get("reviews") or {})
        edges = rev.get("edges") or []
        items = [(edge.get("node") or {}) for edge in edges if edge.get("node")]
        has_next = bool((rev.get("pageInfo") or {}).get("hasNextPage"))
        return items, has_next

    def get_staff_media(self, staff_id, character=True, page=1, per_page=25):
        query = STAFF_CHARACTER_MEDIA_QUERY if character else STAFF_PRODUCTION_MEDIA_QUERY
        data = self._post(
            query,
            {"id": int(staff_id), "page": page, "perpage": per_page},
        )
        if not data:
            return [], False
        staff = data.get("Staff") or {}
        key = "characterMedia" if character else "staffMedia"
        conn = staff.get(key) or {}
        items = _clean_credits(conn.get("nodes"))
        has_next = bool((conn.get("pageInfo") or {}).get("hasNextPage"))
        return items, has_next

    def get_staff_media_by_name(self, name, page=1, per_page=25):
        """Production credits for the staff member matching `name` (creator path)."""
        if not name:
            return [], False
        data = self._post(
            STAFF_SEARCH_MEDIA_QUERY,
            {"search": name, "page": page, "perpage": per_page},
        )
        if not data:
            return [], False
        conn = (data.get("Staff") or {}).get("staffMedia") or {}
        items = _clean_credits(conn.get("nodes"))
        has_next = bool((conn.get("pageInfo") or {}).get("hasNextPage"))
        return items, has_next

    def get_progress(self, mal_id):
        if not has_anilist_token():
            return 0
        viewer = self._post(VIEWER_QUERY)
        if not viewer or not viewer.get("Viewer"):
            return 0
        media = self.get_media(mal_id=mal_id)
        if not media:
            return 0
        data = self._post(
            PROGRESS_QUERY,
            {"userId": viewer["Viewer"]["id"], "mediaId": media["id"]},
        )
        entry = (data or {}).get("MediaList")
        if not entry:
            return 0
        return int(entry.get("progress") or 0)

    def resolve_mal_id(self, params):
        for key in ("mal_id", "tmdb_id"):
            val = params.get(key)
            if val and str(val).isdigit():
                return int(val)
        anilist_id = params.get("anilist_id")
        if anilist_id and str(anilist_id).isdigit():
            media = self.get_media(anilist_id=int(anilist_id))
            if media and media.get("idMal"):
                return int(media["idMal"])
        query = params.get("query", "").strip()
        if query:
            items, _ = self.search(query, "ANIME", page=1, per_page=5)
            year = params.get("year")
            for item in items:
                if not item.get("idMal"):
                    continue
                if year:
                    start = item.get("startDate") or {}
                    if str(start.get("year") or "") != str(year):
                        continue
                return int(item["idMal"])
            for item in items:
                if item.get("idMal"):
                    return int(item["idMal"])
        return None

    def _list_entries(self, status, sort):
        if not has_anilist_token():
            return []
        viewer = self._post(VIEWER_QUERY)
        if not viewer or not viewer.get("Viewer"):
            return []
        user_id = viewer["Viewer"]["id"]
        data = self._post(
            LIST_COLLECTION_QUERY,
            {"userId": user_id, "status": status, "sort": sort},
        )
        if not data:
            return []
        entries = []
        collection = data.get("MediaListCollection") or {}
        for mlist in collection.get("lists") or []:
            for entry in mlist.get("entries") or []:
                if entry not in entries:
                    entries.append(entry)
        return entries

    def next_up(self):
        entries = self._list_entries("CURRENT", ["UPDATED_TIME_DESC"])
        items = []
        for entry in entries:
            media = entry.get("media")
            if not media or not media.get("idMal"):
                continue
            if (entry.get("progress") or 0) >= (media.get("episodes") or 0) and media.get("episodes"):
                continue
            media["_progress"] = entry.get("progress") or 0
            items.append(media)
        return items

    def watchlist(self, page=1, per_page=50):
        entries = self._list_entries("PLANNING", ["UPDATED_TIME_DESC"])
        if not entries:
            return [], False
        start = (page - 1) * per_page
        chunk = entries[start : start + per_page]
        media = [e.get("media") for e in chunk if e.get("media")]
        has_next = start + per_page < len(entries)
        return media, has_next

    def has_token(self):
        return has_anilist_token()

    def save_media_score(self, mal_id, sync_type):
        if not self.has_token():
            return False, "not_logged_in"
        media = self.get_media(mal_id=int(mal_id))
        if not media or not media.get("id"):
            return False, "no_media"
        media_id = int(media["id"])
        if sync_type == "reset":
            data = self._post(
                """
                mutation ($mediaId: Int) {
                    DeleteMediaListEntry(mediaId: $mediaId) { deleted }
                }
                """,
                {"mediaId": media_id},
            )
            deleted = (data or {}).get("DeleteMediaListEntry") or {}
            return bool(deleted.get("deleted")), "reset"
        score_map = {"like": 85.0, "dislike": 25.0}
        score = score_map.get(sync_type)
        if score is None:
            return False, "unknown"
        fmt = (media.get("format") or "").upper()
        status = "COMPLETED" if fmt in ("MOVIE", "ONE_SHOT") else "CURRENT"
        data = self._post(
            """
            mutation ($mediaId: Int, $score: Float, $status: MediaListStatus) {
                SaveMediaListEntry(mediaId: $mediaId, score: $score, status: $status) {
                    id
                    score
                }
            }
            """,
            {"mediaId": media_id, "score": score, "status": status},
        )
        return bool((data or {}).get("SaveMediaListEntry")), sync_type

    def random_pick(self, variables, trending=False, pool_size=25):
        variables = dict(variables)
        variables["page"] = random.randint(1, 3)
        variables["perpage"] = pool_size
        items, _ = self.browse(variables, trending=trending)
        playable = [m for m in items if m.get("idMal")]
        return random.choice(playable) if playable else None


def media_type_from_tmdb(tmdb_type):
    if tmdb_type == "movie":
        return "ANIME", ["MOVIE"]
    if tmdb_type == "tv":
        return "ANIME", ["TV", "TV_SHORT"]
    return "ANIME", None


def current_season_year():
    import datetime

    month = datetime.datetime.now().month
    year = datetime.datetime.now().year
    if month in (12, 1, 2):
        return "WINTER", str(year if month != 12 else year + 1)
    if month in (3, 4, 5):
        return "SPRING", str(year)
    if month in (6, 7, 8):
        return "SUMMER", str(year)
    return "FALL", str(year)


def next_season_year():
    order = ["WINTER", "SPRING", "SUMMER", "FALL"]
    season, year = current_season_year()
    idx = order.index(season)
    next_season = order[(idx + 1) % 4]
    next_year = str(int(year) + (1 if season == "FALL" and next_season == "WINTER" else 0))
    return next_season, next_year


def previous_season_year():
    order = ["WINTER", "SPRING", "SUMMER", "FALL"]
    season, year = current_season_year()
    idx = order.index(season)
    prev_season = order[(idx - 1) % 4]
    # WINTER's predecessor is FALL of the prior calendar year.
    prev_year = str(int(year) - (1 if season == "WINTER" and prev_season == "FALL" else 0))
    return prev_season, prev_year
