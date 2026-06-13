# -*- coding: utf-8 -*-
"""Minimal xbmcaddon stub for running addon code outside Kodi."""


class Addon:
    def __init__(self, addon_id=None):
        self._id = addon_id or "plugin.video.8nime.bingie.helper"
        self._settings = {
            "title_language": "english",
            "playback_plugin": "otaku",
            "sort_order": "desc",
        }
        self._info = {
            "id": self._id,
            "path": "/tmp/fake-addon-path",
            "name": "8nime Bingie Helper",
            "version": "1.0.0",
        }

    def getSetting(self, key):
        return self._settings.get(key, "")

    def getSettingBool(self, key):
        val = self._settings.get(key, "false")
        return str(val).lower() == "true"

    def setSetting(self, key, value):
        self._settings[key] = value

    def getAddonInfo(self, key):
        return self._info.get(key, "")

    def getLocalizedString(self, string_id):
        return ""
