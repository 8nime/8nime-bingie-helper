# -*- coding: utf-8 -*-
"""Helper-native AniList login: a QR + token-paste dialog (TV-friendly).

The user scans the QR (or opens the URL) on a phone, authorises AniList through
the armkai OAuth proxy, copies the displayed token, and pastes it into the
dialog. The token is validated against AniList's Viewer{} and stored by auth.py,
which also mirrors it into Otaku when that addon is installed."""
import os

import xbmcaddon
import xbmcgui

from resources.lib import api, auth

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("name")
ADDON_PATH = ADDON.getAddonInfo("path")

ARMKAI_URL = "https://armkai.vercel.app/api/anilist"
_QR_IMAGE = os.path.join(ADDON_PATH, "resources", "media", "anilist_login_qr.png")

_TOKEN_EDIT = 1001
_AUTHORIZE = 1002
_CANCEL = 1003
_BACK_ACTIONS = (9, 10, 92)  # PARENT_DIR / PREVIOUS_MENU / NAV_BACK


class AniListLoginDialog(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.token = ""
        self.proceed = False

    def onInit(self):
        self.setProperty("qr_code", _QR_IMAGE)
        self.setProperty("armkai_url", ARMKAI_URL)
        try:
            self.setFocusId(_TOKEN_EDIT)
        except Exception:
            pass

    def onClick(self, controlId):
        if controlId == _AUTHORIZE:
            try:
                self.token = (self.getControl(_TOKEN_EDIT).getText() or "").strip()
            except Exception:
                self.token = ""
            self.proceed = True
            self.close()
        elif controlId == _CANCEL:
            self.close()

    def onAction(self, action):
        if action.getId() in _BACK_ACTIONS:
            self.close()


def prompt_login():
    """Show the QR/token dialog, validate the token, store it. True on success."""
    dialog = AniListLoginDialog("anilist_login.xml", ADDON_PATH, "Default", "1080i")
    dialog.doModal()
    proceed, token = dialog.proceed, (dialog.token or "").strip()
    del dialog
    if not proceed or not token:
        return False
    viewer = api.validate_token(token)
    if not viewer:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            "That AniList token didn't work. Copy the whole token from the login "
            "page and try again.",
        )
        return False
    auth.set_anilist_token(token, viewer.get("name", ""))
    xbmcgui.Dialog().notification(
        ADDON_NAME, "Logged in as %s" % (viewer.get("name") or "AniList"),
        xbmcgui.NOTIFICATION_INFO,
    )
    return True


def logout():
    """Confirm, then clear the helper (and mirrored Otaku) token. True if cleared."""
    if not auth.has_anilist_token():
        xbmcgui.Dialog().notification(
            ADDON_NAME, "Not logged in to AniList", xbmcgui.NOTIFICATION_INFO
        )
        return False
    if not xbmcgui.Dialog().yesno(ADDON_NAME, "Log out of AniList?"):
        return False
    auth.clear_anilist_token()
    xbmcgui.Dialog().notification(
        ADDON_NAME, "Logged out of AniList", xbmcgui.NOTIFICATION_INFO
    )
    return True
