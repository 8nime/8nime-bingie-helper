# -*- coding: utf-8 -*-
from urllib.parse import urlencode

import xbmc
import xbmcaddon

from resources.lib.constants import ADDON_ID, PLUGIN_URL
from resources.lib.titles import title_for_media

ADDON = xbmcaddon.Addon()

TMDB_HELPER_ID = "plugin.video.tmdb.bingie.helper"

PLAYBACK_OTAKU = "otaku"
PLAYBACK_WATCHNIXTOONS2 = "watchnixtoons2"
PLAYBACK_FANIME_F = "fanime_f"

PLUGIN_IDS = {
    PLAYBACK_OTAKU: "plugin.video.otaku",
    PLAYBACK_WATCHNIXTOONS2: "plugin.video.watchnixtoons2",
    # Real addon id is plugin.video.fanimef (FANime F, OldManJax/animaniac repo) —
    # NOT plugin.video.fanime_f, which never existed and dead-ended every click.
    PLAYBACK_FANIME_F: "plugin.video.fanimef",
}


# Default to WatchNixtoons2: it (and Fanime) resolve episodes + movies +
# specials directly, whereas Otaku's free sources are broken upstream. This
# matches the settings.xml <default>. The setting still wins when the user picks
# a provider via Change provider.
_DEFAULT_PLAYBACK = PLAYBACK_WATCHNIXTOONS2


def get_playback_plugin():
    value = ADDON.getSetting("playback_plugin") or _DEFAULT_PLAYBACK
    return PLUGIN_IDS.get(value, PLUGIN_IDS[_DEFAULT_PLAYBACK])


def get_playback_key():
    value = ADDON.getSetting("playback_plugin") or _DEFAULT_PLAYBACK
    if value in PLUGIN_IDS:
        return value
    return _DEFAULT_PLAYBACK


def is_addon_installed(addon_id):
    # Use HasAddon rather than xbmcaddon.Addon(): instantiating Addon() for an
    # absent id makes Kodi log "Unknown addon id ..." at the C++ level even when
    # the Python exception is caught, spamming the log on every check.
    return bool(xbmc.getCondVisibility("System.HasAddon({0})".format(addon_id)))


def flatten_seasons_enabled():
    """Match TMDb Bingie Helper Player → Flatten seasons when installed."""
    if not is_addon_installed(TMDB_HELPER_ID):
        return False
    try:
        return xbmcaddon.Addon(TMDB_HELPER_ID).getSettingBool("flatten_seasons")
    except Exception:
        value = (xbmcaddon.Addon(TMDB_HELPER_ID).getSetting("flatten_seasons") or "false").lower()
        return value == "true"


def helper_url(**params):
    """Build a plugin:// URL into this addon's own routes from query params."""
    return f"{PLUGIN_URL}/?{urlencode(params)}"


def browse_show_path(mal_id):
    """Bingie More Episodes browse root — seasons or flat list per TMDb helper setting."""
    if not mal_id:
        return None
    info = "flatseasons" if flatten_seasons_enabled() else "seasons"
    return helper_url(info=info, mal_id=str(mal_id), tmdb_type="tv")


def helper_play_url(mal_id, episode=None, is_movie=False, title=None):
    """Deferred play route — resolves to the configured plugin at click time."""
    params = {"info": "play", "mal_id": str(mal_id)}
    if episode:
        params["episode"] = str(episode)
    if is_movie:
        params["tmdb_type"] = "movie"
    if title:
        params["title"] = title
    return helper_url(**params)


def _watchnixtoons_search(title, search_type, episode=None):
    plugin = PLUGIN_IDS[PLAYBACK_WATCHNIXTOONS2]
    query = title
    if episode and search_type == "episodes":
        query = f"{title} Episode {episode}"
    # WatchNixtoons2 routes the search via actionSearchMenu -> actionCatalogSection
    # -> getCatalogProperty, which needs params['path'] to equal its
    # URL_PATHS['search'] == '/search' (WITH the leading slash) so CATALOG_FUNCS
    # dispatches to makeSearchCatalog. A bare 'search' falls through to
    # makeGenericCatalog, which does BASEURL + path -> 'wcostream.tvsearch' (bad
    # host); omitting path entirely raises KeyError: 'path'.
    params = {
        "action": "actionSearchMenu",
        "path": "/search",
        "searchType": search_type,
        "query": query,
    }
    return f"plugin://{plugin}/?{urlencode(params)}"


def _fanime_search(title, episode=None, is_movie=False):
    # FANime F (plugin.video.fanimef) takes NO query parameter: its router does
    # int(params['mode']) (so the old mode=search crashed it) and its search
    # (mode=8) always opens a Kodi keyboard for the user to type — there is no way
    # to pre-fill or defer the term. mode=8 also needs a non-empty `url`, or the
    # router falls through to the main menu. So all we can do is launch its
    # search; the title/episode can't be passed through. Best treated as a
    # bundled standalone addon rather than a click-to-play backend.
    plugin = PLUGIN_IDS[PLAYBACK_FANIME_F]
    return f"plugin://{plugin}/?mode=8&url=search"


def play_movie_path(media, title=None):
    mal_id = media.get("idMal") if media else None
    title = title or _title_from_media(media)
    plugin = get_playback_plugin()
    key = get_playback_key()

    if key == PLAYBACK_OTAKU:
        if mal_id:
            return f"plugin://{plugin}/play_movie/{mal_id}/"
        return None

    if not title:
        return None

    if key == PLAYBACK_WATCHNIXTOONS2:
        return _watchnixtoons_search(title, "movies")

    if key == PLAYBACK_FANIME_F:
        return _fanime_search(title, is_movie=True)

    return None


def play_episode_path(mal_id, episode, title=None, is_movie=False):
    plugin = get_playback_plugin()
    key = get_playback_key()

    if key == PLAYBACK_OTAKU:
        if is_movie and mal_id:
            return f"plugin://{plugin}/play_movie/{mal_id}/"
        if mal_id and episode:
            # No trailing slash: Otaku's PLAY route does payload.rsplit("/")
            # expecting exactly [mal_id, episode]. A trailing slash yields a 3rd
            # empty element -> "too many values to unpack". (play_movie/ keeps its
            # trailing slash because PLAY_MOVIE expects [mal_id, eps_watched].)
            return f"plugin://{plugin}/play/{mal_id}/{episode}"
        if mal_id:
            return f"plugin://{plugin}/animes/{mal_id}/"
        return None

    if not title:
        return None

    if key == PLAYBACK_WATCHNIXTOONS2:
        if is_movie:
            return _watchnixtoons_search(title, "movies")
        # Episode search ('{title} Episode N') rarely matches WNT2's episode-page
        # titles. A SERIES search reliably lands on the show (the path that works
        # navigating WNT2 by hand); WNT2's own Cloudflare-capable resolver then
        # plays the episode the user picks. We deliberately don't scrape wcostream
        # in the helper (plain requests would hit Cloudflare 403s).
        return _watchnixtoons_search(title, "series")

    if key == PLAYBACK_FANIME_F:
        return _fanime_search(title, episode=episode, is_movie=is_movie)

    return None


def resolve_play_path(media=None, mal_id=None, episode=None, title=None, is_movie=False):
    mal_id = mal_id or (media.get("idMal") if media else None)
    title = title or _title_from_media(media)
    if episode:
        try:
            episode = int(episode)
        except (TypeError, ValueError):
            episode = None

    if is_movie or (media and _is_movie(media)):
        return play_movie_path(media or {"idMal": mal_id}, title=title)

    if episode:
        return play_episode_path(mal_id, episode, title=title, is_movie=False)

    if mal_id and get_playback_key() == PLAYBACK_OTAKU:
        return f"plugin://{get_playback_plugin()}/animes/{mal_id}/"

    if title and get_playback_key() == PLAYBACK_WATCHNIXTOONS2:
        return _watchnixtoons_search(title, "series")

    if title and get_playback_key() == PLAYBACK_FANIME_F:
        return _fanime_search(title)

    return None


def _title_from_media(media):
    if not media:
        return ""
    title = title_for_media(media)
    return title if title != "Unknown" else ""


def _is_movie(media):
    fmt = (media.get("format") or "").upper()
    return fmt in ("MOVIE", "ONE_SHOT")


def log_missing_plugin():
    plugin = get_playback_plugin()
    if not is_addon_installed(plugin):
        xbmc.log(
            f"[{ADDON_ID}] Playback addon not installed: {plugin}",
            xbmc.LOGWARNING,
        )
