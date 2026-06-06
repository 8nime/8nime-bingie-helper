# -*- coding: utf-8 -*-
import xbmcaddon

OTAKU_ID = "plugin.video.otaku"
OTAKU_ANILIST_TOKEN = "anilist.token"
OTAKU_ANILIST_LOGIN = "plugin://plugin.video.otaku/watchlist_login/anilist?auth_dialog=true"

ADDON = xbmcaddon.Addon()


def _addon_setting(addon_id, setting_id):
    try:
        return xbmcaddon.Addon(addon_id).getSetting(setting_id) or ""
    except Exception:
        return ""


def get_anilist_token():
    """Otaku OAuth token is canonical; helper setting is legacy fallback."""
    token = _addon_setting(OTAKU_ID, OTAKU_ANILIST_TOKEN).strip()
    if token:
        return token
    return (ADDON.getSetting("anilist_token") or "").strip()


def has_anilist_token():
    return bool(get_anilist_token())
