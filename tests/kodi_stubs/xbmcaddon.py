# -*- coding: utf-8 -*-
"""Minimal xbmcaddon stub for running addon code outside Kodi.

Settings persist per addon-id in a module-level store (looked up live on every
get/set) so that import-time `Addon()` instances and freshly-created ones share
state -- needed to exercise the helper<->Otaku token mirror/priority. Call
reset() between tests (conftest does this automatically)."""

_STORE = {}

_DEFAULTS = {
    "plugin.video.8nime.bingie.helper": {
        "title_language": "english",
        "playback_plugin": "otaku",
        "sort_order": "desc",
    },
}


def _settings_for(addon_id):
    if addon_id not in _STORE:
        _STORE[addon_id] = dict(_DEFAULTS.get(addon_id, {}))
    return _STORE[addon_id]


def reset():
    """Clear all persisted per-addon settings (call between tests)."""
    _STORE.clear()


class Addon:
    def __init__(self, addon_id=None):
        self._id = addon_id or "plugin.video.8nime.bingie.helper"
        _settings_for(self._id)  # seed defaults
        self._info = {
            "id": self._id,
            "path": "/tmp/fake-addon-path",
            "name": "8nime Bingie Helper",
            "version": "1.0.0",
        }

    def getSetting(self, key):
        return _settings_for(self._id).get(key, "")

    def getSettingBool(self, key):
        val = _settings_for(self._id).get(key, "false")
        return str(val).lower() == "true"

    def setSetting(self, key, value):
        _settings_for(self._id)[key] = value

    def getAddonInfo(self, key):
        return self._info.get(key, "")

    def getLocalizedString(self, string_id):
        return ""
