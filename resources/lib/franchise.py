# -*- coding: utf-8 -*-
"""Build multi-season TV franchises.

Primary source: the bundled Fribb/anime-lists TVDB-season map (season_map.py).
It collapses split cours into the canonical TVDB season number and enumerates a
series' members deterministically -- no fragile relation walking, no rate-limit
truncation. AniList is still queried per member for the live data (titles,
episode counts, streamingEpisodes thumbnails, aired status).

Fallbacks (both honour the "a brand-new season is its own season" rule):
  * A show with no TVDB mapping -> walk AniList PREQUEL/SEQUEL relations and
    number cours sequentially (legacy behaviour).
  * A mapped show whose newest season aired *after* the snapshot was built ->
    forward-extend from the latest known cour via SEQUEL relations, appending
    each unmapped aired TV cour as the next season.

Return shape: an ordered list of SEASON groups. Each group keeps the fields the
callers already rely on (mal_id / season / episodes / media) plus a `cours`
list, so a single season can aggregate multiple cours (e.g. Mushoku Tensei S2 =
two cours -> one "Season 2"):

    {
      "season": 2,
      "mal_id": <first cour mal id>,   # representative for the season tile
      "media":  <first cour media>,    # representative
      "episodes": <sum of cour episode counts>,
      "cours": [ {mal_id, anilist_id, season, episodes, media, start_key}, ... ],
    }
"""
from resources.lib import season_map

# Only count cours that have aired or are airing. A mapped-but-unreleased season
# (NOT_YET_RELEASED -- e.g. Jujutsu Kaisen S3, which the TVDB map *does* list) is
# fetched by id (not via the status-filtered page queries), so we still drop it
# here to avoid an empty "Season N" with no episodes or thumbnails.
AIRED_STATUSES = {"FINISHED", "RELEASING", "HIATUS"}


def _start_sort_key(media):
    start = media.get("startDate") or {}
    return (
        int(start.get("year") or 0),
        int(start.get("month") or 0),
        int(start.get("day") or 0),
        int(media.get("idMal") or 0),
    )


def _aired(media):
    status = (media.get("status") or "").upper()
    return not status or status in AIRED_STATUSES


def _cour_dict(media, season, tmdb_id=None, tmdb_season=None):
    return {
        "mal_id": int(media.get("idMal") or 0) or None,
        "anilist_id": media.get("id"),
        "season": int(season),
        "episodes": int(media.get("episodes") or 0),
        "media": media,
        "start_key": _start_sort_key(media),
        "tmdb_id": tmdb_id,
        "tmdb_season": tmdb_season,
    }


def _fetch_media(client, mal_id=None, anilist_id=None):
    if mal_id:
        media = client.get_media(mal_id=mal_id)
        if media:
            return media
        return client.get_franchise_media(mal_id)
    if anilist_id:
        return client.get_media(anilist_id=anilist_id)
    return None


def _fribb_cours(client, tvdb_id):
    """Build cours purely from the Fribb TVDB map (no relation walking).

    Returns (cours, complete) or None when the series has no aired TV season. A
    member fetch that transiently fails marks the build incomplete so it is not
    cached and the next poll can heal it.
    """
    members = season_map.members(tvdb_id)
    tv_members = [m for m in members if m["is_tv"] and m["season"] >= 1]
    if not tv_members:
        return None

    # Choose the season axis that actually DISTINGUISHES the cours. TVDB season is
    # the default (Fribb's most reliable split); only defer to tmdb_season when
    # TVDB lumps every cour into one season but TMDB separates them. Fribb often
    # records tmdb_season=1 for EVERY cour of a multi-season show (e.g. Re:Zero,
    # which has correct TVDB seasons 1/2/2/3/4 but tmdb_season=1 throughout) — so
    # preferring tmdb_season collapsed them all into one ~85-episode season.
    tvdb_seasons = {m["season"] for m in tv_members}
    tmdb_seasons = {m.get("tmdb_season") for m in tv_members if m.get("tmdb_season")}
    group_by_tmdb = len(tvdb_seasons) <= 1 and len(tmdb_seasons) > 1

    cours = []
    complete = True
    for member in sorted(tv_members, key=lambda m: (m["season"], m["mal"] or 0)):
        full = _fetch_media(client, mal_id=member["mal"], anilist_id=member["anilist"])
        if not full:
            complete = False
            continue
        if not _aired(full):
            continue
        # tmdb_id/tmdb_season are still passed through for fetching TMDB stills,
        # but the GROUPING uses the distinguishing axis chosen above.
        if group_by_tmdb:
            group_season = member.get("tmdb_season") or member["season"]
        else:
            group_season = member["season"]
        cours.append(
            _cour_dict(full, group_season, member.get("tmdb_id"), member.get("tmdb_season"))
        )

    if not cours:
        return None
    return cours, complete


def _group(cours):
    by_season = {}
    for cour in cours:
        by_season.setdefault(cour["season"], []).append(cour)
    groups = []
    for season in sorted(by_season):
        members = sorted(by_season[season], key=lambda c: c["start_key"])
        tmdb_id = next((c.get("tmdb_id") for c in members if c.get("tmdb_id")), None)
        tmdb_season = next((c.get("tmdb_season") for c in members if c.get("tmdb_season")), None)
        groups.append(
            {
                "season": season,
                "mal_id": members[0]["mal_id"],
                "media": members[0]["media"],
                "episodes": sum(int(c["episodes"] or 0) for c in members),
                "cours": members,
                "tmdb_id": tmdb_id,
                "tmdb_season": tmdb_season,
            }
        )
    return groups


def collect_tv_franchise(client, media):
    """Return ordered season groups for a franchise, sourced ONLY from the Fribb
    TVDB map -- no relation walking. An entry with no TVDB mapping (e.g. a brand
    new or not-yet-released cour absent from the snapshot) yields no franchise, so
    the caller renders it as a standalone show until Fribb catches up.
    """
    if not media or not media.get("idMal"):
        return []

    cache_key = int(media["idMal"])
    cached = client.get_franchise_cache(cache_key)
    if cached is not None:
        return cached

    tvdb_id, _season = season_map.lookup(media.get("id"), media.get("idMal"))
    if not tvdb_id:
        return []
    built = _fribb_cours(client, tvdb_id)
    if not built:
        return []
    cours, complete = built

    result = _group(cours)

    # Only memoize a fully-resolved build. A transiently truncated walk/extend is
    # returned for this call but left uncached so the next poll can heal it.
    if complete and result:
        client.set_franchise_cache(cache_key, result)
        for group in result:
            for cour in group["cours"]:
                if cour.get("mal_id"):
                    client.set_franchise_cache(int(cour["mal_id"]), result)

    return result


def iter_cours(franchise):
    """Flat, season-ordered cours across every group (for global numbering)."""
    cours = []
    for group in franchise:
        cours.extend(group.get("cours") or [])
    return cours


def franchise_show_title(franchise, title_fn):
    """Pick a stable show title from the first cour with a resolved title."""
    if not franchise:
        return ""
    for cour in iter_cours(franchise):
        media = cour.get("media") or {}
        title = title_fn(media)
        if title and title != "Unknown":
            return title
    first = franchise[0] if franchise else {}
    return title_fn(first.get("media") or {})


def franchise_entry_for_season(franchise, season):
    """Return the season group for a season number, or None."""
    try:
        season = int(season)
    except (TypeError, ValueError):
        return None
    if season < 1:
        return None
    for group in franchise:
        if group.get("season") == season:
            return group
    return None
