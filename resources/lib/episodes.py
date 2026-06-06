# -*- coding: utf-8 -*-
"""Real per-episode thumbnails.

AniList exposes Crunchyroll episode stills via `streamingEpisodes`
({title, thumbnail, site}). Titles look like "Episode 24 - Succession", so the
episode number is parsed from the title. Numbering is global across a franchise
(cour 2 continues from cour 1), hence callers pass an offset for per-cour views.
"""
import re

_EP_NUM_RE = re.compile(r"(?:episode|ep\.?|e)\s*#?\s*(\d+)", re.IGNORECASE)


def thumbnails_from_media(media):
    """Return {episode_number: thumbnail_url} parsed from media.streamingEpisodes."""
    if not media:
        return {}
    result = {}
    fallback_order = []
    for entry in media.get("streamingEpisodes") or []:
        thumb = entry.get("thumbnail")
        if not thumb:
            continue
        title = entry.get("title") or ""
        match = _EP_NUM_RE.search(title)
        if match:
            result[int(match.group(1))] = thumb
        else:
            fallback_order.append(thumb)

    # If no titles carried numbers, fall back to source order (1-indexed).
    if not result and fallback_order:
        for idx, thumb in enumerate(fallback_order, start=1):
            result[idx] = thumb
    return result


def thumb_for_episode(thumbs, episode, offset=0):
    """Strict global lookup: local episode -> global episode number.

    No local fallback: when several cours share one global streamingEpisodes list,
    a fallback to thumbs.get(ep) makes later cours reuse earlier cours' images.
    """
    if not thumbs:
        return None
    return thumbs.get(offset + int(episode or 1))


def streaming_covers(thumbs, total, offset=0, ratio=0.6):
    """True when the (shared/global) list actually has stills for this cour's range."""
    if not thumbs or not total or total < 1:
        return False
    have = sum(1 for ep in range(1, int(total) + 1) if (offset + ep) in thumbs)
    return have >= max(1, int(total * ratio))


def signature(thumbs):
    """Order-independent signature of a thumbnail set, to detect shared lists."""
    return tuple(sorted(v for v in thumbs.values() if v)) if thumbs else ()
