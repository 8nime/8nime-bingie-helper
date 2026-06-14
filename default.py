# -*- coding: utf-8 -*-
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import art_overrides, identity
from resources.lib.api import AniListClient, clear_all_caches
from resources.lib.cache import format_cache_size, get_api_cache
from resources.lib.listitems import _clean_description, _title
from resources.lib.window_state import bump_widget_reload

ADDON = xbmcaddon.Addon()


def show_description(mal_id=None, query=None):
    client = AniListClient()
    media = None
    if mal_id and str(mal_id).isdigit():
        media = client.get_media(mal_id=int(mal_id))
    elif query:
        resolved = client.resolve_mal_id({"query": query})
        if resolved:
            media = client.get_media(mal_id=resolved)
    if not media:
        xbmcgui.Dialog().ok(ADDON.getAddonInfo("name"), "No AniList description found.")
        return
    title = _title(media)
    body = _clean_description(media.get("description") or "")
    if not body:
        xbmcgui.Dialog().ok(title, "No description available on AniList.")
        return
    xbmcgui.Dialog().textviewer(title, body)


def close_dialog(dialog_id=None):
    if dialog_id:
        xbmc.executebuiltin(f"Dialog.Close({dialog_id})")


def clear_cache(expired_only=False):
    cache = get_api_cache()
    count, size = cache.stats()
    if count == 0:
        xbmcgui.Dialog().notification(
            ADDON.getAddonInfo("name"),
            ADDON.getLocalizedString(32066),
            xbmcgui.NOTIFICATION_INFO,
            3000,
        )
        return

    if expired_only:
        removed = clear_all_caches(expired_only=True)
        msg = ADDON.getLocalizedString(32067) % removed
        xbmcgui.Dialog().notification(ADDON.getAddonInfo("name"), msg, xbmcgui.NOTIFICATION_INFO, 3500)
        return

    prompt = ADDON.getLocalizedString(32065) % (count, format_cache_size(size))
    if not xbmcgui.Dialog().yesno(ADDON.getAddonInfo("name"), prompt):
        return
    removed = clear_all_caches(expired_only=False)
    msg = ADDON.getLocalizedString(32068) % removed
    xbmcgui.Dialog().notification(ADDON.getAddonInfo("name"), msg, xbmcgui.NOTIFICATION_INFO, 3500)
    xbmc.executebuiltin("Container.Refresh")


# How long to hold the busy spinner after Container.Refresh so it doesn't vanish
# before the (async) detail/widget re-query lands and the view visibly updates.
_REFRESH_SETTLE_MS = 900


def _busy_open():
    xbmc.executebuiltin("ActivateWindow(busydialognocancel)")


def _busy_close():
    xbmc.executebuiltin("Dialog.Close(busydialognocancel)")


def _refresh_views():
    """Bust caches + force a re-fetch, holding the spinner across the async refresh."""
    clear_all_caches(expired_only=False)
    bump_widget_reload()
    xbmc.executebuiltin("Container.Refresh")
    xbmc.sleep(_REFRESH_SETTLE_MS)


def sync_trakt_rating(args):
    sync_type = args.get("sync_type")

    # Cache refresh (button 562) busts the cached metadata for the item and forces
    # a widget/detail re-fetch. No AniList auth required. Spinner so it never looks
    # like nothing happened.
    if sync_type == "cache_refresh":
        _busy_open()
        try:
            _refresh_views()
        finally:
            _busy_close()
        return

    client = AniListClient()
    if not client.has_token():
        xbmcgui.Dialog().notification(
            ADDON.getAddonInfo("name"),
            "Add an AniList token in helper settings to rate titles.",
            xbmcgui.NOTIFICATION_WARNING,
            4000,
        )
        return

    # The skin sends the item's tmdb_id (real Fribb id or our surrogate), NOT a
    # mal_id, so reverse-map it to the AniList entry before scoring (gap G2).
    mal_id = identity.resolve_mal_id(args, client)
    if not mal_id or not sync_type:
        return

    # A busy spinner stands in for the removed success toast: it shows the AniList
    # request is in flight (the save + membership/score reads are a network round
    # trip) and, being modal, also blocks the double-clicks that previously toggled
    # an entry on then straight back off. Held across the refresh so it doesn't
    # vanish before the label/icon flip. Closed in finally so an error never leaves
    # the spinner stuck.
    _busy_open()
    ok = False
    try:
        ok, action = client.save_media_score(int(mal_id), sync_type)
        if ok:
            # Bust the AniList cache so My List (cached MediaListCollection) and the
            # detail dialog's on-list/rating state (OnMyList/MyRating) reflect this
            # change. No success toast: the favourite button's label/icon flip
            # ("Add To Favorite" + plus <-> "Remove From Favorite" + minus) via the
            # OnMyList/MyRating the refreshed detail item carries is the feedback.
            clear_all_caches(expired_only=False)
            # Pre-warm the caches the refreshed detail + My List widget will read,
            # WHILE the spinner is still up, so their re-query is an instant cache
            # hit and the view updates before the spinner closes -- not after.
            try:
                media = client.get_media(int(mal_id))
                if media and media.get("id"):
                    client.list_state(media["id"])
                client.watchlist()
            except Exception:
                pass
            bump_widget_reload()
            xbmc.executebuiltin("Container.Refresh")
            xbmc.sleep(_REFRESH_SETTLE_MS)
    finally:
        _busy_close()
    if not ok:
        xbmcgui.Dialog().notification(
            ADDON.getAddonInfo("name"),
            "Could not update AniList rating.",
            xbmcgui.NOTIFICATION_ERROR,
            3500,
        )


def select_artwork(args):
    """More-Info 'Change artwork' (G6): pick AniList cover/banner as poster/fanart."""
    client = AniListClient()
    mal_id = identity.resolve_mal_id(args, client)
    if not mal_id:
        return
    media = client.get_media(mal_id=int(mal_id))
    if not media:
        return
    cover = media.get("coverImage") or {}
    poster = cover.get("extraLarge") or cover.get("large")
    banner = media.get("bannerImage")
    options, choices = [], []
    if poster:
        options.append("Use cover as poster")
        choices.append(("poster", poster))
    if banner:
        options.append("Use banner as fanart")
        choices.append(("fanart", banner))
    if not options:
        return
    idx = xbmcgui.Dialog().select(ADDON.getAddonInfo("name"), options)
    if idx is None or idx < 0:
        return
    kind, url = choices[idx]
    if art_overrides.set_art(mal_id, **{kind: url}):
        bump_widget_reload()
        xbmc.executebuiltin("Container.Refresh")


def refresh_details(args):
    """More-Info 'Refresh' (G6): bust cached metadata and force a re-fetch.

    Wrapped in the busy spinner so the button gives visible feedback -- the
    re-fetch was otherwise silent and looked like nothing happened.
    """
    _busy_open()
    try:
        _refresh_views()
    finally:
        _busy_close()


def _merge_query(url, updates):
    """Return url with its query params updated. A None value removes a param.

    Always resets `page` so a new search/sort starts at page 1.
    """
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=False))
    params.pop("page", None)
    for key, value in updates.items():
        if value:
            params[key] = value
        else:
            params.pop(key, None)
    return urlunsplit(parts._replace(query=urlencode(params)))


def category_filter(args):
    """Side-blade Search: prompt for text, re-query AniList scoped to this view."""
    path = (args.get("path") or "").replace('"', "")
    if not path:
        return
    current = dict(parse_qsl(urlsplit(path).query)).get("search", "")
    query = xbmcgui.Dialog().input(
        "Search this category", defaultt=current, type=xbmcgui.INPUT_ALPHANUM
    )
    if query is None:
        return
    target = _merge_query(path, {"search": query.strip()})
    xbmc.executebuiltin(f'Container.Update({target})')


def category_sort(args):
    """Side-blade Sort: pick an AniList sort, re-query this view."""
    path = (args.get("path") or "").replace('"', "")
    if not path:
        return
    labels = ["Title (A-Z)", "Most popular", "Highest score", "Newest", "Trending"]
    keys = ["title", "popularity", "score", "newest", "trending"]
    idx = xbmcgui.Dialog().select("Sort by", labels)
    if idx < 0:
        return
    target = _merge_query(path, {"sort": keys[idx]})
    xbmc.executebuiltin(f'Container.Update({target})')


def main():
    raw = sys.argv[1:]
    args = dict(arg.split("=", 1) for arg in raw if "=" in arg)
    # Some skin actions are passed as a bare positional token (e.g. sync_trakt,
    # cache_refresh) which the old k=v-only parser silently dropped -- so every
    # rating button fell through to the description popup (gaps G1/G3). Capture them.
    flags = {arg for arg in raw if "=" not in arg}

    if args.get("close_dialog"):
        close_dialog(args.get("close_dialog"))
        return
    if args.get("add_path"):
        path = args["add_path"].replace('"', "")
        xbmc.executebuiltin(f'PlayMedia("{path}",isdir)')
        return
    if args.get("call_path"):
        path = args["call_path"].replace('"', "")
        xbmc.executebuiltin(f'ActivateWindow(Videos,"{path}",return)')
        return
    if "cache_refresh" in flags:
        args.setdefault("sync_type", "cache_refresh")
    if "sync_trakt" in flags or args.get("sync_trakt"):
        sync_trakt_rating(args)
        return
    if "select_artwork" in flags or args.get("select_artwork"):
        select_artwork(args)
        return
    if "refresh_details" in flags or args.get("refresh_details"):
        refresh_details(args)
        return
    if args.get("clear_cache") == "true":
        clear_cache(expired_only=False)
        return
    if args.get("clear_expired_cache") == "true":
        clear_cache(expired_only=True)
        return
    if args.get("action") == "resumewatch":
        from resources.lib import resume
        resume.babysit(args.get("aid"), args.get("episode"), args.get("mal_id"))
        return
    if args.get("action") == "catfilter":
        category_filter(args)
        return
    if args.get("action") == "catsort":
        category_sort(args)
        return
    if args.get("anilist_login") == "true":
        from resources.lib import anilist_login
        if anilist_login.prompt_login():
            bump_widget_reload()
        return
    if args.get("anilist_logout") == "true":
        from resources.lib import anilist_login
        if anilist_login.logout():
            bump_widget_reload()
        return
    action = args.get("description") or args.get("wikipedia")
    if action:
        show_description(mal_id=args.get("mal_id"), query=action)
        return
    mal_id = args.get("mal_id")
    if mal_id:
        show_description(mal_id=mal_id)


if __name__ == "__main__":
    main()
