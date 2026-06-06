# -*- coding: utf-8 -*-
"""Direct FANime F (animixplay / echovideo) episode resolver.

Mirrors what plugin.video.fanimef does internally — search animixplay.la, read a
series' episode list from its ``epslistplace`` JSON, then resolve the echovideo
``getSources`` endpoint to the final HLS (m3u8) — but WITHOUT fanimef's two
problems:

  * Its ``Play_All`` builds a per-episode source list then resolves the *last*
    loop value, ignoring the user's selection (always plays the wrong episode).
  * It only reaches search via a Kodi keyboard prompt (no query param).

So we replicate the scrape ourselves and return the stream URL directly. The
helper sets it on the resolved ListItem (no second plugin hop — episode OSD
metadata sticks, and there is no picker / keyboard).

Unlike WNT2 (where we delegate stream extraction back to the addon), fanimef's
final source is a plain m3u8 from ``getSources``, so we resolve it here.

The scrape core takes no Kodi deps, so it can be exercised head-less in a
dry-run. Episode keys in ``epslistplace`` are 0-indexed ("0" == episode 1).
"""
import json
import re

import requests

from resources.lib.wnt2 import best_series  # generic (candidates, *titles) matcher

FANIMEF_PLUGIN = "plugin.video.fanimef"
BASE_URL = "https://animixplay.la"
API_URL = BASE_URL + "/api/search"
SOURCE_API = "https://play2.echovideo.ru"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
# Stream host wants the echovideo origin; mirror fanimef's play_item headers.
MEDIA_REFERER = SOURCE_API + "/"
MEDIA_UA = _UA

# Search results repeat each <a href="/v1/slug" title="Name"> twice (poster +
# name); dedupe by href. A "-dub" slug is the dubbed variant of the same show.
_LI_RE = re.compile(r'<a href="(/v1/[^"]+)"\s+title="([^"]+)"')
_EPS_RE = re.compile(r'id="epslistplace"[^>]*>(.*?)</div>', re.DOTALL)


def _headers(referer=None):
    return {
        "Origin": BASE_URL,
        "x-requested-with": "XMLHttpRequest",
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer or (BASE_URL + "/"),
    }


def search_series(query, session=None, dub=False):
    """Return [(href, title), ...] for a search, filtered to the requested lang."""
    session = session or requests.session()
    resp = session.post(
        API_URL,
        data={"q2": query, "origin": "1", "d": "gogoanime.tel"},
        headers=_headers(BASE_URL + "/?p=movie"),
        timeout=15,
    )
    try:
        html = (resp.json() or {}).get("result", "")
    except ValueError:
        return []
    seen, out = set(), []
    for href, title in _LI_RE.findall(html):
        if href in seen:
            continue
        seen.add(href)
        if href.endswith("-dub") != bool(dub):
            continue
        out.append((href, title))
    return out


def episode_list(series_href, session=None):
    """Return {episode_number: embed_url} for a series (keys 0-indexed -> 1-based)."""
    session = session or requests.session()
    url = series_href if series_href.startswith("http") else BASE_URL + series_href
    html = session.get(url, headers=_headers(), timeout=15).text
    m = _EPS_RE.search(html)
    if not m:
        return {}
    try:
        content = json.loads(m.group(1).strip())
    except ValueError:
        return {}
    eps = {}
    for key, val in content.items():
        if key.isdigit() and isinstance(val, str):
            eps[int(key) + 1] = val
    return eps


def resolve_stream(embed_url, session=None):
    """Resolve an episode embed URL to (m3u8_url, tracks) via echovideo getSources."""
    session = session or requests.session()
    if "/embed-3/" in embed_url:
        key = embed_url.rsplit("/embed-3/", 1)[-1]
    else:
        key = embed_url.rsplit("/", 1)[-1]
    js = session.get(
        SOURCE_API + "/embed-3/getSources?id=" + key,
        headers=_headers(SOURCE_API + "/"),
        timeout=15,
    ).json()
    src = js.get("sources")
    # fanimef treats `sources` as a string; tolerate a list of {file}/str too.
    if isinstance(src, list):
        first = src[0] if src else None
        src = first.get("file") if isinstance(first, dict) else first
    return src, js.get("tracks")


def resolve_episode(titles, number, dub=False, min_score=0.55):
    """Resolve episode ``number`` to a stream.

    ``titles`` is an ordered list of search candidates (anime-planet slug first,
    then AniList romaji/english). Returns (result, debug) where result is
    {stream, tracks, referer, ua} or None.
    """
    try:
        number = int(number)
    except (TypeError, ValueError):
        return None, {"error": "bad episode"}
    session = requests.session()
    debug = {"tried": [], "series": None, "score": 0.0}
    for title in [t for t in titles if t]:
        results = search_series(title, session, dub=dub)
        debug["tried"].append({"query": title, "results": len(results)})
        if not results:
            continue
        link, name, score = best_series(results, *titles)
        if not link or score < min_score:
            debug["score"] = max(debug["score"], score)
            continue
        debug.update({"series": name, "series_url": link, "score": score})
        eps = episode_list(link, session)
        debug["episodes"] = len(eps)
        embed = eps.get(number)
        if not embed:
            continue
        stream, tracks = resolve_stream(embed, session)
        if stream:
            debug["stream"] = stream
            return (
                {"stream": stream, "tracks": tracks, "referer": MEDIA_REFERER, "ua": MEDIA_UA},
                debug,
            )
    return None, debug
