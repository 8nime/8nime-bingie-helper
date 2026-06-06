# -*- coding: utf-8 -*-
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_PATH = ADDON.getAddonInfo("path")
ADDON_NAME = ADDON.getAddonInfo("name")
PLUGIN_URL = f"plugin://{ADDON_ID}/"

ANILIST_API = "https://graphql.anilist.co"

# Bingie skin reads this property name from stock TMDb helper — keep it.
WIDGET_RELOAD_PROP = "TMDbBingieHelper.Widgets.Reload"
