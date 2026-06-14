# -*- coding: utf-8 -*-
"""Direct WatchNixtoons2 episode resolver.

WNT2 has no cross-database IDs (wcostream is a pirate index with its own
slugs), so an episode cannot be located by mal_id/anilist_id. Instead we
replicate exactly what the WNT2 addon itself does -- search wcostream for the
series, then read its episode list -- and return the episode *page* URL. The
helper then hands that page URL straight to WNT2's own ``actionResolve`` via
``setResolvedUrl``, so playback is direct (no picker / middle screen) and the
fragile stream-extraction stays inside WNT2 where it belongs.

The network layer mirrors WNT2/lib/network.py: plain ``requests`` with
``verify=False``, a browser User-Agent, and a TLSv1.2 -> TLSv1.1 adapter
fallback when Cloudflare answers 403. No cloudscraper.

The scraping core (``search_series``/``episode_list``/``resolve_episode_url``)
takes ``base_url`` as an argument and imports nothing from Kodi, so it can be
exercised head-less in a dry-run. Only ``default_base_url`` touches xbmc.
"""
import difflib
import json
import os
import re
import ssl
import time
from urllib.parse import urlencode, urlparse

import requests
import xbmc
from resources.lib import debuglog
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

WNT2_PLUGIN = "plugin.video.watchnixtoons2"

# Mirror WNT2/lib/constants.py exactly.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
_DOMAINS = {0: "www.wcostream.tv", 1: "www.wcoflix.tv", 2: "www.wcoforever.net"}

# wcostream SITE_SETTINGS, copied verbatim (slashes unescaped for Python re).
_SERIES_RE = re.compile(
    r'<a href="(?P<link>[^"]+)"\s*title="(?P<name>[^"]+)">\s*<img\s*src="(?P<img>[^"]+)'
)
_SERIES_START, _SERIES_END = "aramamotoru", "cizgiyazisi"

_EPISODE_RE = re.compile(
    r'<a href="(?P<link>[^"]+).*?(data-lang="(?P<type>[^"]+)")?>(?:<span>)?(?P<name>[^<]+)'
)
_EPISODE_START, _EPISODE_END = 'name="pid"', "<!--CAT PAGE"

# Integer episode number only -- the negative lookahead (no trailing digit or dot)
# drops fractional specials ("Episode 12.5", "Episode 24.9") so they don't collide
# with the real episode 12/24 (without it, \d+ backtracks and matches "1" of "12.5").
_EP_NUM_RE = re.compile(r"episode\s+0*(\d+)(?![\d.])", re.IGNORECASE)

# wcostream tags a season three different ways across (and within) shows:
#   "Season N Episode M"      -> Slime, Re:Zero
#   "Nth Season"              -> occasional
#   sequel roman numeral      -> "Mushoku Tensei II ..." (numbering restarts)
# Season 1 carries NO marker. _episode_season() checks these widest-first.
_SEASON_NUM_RE = re.compile(r"season[\s\-]+0*(\d+)", re.IGNORECASE)
_ORDINAL_SEASON_RE = re.compile(r"\b0*(\d+)(?:st|nd|rd|th)\s+season", re.IGNORECASE)
_ROMAN_SEQUEL_RE = re.compile(r"\b(i{2,3}|iv)\b")
_ROMAN_SEQUEL = {"ii": 2, "iii": 3, "iv": 4}
_PART_RE = re.compile(r"\bpart\s+0*(\d+)", re.IGNORECASE)
# Trailing "(Season N )?(Part N )?Episode M" + the English Sub/Dub suffix, peeled
# off an episode name to leave its series-name prefix (empty for bare "Episode N").
_LANG_SUFFIX_RE = re.compile(r"\s*(?:english\s+)?(?:sub(?:bed)?|dub(?:bed)?)\s*$", re.IGNORECASE)
_EP_TAIL_RE = re.compile(
    r"(?:season\s+\d+\s+)?(?:part\s+\d+\s+)?episode\s+[\d.]+\s*[ab]?\s*$", re.IGNORECASE
)
# Side content that must never win over a real numbered episode of the season.
_SIDE_RE = re.compile(
    r"\b(ova|oad|ona|movie|film|special|recap|digression|picture\s+drama|"
    r"preview|trailer|nced|ncop|bonus|short)\b",
    re.IGNORECASE,
)

# wcostream keeps movies on a separate /movie-list page (NOT in series search).
# makeMoviesSearchCatalog slices from '"ddmcc"' and substring-filters by query.
MOVIE_LIST_PATH = "/movie-list"
_MOVIE_RE = re.compile(r'<a href="([^"]+).*?>([^<]+)')
_LANG_NOISE = re.compile(r"\b(english|dubbed|subbed|dub|sub|movie|ova)\b", re.IGNORECASE)


class _TLSAdapter(HTTPAdapter):
    def __init__(self, ssl_version, *a, **k):
        self._ssl_version = ssl_version
        super().__init__(*a, **k)

    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_version=self._ssl_version,
        )


def _request(session, url, data=None, referer=None):
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml,"
        "application/json;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Cache-Control": "no-cache",
    }
    if referer:
        headers["Referer"] = referer

    uri = urlparse(url)
    domain = uri.scheme + "://" + uri.netloc
    adapters = [_TLSAdapter(ssl.PROTOCOL_TLSv1_2), _TLSAdapter(ssl.PROTOCOL_TLSv1_1)]

    status, i, resp = 0, 0, None
    while status not in (200, 204) and i < 2:
        if data:
            resp = session.post(url, data=data, headers=headers, verify=False, timeout=10)
        else:
            resp = session.get(url, headers=headers, verify=False, timeout=10)
        status = resp.status_code
        if status not in (200, 204):
            if status == 403 and resp.headers.get("server", "") == "cloudflare":
                session.mount(domain, adapters[i])
            i += 1
    return resp


def _slice(html, start, end):
    i = html.find(start)
    if i == -1:
        return ""
    j = html.find(end, i)
    return html[i:j] if j != -1 else html[i:]


def _norm(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def search_series(query, base_url, session=None):
    """Return [(link, name), ...] for a series search, best-first as the site lists them."""
    session = session or requests.session()
    resp = _request(
        session,
        base_url + "/search",
        data={"catara": query, "konuara": "series"},
        referer=base_url + "/",
    )
    seg = _slice(resp.text, _SERIES_START, _SERIES_END)
    return [(m.group("link"), m.group("name")) for m in _SERIES_RE.finditer(seg)]


# Disk-backed parsed-episode-list cache {url: {"ts", "eps"}}. resolve_episode_url
# fetches this on EVERY play (even when the series-page URL is already cached), and a
# long-runner's page (One Piece, ~1000 eps) is expensive to download + parse. Persisting
# the parsed list means the heavy work runs at most once per series per TTL -- and
# SURVIVES restarts -- so resuming the next episode (or replaying) is an instant match.
_EPISODE_LIST_CACHE = None  # lazy {url: {"ts": float, "eps": [[link, name, type], ...]}}
_EPISODE_LIST_TTL = 21600   # 6h -- a series' list only changes when a new episode airs;
# a cached-list MISS forces a refresh (see resolve_episode_url), so a just-aired episode
# is still picked up immediately rather than waiting out the TTL.


def _episode_list_cache_path():
    try:
        import xbmcvfs

        from resources.lib.constants import ADDON_ID

        base = xbmcvfs.translatePath("special://profile/addon_data/%s/" % ADDON_ID)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".8nime")
    return os.path.join(base, "wnt2_episodes.json")


def _episode_list_cache():
    global _EPISODE_LIST_CACHE
    if _EPISODE_LIST_CACHE is None:
        _EPISODE_LIST_CACHE = {}
        try:
            path = _episode_list_cache_path()
            if os.path.exists(path):
                with open(path, encoding="utf-8") as handle:
                    _EPISODE_LIST_CACHE = json.load(handle) or {}
        except Exception:
            _EPISODE_LIST_CACHE = {}
    return _EPISODE_LIST_CACHE


def _episode_list_cache_save():
    try:
        path = _episode_list_cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.tmp.%d" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_EPISODE_LIST_CACHE, handle)
        os.replace(tmp, path)
    except Exception:
        pass


def reset_episode_list_cache():
    """Test hook / refresh: drop the parsed-episode-list cache (reloads from disk)."""
    global _EPISODE_LIST_CACHE
    _EPISODE_LIST_CACHE = None


def episode_list(series_url, base_url, session=None, force_refresh=False):
    """Return [(link, name, lang_type), ...] for a series page (newest-first as on site).

    Disk-cached for 6h, keyed by the resolved page URL (see the cache note above): the
    heavy fetch + parse of a long-runner's page runs at most once per series per window
    and survives restarts. ``force_refresh`` bypasses the cache (used to self-heal a
    stale list that's missing a just-aired episode)."""
    url = series_url if series_url.startswith("http") else base_url + series_url
    cache = _episode_list_cache()
    if not force_refresh:
        entry = cache.get(url)
        if entry and (time.time() - (entry.get("ts") or 0)) < _EPISODE_LIST_TTL:
            return [tuple(e) for e in entry.get("eps") or []]
    session = session or requests.session()
    resp = _request(session, url)
    seg = _slice(resp.text, _EPISODE_START, _EPISODE_END)
    eps = [
        (m.group("link"), m.group("name"), m.group("type"))
        for m in _EPISODE_RE.finditer(seg)
    ]
    if eps:  # never cache an empty parse (transient fetch failure / stale slug)
        cache[url] = {"ts": time.time(), "eps": [list(e) for e in eps]}
        _episode_list_cache_save()
    return eps


def _pair_score(n, t):
    """Score two normalized titles. Exact == 1.0; containment scored above fuzzy
    ratio so 'Naruto' doesn't lose to 'Naruto Shippuden' for canonical 'Naruto'."""
    if not n or not t:
        return 0.0
    if n == t:
        return 1.0
    if t in n or n in t:
        return 0.9 + 0.1 * (min(len(t), len(n)) / max(len(t), len(n)))
    return difflib.SequenceMatcher(None, n, t).ratio()


def best_series(candidates, *titles):
    """Pick the candidate whose name best matches any supplied title.

    Returns (link, name, score) or (None, None, 0.0).
    """
    norm_titles = [_norm(t) for t in titles if t]
    if not norm_titles:
        return None, None, 0.0
    best, best_name, best_score = None, None, 0.0
    for link, name in candidates:
        n = _norm(name)
        score = max((_pair_score(n, t) for t in norm_titles), default=0.0)
        if score > best_score:
            best, best_name, best_score = link, name, score
    return best, best_name, best_score


def _episode_number(name):
    m = _EP_NUM_RE.search(name or "")
    return int(m.group(1)) if m else None


def _episode_season(name):
    """wcostream season ordinal for an episode name (1 when unmarked)."""
    text = name or ""
    m = _SEASON_NUM_RE.search(text) or _ORDINAL_SEASON_RE.search(text)
    if m:
        return int(m.group(1))
    m = _ROMAN_SEQUEL_RE.search(text.lower())
    if m:
        return _ROMAN_SEQUEL[m.group(1).lower()]
    return 1


def _episode_lang(name, lang_attr):
    """sub/dub for an episode: the data-lang attribute when present, else parsed
    from the title ("... English Dubbed"). None when neither tells us."""
    if lang_attr:
        return lang_attr
    low = (name or "").lower()
    if "dub" in low:
        return "dub"
    if "sub" in low:
        return "sub"
    return None


def _episode_prefix(name):
    """The series-name portion of an episode title, normalized (empty for a bare
    "Episode N"). 'Mushoku Tensei II: ... Episode 1 English Dubbed' ->
    'mushoku tensei ii jobless reincarnation'."""
    stripped = _LANG_SUFFIX_RE.sub("", name or "").strip()
    return _norm(_EP_TAIL_RE.sub("", stripped))


def _matches_show(name, titles, min_score=0.6):
    """True when an episode is a real episode of THIS series: its name-prefix is
    bare (just "Episode N") or fuzzily matches one of the show's titles. Filters
    out embedded spin-offs ('Visions of Coleus Episode 1' on the Slime page)."""
    prefix = _episode_prefix(name)
    if not prefix:
        return True
    norm_titles = [_norm(t) for t in titles if t]
    return max((_pair_score(prefix, t) for t in norm_titles), default=0.0) >= min_score


def match_episode(episodes, number, season=1, offset=0, lang="sub", titles=None):
    """Best episode-page (link, name, type) for a season+episode, or None.

    wcostream aggregates every season -- plus OVAs, movies and spin-offs -- of a
    series into one newest-first list, so a bare episode-number match plays the
    NEWEST season (the original bug: Slime S1 ep1 -> Season 4 ep1). Each candidate
    is scored, in priority order, by: how close its season tag is to the requested
    ``season``; whether it's a real episode (not side content); whether it belongs
    to this show (not an embedded spin-off); the requested ``lang``; continuous
    numbering over a "Part N" re-upload; and earliest listing.

    ``offset`` is the episode count of earlier cours in the SAME season -- wcostream
    usually numbers a season's cours continuously (Slime "Season 2 Part 2 ep1" ==
    "Season 2 Episode 13"), so the offset-applied number is tried before the raw
    cour-local one.
    """
    season = int(season or 1)
    titles = titles or []
    target = number + int(offset or 0)

    indexed = []
    for idx, (link, name, lang_attr) in enumerate(episodes):
        epn = _episode_number(name)
        if epn is None:
            continue
        indexed.append(
            (
                idx,
                link,
                name,
                _episode_lang(name, lang_attr),
                epn,
                _episode_season(name),
                bool(_SIDE_RE.search(name or "")),
                _matches_show(name, titles),
                bool(_PART_RE.search(name or "")),
            )
        )

    def sort_key(c):
        _idx, _link, _name, c_lang, _epn, c_season, c_side, c_show, c_part = c
        return (
            abs(c_season - season),                 # nearest requested season
            0 if not c_side else 1,                 # real episode over side content
            0 if c_show else 1,                     # this show, not a spin-off
            0 if (not c_lang or c_lang == lang) else 1,  # requested language
            0 if not c_part else 1,                 # continuous numbering over a Part-N reupload
            -_idx,                                  # earliest listing on ties
        )

    for num in (target, number) if target != number else (number,):
        pool = [c for c in indexed if c[4] == num]
        if pool:
            best = min(pool, key=sort_key)
            return (best[1], best[2], best[3])
    return None


def movie_list(base_url, session=None):
    """Return [(url, name), ...] from wcostream's /movie-list page."""
    session = session or requests.session()
    html = _request(session, base_url + MOVIE_LIST_PATH).text
    i = html.find('"ddmcc"')
    if i == -1:
        return []
    seg = html[i : html.find("/ul></ul", i)]
    return _MOVIE_RE.findall(seg)


def resolve_movie_url(titles, base_url, lang="sub", min_score=0.6):
    """Find a wcostream movie-page URL by title (movies live on /movie-list, not
    series search). Returns (movie_url, debug). The page URL plays directly via
    WNT2 actionResolve, just like an episode page."""
    session = requests.session()
    movies = movie_list(base_url, session)
    debug = {"candidates": len(movies), "movie": None, "score": 0.0}
    if not movies:
        return None, debug
    norm_titles = [_norm(t) for t in titles if t]
    if not norm_titles:
        return None, debug
    scored = []
    for url, name in movies:
        # Strip the "English Dubbed/Subbed"/"Movie" noise before matching.
        clean = _norm(_LANG_NOISE.sub(" ", name))
        score = max((_pair_score(clean, t) for t in norm_titles), default=0.0)
        scored.append((score, url, name))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0]
    debug.update({"movie": scored[0][2], "score": top_score})
    if top_score < min_score:
        return None, debug
    # Among the near-best matches, prefer the requested sub/dub variant.
    near = [s for s in scored if top_score - s[0] < 0.02]
    pref = [s for s in near if ("subbed" in s[2].lower()) == (lang == "sub")]
    chosen = (pref or near)[0]
    debug.update({"movie": chosen[2], "movie_url": chosen[1], "score": chosen[0]})
    return chosen[1], debug


# --- WNT2-only durable resolve helpers (scoped to wcostream; never touched by the
# --- Otaku / Fanime playback paths, which don't import resolve_episode_url) -------
# wcostream search throttles rapid queries (the productive bare-name query then
# intermittently returns 0). Two mitigations, both confined to this module:
#   * a tiny persistent cache of resolved series-page URLs, so repeat episode plays
#     of the same show skip search entirely;
#   * one retry pass with a short backoff when a whole search attempt comes up empty.
_SEARCH_RETRY_DELAY = 3.0
_SERIES_CACHE = None  # lazy {normalized_title: series_page_url}


def _series_cache_path():
    try:
        import xbmcvfs

        from resources.lib.constants import ADDON_ID

        base = xbmcvfs.translatePath("special://profile/addon_data/%s/" % ADDON_ID)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".8nime")
    return os.path.join(base, "wnt2_series.json")


def _series_cache():
    global _SERIES_CACHE
    if _SERIES_CACHE is None:
        _SERIES_CACHE = {}
        try:
            path = _series_cache_path()
            if os.path.exists(path):
                with open(path, encoding="utf-8") as handle:
                    _SERIES_CACHE = json.load(handle) or {}
        except Exception:
            _SERIES_CACHE = {}
    return _SERIES_CACHE


def _series_cache_get(titles):
    cache = _series_cache()
    for title in titles:
        key = _norm(title)
        if key and cache.get(key):
            return cache[key]
    return None


def _series_cache_put(titles, series_url):
    if not series_url:
        return
    cache = _series_cache()
    changed = False
    for title in titles:
        key = _norm(title)
        if key and cache.get(key) != series_url:
            cache[key] = series_url
            changed = True
    if not changed:
        return
    try:
        path = _series_cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.tmp.%d" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(cache, handle)
        os.replace(tmp, path)
    except Exception:
        pass


def reset_series_cache():
    """Test hook: drop the in-process series-page cache."""
    global _SERIES_CACHE
    _SERIES_CACHE = None


def resolve_episode_url(titles, number, base_url, lang="sub", min_score=0.55,
                        season=1, offset=0):
    """Find the wcostream episode-page URL for episode ``number`` of a series.

    ``titles`` is an ordered list of search candidates (anime-planet slug first,
    then AniList romaji/english). ``season``/``offset`` make the episode match
    season-aware (see match_episode): wcostream lists every season of a series in
    one page, so the AniList cour's franchise season + intra-season episode offset
    are needed to pin the right one. Returns (episode_url, debug) where debug is a
    dict describing what matched, for logging / dry-run output.
    """
    session = requests.session()
    titles = [t for t in titles if t]
    debug = {"tried": [], "series": None, "score": 0.0, "episodes": 0,
             "season": season, "offset": offset}

    # Cached series page first: repeat plays of the same show skip search entirely
    # (so wcostream's search throttle is only ever hit on the first resolve). A stale
    # entry yields an empty episode list / no match and harmlessly falls through to a
    # fresh search below, which overwrites it.
    cached_url = _series_cache_get(titles)
    if cached_url:
        _t = time.time()
        eps = episode_list(cached_url, base_url, session)
        _t_fetch = time.time() - _t
        _t = time.time()
        hit = match_episode(eps, number, season=season, offset=offset,
                            lang=lang, titles=titles)
        debuglog.dbg("wnt2 cached series: episode_list %d eps in %.2fs, match in %.2fs hit=%s" % (len(eps), _t_fetch, time.time() - _t, bool(hit)))
        if not hit:
            # Cached list may be stale (a just-aired episode) -> refetch once fresh
            # before giving up, so the newest episode self-heals without a TTL wait.
            eps = episode_list(cached_url, base_url, session, force_refresh=True)
            hit = match_episode(eps, number, season=season, offset=offset,
                                lang=lang, titles=titles)
            debuglog.dbg("wnt2 cached series REFRESH: %d eps, hit=%s" % (len(eps), bool(hit)))
        if hit:
            debug.update({"series_url": cached_url, "cached": True, "episodes": len(eps),
                          "episode": {"name": hit[1], "type": hit[2], "url": hit[0]}})
            return hit[0], debug

    # Search, with one retry pass: wcostream's search intermittently returns 0 for the
    # productive bare-name query when throttled, so a single backoff+retry turns that
    # transient miss into a hit instead of a hard "no match".
    for attempt in range(2):
        for title in titles:
            _t = time.time()
            results = search_series(title, base_url, session)
            debuglog.dbg("wnt2 search '%s' -> %d results in %.2fs" % (title, len(results), time.time() - _t))
            debug["tried"].append({"query": title, "results": len(results), "attempt": attempt})
            if not results:
                continue
            link, name, score = best_series(results, *titles)
            if not link or score < min_score:
                debug["score"] = max(debug["score"], score)
                continue
            debug.update({"series": name, "series_url": link, "score": score})
            _t = time.time()
            eps = episode_list(link, base_url, session)
            _t_fetch = time.time() - _t
            _t = time.time()
            hit = match_episode(eps, number, season=season, offset=offset,
                                lang=lang, titles=titles)
            debuglog.dbg("wnt2 search series: episode_list %d eps in %.2fs, match in %.2fs hit=%s" % (len(eps), _t_fetch, time.time() - _t, bool(hit)))
            if hit:
                debug["episode"] = {"name": hit[1], "type": hit[2], "url": hit[0]}
                _series_cache_put(titles, link)
                return hit[0], debug
        if attempt == 0:
            time.sleep(_SEARCH_RETRY_DELAY)
    return None, debug


def default_base_url():
    """wcostream base URL from the installed WNT2 addon's domain setting."""
    import xbmcaddon

    try:
        idx = int(xbmcaddon.Addon(WNT2_PLUGIN).getSetting("baseURL"))
    except Exception:
        idx = 0
    return "https://" + _DOMAINS.get(idx, _DOMAINS[0])


def actionresolve_url(episode_url):
    """plugin:// URL that drives WNT2's own resolver for direct playback."""
    return "plugin://{0}/?{1}".format(
        WNT2_PLUGIN, urlencode({"action": "actionResolve", "url": episode_url})
    )
