# -*- coding: utf-8 -*-
"""Minimal xbmcgui stub for running addon code outside Kodi."""


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
