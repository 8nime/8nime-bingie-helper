# -*- coding: utf-8 -*-
import xbmcaddon

OTAKU_ID = "plugin.video.otaku"
OTAKU_ANILIST_TOKEN = "anilist.token"
OTAKU_ANILIST_USERNAME = "anilist.username"

ADDON = xbmcaddon.Addon()


def _addon_setting(addon_id, setting_id):
    try:
        return xbmcaddon.Addon(addon_id).getSetting(setting_id) or ""
    except Exception:
        return ""


def _set_addon_setting(addon_id, setting_id, value):
    """Write a setting on another addon, or no-op if it isn't installed.

    Instantiating Addon(<id>) raises when the addon is absent, so this doubles
    as the "only mirror when Otaku is installed" guard -- never a hard dep."""
    try:
        xbmcaddon.Addon(addon_id).setSetting(setting_id, value)
        return True
    except Exception:
        return False


def get_anilist_token():
    """The helper's own login is canonical; Otaku's token is a shared fallback.

    Once the user logs in through the helper its token wins; if they only ever
    logged in via Otaku, that token is still picked up (read-side sharing)."""
    token = (ADDON.getSetting("anilist_token") or "").strip()
    if token:
        return token
    return _addon_setting(OTAKU_ID, OTAKU_ANILIST_TOKEN).strip()


def has_anilist_token():
    return bool(get_anilist_token())


def get_anilist_username():
    """Display name for the logged-in account (helper first, then Otaku)."""
    name = (ADDON.getSetting("anilist_username") or "").strip()
    if name:
        return name
    return _addon_setting(OTAKU_ID, OTAKU_ANILIST_USERNAME).strip()


def set_anilist_token(token, username=""):
    """Store the token in the helper and mirror it into Otaku (when installed).

    The AniList access token is a portable user bearer token, so writing it to
    both addons lets a single login work in either -- without the helper
    depending on Otaku being present."""
    token = (token or "").strip()
    username = (username or "").strip()
    ADDON.setSetting("anilist_token", token)
    ADDON.setSetting("anilist_username", username)
    _set_addon_setting(OTAKU_ID, OTAKU_ANILIST_TOKEN, token)
    _set_addon_setting(OTAKU_ID, OTAKU_ANILIST_USERNAME, username)


def clear_anilist_token():
    """Log out: clear the helper's token + the mirrored Otaku token."""
    ADDON.setSetting("anilist_token", "")
    ADDON.setSetting("anilist_username", "")
    _set_addon_setting(OTAKU_ID, OTAKU_ANILIST_TOKEN, "")
    _set_addon_setting(OTAKU_ID, OTAKU_ANILIST_USERNAME, "")
