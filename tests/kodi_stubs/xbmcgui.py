# -*- coding: utf-8 -*-
"""Minimal xbmcgui stub for running addon code outside Kodi."""

NOTIFICATION_INFO = "info"
NOTIFICATION_WARNING = "warning"
NOTIFICATION_ERROR = "error"


class _Control:
    """Stand-in for a Kodi control (Window.getControl result)."""

    def __init__(self):
        self._items = []
        self._text = ""

    def reset(self):
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def getText(self):
        return self._text

    def setText(self, text):
        self._text = text

    def setLabel(self, label):
        self._text = label

    def setImage(self, path):
        self._image = path


class WindowXMLDialog:
    """Minimal WindowXMLDialog base so dialog controllers import under tests.

    Tests don't render a UI; they monkeypatch the controller or its doModal."""

    def __init__(self, *args, **kwargs):
        pass

    def doModal(self):
        pass

    def close(self):
        pass

    def show(self):
        pass

    def getControl(self, control_id):
        return _Control()

    def setProperty(self, key, value):
        pass

    def getProperty(self, key):
        return ""

    def setFocusId(self, control_id):
        pass


class Window:
    """Window with a per-id property store so tests can assert set/clear."""

    _store = {}

    def __init__(self, window_id=0):
        self.window_id = window_id
        Window._store.setdefault(window_id, {})

    def setProperty(self, key, value):
        Window._store.setdefault(self.window_id, {})[key] = str(value)

    def getProperty(self, key):
        return Window._store.get(self.window_id, {}).get(key, "")

    def clearProperty(self, key):
        Window._store.get(self.window_id, {}).pop(key, None)

    def getControl(self, control_id):
        return _Control()


class Dialog:
    """No-op dialog; select/yesno return defaults overridable in tests."""

    def notification(self, heading, message, icon="", time=5000, sound=True):
        pass

    def ok(self, heading, message):
        return True

    def yesno(self, heading, message, *args, **kwargs):
        return True

    def textviewer(self, heading, text, usemono=False):
        pass

    def select(self, heading, options, **kwargs):
        return 0


class ListItem:
    def __init__(self, label="", label2="", path=""):
        self.label = label
        self.label2 = label2
        self._path = path
        self._art = {}
        self._info = {}
        self._properties = {}
        self._unique_ids = {}

    def setLabel(self, label):
        self.label = label

    def setArt(self, art_dict):
        self._art.update(art_dict)

    def getArt(self, key):
        return self._art.get(key, "")

    def setInfo(self, media_type, info_dict):
        self._info.setdefault(media_type, {}).update(info_dict)

    def getVideoInfoTag(self):
        return self._info.get("video", {})

    def setProperty(self, key, value):
        self._properties[key] = str(value)

    def getProperty(self, key):
        return self._properties.get(key, "")

    def setPath(self, path):
        self._path = path

    def getPath(self):
        return self._path

    def setUniqueIDs(self, ids, default_id=""):
        self._unique_ids.update(ids)

    def setContentLookup(self, enable):
        pass

    def setMimeType(self, mimetype):
        self._mimetype = mimetype
