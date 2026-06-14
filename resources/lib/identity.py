# -*- coding: utf-8 -*-
"""Skin-facing identity: tmdb_id everywhere, sourced from AniList via Fribb.

The Bingie skin's whole contract is keyed on tmdb_id. The 8nime helper sources
its data from AniList, so it maps AniList/MAL -> tmdb_id with the Fribb table
(see season_map) and emits tmdb_id to the skin. Titles Fribb has no TMDB mapping
for (many OVAs/ONAs/niche shows) get a stable, helper-owned SURROGATE id in a
disjoint high namespace, so every title carries a usable tmdb_id and round-trips
through the skin unchanged. On the way back in, the helper reverse-maps an
inbound tmdb_id (+ season) to the AniList entry -- surrogates decode directly,
real ids resolve via the Fribb reverse index.

This module is pure (no Kodi deps) and offline: any AniList media fetch happens
in the caller (the resolution layer), never here.
"""
from resources.lib import season_map

# Surrogates live far above any real TMDB id so they can never collide and are
# O(1) recognizable on the way back in. AniList ids occupy [BASE, BASE+MAL_TAG);
# MAL ids occupy [BASE+MAL_TAG, ...). Both id spaces sit well under MAL_TAG today.
SURROGATE_BASE = 900_000_000
MAL_TAG = 400_000_000


def _intable(value):
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def is_surrogate(tmdb_id):
    """True if tmdb_id is one of our helper-owned surrogate ids."""
    try:
        return int(tmdb_id) >= SURROGATE_BASE
    except (TypeError, ValueError):
        return False


def encode_surrogate(kind, src_id):
    """Encode an AniList/MAL id into a stable surrogate tmdb_id.

    kind is 'anilist' or 'mal'. Raises ValueError if the source id is too large
    to keep the AniList/MAL sub-ranges disjoint.
    """
    src = int(src_id)
    if src < 0 or src >= MAL_TAG:
        raise ValueError("id %s out of surrogate range" % src)
    if kind == "mal":
        return SURROGATE_BASE + MAL_TAG + src
    return SURROGATE_BASE + src


def decode_surrogate(tmdb_id):
    """Decode a surrogate tmdb_id to (kind, src_id) -> ('anilist'|'mal', int)."""
    val = int(tmdb_id)
    if val >= SURROGATE_BASE + MAL_TAG:
        return "mal", val - SURROGATE_BASE - MAL_TAG
    return "anilist", val - SURROGATE_BASE


def to_tmdb_id(anilist_id=None, mal_id=None):
    """Forward map AniList/MAL -> a skin-facing tmdb_id.

    Returns the real Fribb TMDB id when mapped, else a stable surrogate (AniList
    id preferred, MAL fallback). Returns None only when neither id is given.
    """
    tmdb_id, _season = season_map.tmdb_lookup(anilist_id=anilist_id, mal_id=mal_id)
    if tmdb_id:
        return int(tmdb_id)
    if anilist_id is not None and _intable(anilist_id):
        return encode_surrogate("anilist", anilist_id)
    if mal_id is not None and _intable(mal_id):
        return encode_surrogate("mal", mal_id)
    return None


def reverse_ids(tmdb_id, season=None):
    """Offline reverse map: tmdb_id (+season) -> {'anilist', 'mal'} or None.

    Surrogates decode directly with no lookup. Real tmdb_ids resolve via the
    Fribb reverse index; for a multi-cour franchise the season picks the cour
    (matching the skin's TMDB season axis first, then the TVDB axis), else the
    lowest-season/base cour. No network: the AniList media fetch is the caller's
    job (resolution layer).
    """
    if tmdb_id is None or not _intable(tmdb_id):
        return None
    val = int(tmdb_id)
    if is_surrogate(val):
        kind, src = decode_surrogate(val)
        return {"anilist": src if kind == "anilist" else None,
                "mal": src if kind == "mal" else None}
    members = season_map.members_for_tmdb(val)
    if not members:
        # Monolith fallback: the TV entry (One Piece) lives in the forward by_mal
        # index, NOT tvdb_members, so members_for_tmdb misses it. Reverse the forward
        # index instead -- otherwise the skin's tmdb_id Play params resolve to nothing
        # and the Play button hangs with an empty result.
        flat = season_map.ids_for_tmdb(val)
        if flat and (flat.get("mal") is not None or flat.get("anilist") is not None):
            return {"anilist": flat.get("anilist"), "mal": flat.get("mal")}
        return None
    chosen = _pick_member(members, season)
    return {"anilist": chosen.get("anilist"), "mal": chosen.get("mal")}


def _pick_member(members, season):
    """Pick the franchise cour matching season, else the base/lowest-season cour."""
    if season is not None and _intable(season):
        want = int(season)
        for member in members:
            if member.get("tmdb_season") == want:
                return member
        for member in members:
            if member.get("season") == want:
                return member
    return min(members, key=lambda m: (m.get("season") or 1))


def resolve_mal_id(params, client):
    """Resolve inbound skin params to the helper's internal MAL id.

    Resolution order:
      1. explicit `mal_id` (8nime's current inbound key) -- wins outright,
      2. `tmdb_id` reverse map: our surrogate decodes directly; a real Fribb id
         resolves via the reverse index (+ season), fetching the AniList entry
         when only an anilist_id is known,
      3. fall back to the AniList client's own resolver (anilist_id / query).

    Person/staff routes (crew_in_*) do NOT use this -- their tmdb_id slot carries
    an AniList staff id, not a media id, so they read it directly.
    """
    val = params.get("mal_id")
    if val is not None and str(val).isdigit():
        return int(val)
    tmdb_id = params.get("tmdb_id")
    if tmdb_id is not None and _intable(tmdb_id):
        ids = reverse_ids(tmdb_id, params.get("season"))
        if ids:
            if ids.get("mal") is not None:
                return int(ids["mal"])
            anilist_id = ids.get("anilist")
            if anilist_id is not None:
                media = client.get_media(anilist_id=int(anilist_id))
                if media and media.get("idMal"):
                    return int(media["idMal"])
    return client.resolve_mal_id(params)
