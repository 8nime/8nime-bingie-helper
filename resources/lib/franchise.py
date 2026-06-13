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

# A monolithic long-runner (One Piece, Detective Conan, ...) is one AniList entry
# with FAR more episodes than a normal cour. Only such entries are candidates for
# the TMDB season-split; gating on aired count keeps the extra TMDB request off the
# hot path for ordinary single-cour shows (the vast majority).
_MONOLITH_MIN_EPISODES = 60


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


def _aired_count(media):
    """AniList episodes that have aired (handles ongoing entries with null total)."""
    total = int(media.get("episodes") or 0)
    next_ep = int((media.get("nextAiringEpisode") or {}).get("episode") or 0)
    if next_ep:
        aired = next_ep - 1
        return min(total, aired) if total else aired
    return total


def _tmdb_season_split(media, tmdb_id):
    """Split a single monolithic AniList entry across TMDB's own seasons.

    Some long-runners are ONE AniList entry (One Piece, Detective Conan, ...) but
    TMDB divides them into many arc-seasons. AniList numbers their episodes
    continuously (1..N); TMDB restarts each season. Each TMDB regular season
    becomes a franchise 'season' group whose single synthetic cour points back at
    the one AniList media, carrying the TMDB season number plus the cumulative
    episode offset. That lets the episode list show season-local numbers + the
    real TMDB stills/titles while still PLAYING the absolute AniList episode the
    backends expect (offset + local). Returns [] when the show is not a monolithic
    multi-season case (so normal shows are untouched).
    """
    from resources.lib import tmdb

    seasons = tmdb.aired_seasons(tmdb_id)
    if len(seasons) <= 1:
        return []
    seasons = sorted(seasons, key=lambda s: int(s.get("season_number") or 0))
    aired_total = _aired_count(media)
    first_count = int(seasons[0].get("episode_count") or 0)
    # Only a genuine long-runner that plainly spans past TMDB season 1; this guards
    # normal single-season shows that merely share a multi-season TMDB record.
    if aired_total and first_count and aired_total <= first_count:
        return []

    groups = []
    offset = 0
    display = 0
    for s in seasons:
        count = int(s.get("episode_count") or 0)
        if count < 1:
            continue
        # Skip arc-seasons entirely beyond what AniList has aired (future arcs);
        # keep advancing the offset so later seasons stay correctly numbered.
        if aired_total and offset >= aired_total:
            offset += count
            continue
        display += 1
        tmdb_season = int(s.get("season_number"))
        cour = _cour_dict(media, display, tmdb_id, tmdb_season)
        cour["episodes"] = count
        cour["_episode_count"] = count
        cour["_play_offset"] = offset
        groups.append(
            {
                "season": display,
                "mal_id": media.get("idMal"),
                "media": media,
                "episodes": count,
                "cours": [cour],
                "tmdb_id": tmdb_id,
                "tmdb_season": tmdb_season,
                "_tmdb_split": True,
            }
        )
        offset += count
    return groups if len(groups) > 1 else []


def _prequel_anchor(client, media, max_hops=6):
    """Walk PREQUEL relations back to the first ancestor with a Fribb TVDB mapping.

    A just-announced / not-yet-released season isn't in the Fribb snapshot yet, so
    its own lookup misses and the franchise can't be built. Its prior seasons ARE
    mapped, so we follow the PREQUEL chain back to an anchor that resolves, and
    build the franchise from there. Returns the anchor tvdb_id, or None.
    """
    seen = set()
    current = media
    for _ in range(max_hops):
        mal = current.get("idMal")
        if mal in seen:
            break
        seen.add(mal)
        prequel = None
        for edge in (current.get("relations") or {}).get("edges") or []:
            if (edge.get("relationType") or "").upper() != "PREQUEL":
                continue
            node = edge.get("node") or {}
            if (node.get("type") or "").upper() != "ANIME":
                continue
            if (node.get("format") or "").upper() not in ("TV", "TV_SHORT"):
                continue
            prequel = node
            break
        if not prequel or not prequel.get("idMal"):
            break
        tvdb_id, _season = season_map.lookup(prequel.get("id"), prequel.get("idMal"))
        if tvdb_id:
            return tvdb_id
        # Mapping miss this far back too -> fetch the prequel's own relations and
        # keep walking (its edges aren't carried on the related-node summary).
        current = client.get_media(mal_id=prequel.get("idMal"))
        if not current:
            break
    return None


def _append_viewed_cour(result, media):
    """Ensure the viewed entry shows as a season even when Fribb omits it.

    A not-yet-released (or just-added) cour is dropped by `_aired`/absent from the
    snapshot, so a franchise built from its prior seasons wouldn't list it. When the
    viewed TV entry isn't covered by any cour, append it as the next season group so
    the More-Info seasons list stays complete (build_season_item labels it Upcoming).
    """
    if not result:
        return result
    mal = media.get("idMal")
    if not mal or (media.get("format") or "").upper() not in ("TV", "TV_SHORT"):
        return result
    for group in result:
        for cour in group.get("cours") or []:
            if cour.get("mal_id") == mal:
                return result
    next_season = max((int(g.get("season") or 0) for g in result), default=0) + 1
    cour = _cour_dict(media, next_season)
    return list(result) + [{
        "season": next_season,
        "mal_id": mal,
        "media": media,
        "episodes": int(media.get("episodes") or 0),
        "cours": [cour],
        "tmdb_id": None,
        "tmdb_season": None,
    }]


def collect_tv_franchise(client, media):
    """Return ordered season groups for a franchise.

    Primary source is the Fribb TVDB map (no relation walking). A monolithic
    long-runner that AniList tracks as ONE entry but TMDB splits into many seasons
    (One Piece, ...) produces no real Fribb split, so when the TVDB path yields 0
    or 1 season we fall back to splitting by TMDB's own season taxonomy. An entry
    with neither mapping renders as a standalone show.
    """
    if not media or not media.get("idMal"):
        return []

    cache_key = int(media["idMal"])
    cached = client.get_franchise_cache(cache_key)
    if cached is not None:
        return cached

    tvdb_id, _season = season_map.lookup(media.get("id"), media.get("idMal"))
    result = []
    complete = True
    if tvdb_id:
        built = _fribb_cours(client, tvdb_id)
        if built:
            cours, complete = built
            result = _group(cours)

    # Monolithic long-runner fallback: the TVDB path gave no real split, but TMDB
    # may divide the show into many seasons. Rebuild from TMDB when so.
    if len(result) <= 1 and _aired_count(media) > _MONOLITH_MIN_EPISODES:
        tmdb_id, _tmdb_season = season_map.tmdb_lookup(media.get("id"), media.get("idMal"))
        if tmdb_id:
            split = _tmdb_season_split(media, tmdb_id)
            if split:
                result = split
                complete = True

    # Upcoming-season fallback: a not-yet-released cour isn't in the Fribb snapshot,
    # so its own lookup missed and it rendered standalone. Anchor on a mapped
    # PREQUEL to recover the prior seasons.
    if not result and not tvdb_id:
        anchor_tvdb = _prequel_anchor(client, media)
        if anchor_tvdb:
            built = _fribb_cours(client, anchor_tvdb)
            if built:
                cours, complete = built
                result = _group(cours)

    # The viewed entry may be dropped/absent from Fribb (not-yet-released); make
    # sure it still appears as a season alongside the recovered prior seasons.
    result = _append_viewed_cour(result, media)

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
