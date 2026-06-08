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
import re
import ssl
from urllib.parse import urlencode, urlparse

import requests
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

_EP_NUM_RE = re.compile(r"episode\s+0*(\d+)", re.IGNORECASE)

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


def episode_list(series_url, base_url, session=None):
    """Return [(link, name, lang_type), ...] for a series page (newest-first as on site)."""
    session = session or requests.session()
    url = series_url if series_url.startswith("http") else base_url + series_url
    resp = _request(session, url)
    seg = _slice(resp.text, _EPISODE_START, _EPISODE_END)
    return [
        (m.group("link"), m.group("name"), m.group("type"))
        for m in _EPISODE_RE.finditer(seg)
    ]


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


def match_episode(episodes, number, lang="sub"):
    """Return (link, name, type) for episode ``number``, preferring ``lang``."""
    hits = [(l, n, t) for (l, n, t) in episodes if _episode_number(n) == number]
    if not hits:
        return None
    if lang:
        for l, n, t in hits:
            if not t or t == lang:
                return (l, n, t)
    return hits[0]


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


def resolve_episode_url(titles, number, base_url, lang="sub", min_score=0.55):
    """Find the wcostream episode-page URL for episode ``number`` of a series.

    ``titles`` is an ordered list of search candidates (anime-planet slug first,
    then AniList romaji/english). Returns (episode_url, debug) where debug is a
    dict describing what matched, for logging / dry-run output.
    """
    session = requests.session()
    debug = {"tried": [], "series": None, "score": 0.0, "episodes": 0}
    for title in [t for t in titles if t]:
        results = search_series(title, base_url, session)
        debug["tried"].append({"query": title, "results": len(results)})
        if not results:
            continue
        link, name, score = best_series(results, *titles)
        if not link or score < min_score:
            debug["score"] = max(debug["score"], score)
            continue
        debug.update({"series": name, "series_url": link, "score": score})
        eps = episode_list(link, base_url, session)
        debug["episodes"] = len(eps)
        hit = match_episode(eps, number, lang)
        if hit:
            debug["episode"] = {"name": hit[1], "type": hit[2], "url": hit[0]}
            return hit[0], debug
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
