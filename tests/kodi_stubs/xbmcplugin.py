# -*- coding: utf-8 -*-
"""Minimal xbmcplugin stub for running addon code outside Kodi."""

SORT_METHOD_NONE = 0
SORT_METHOD_UNSORTED = 0
SORT_METHOD_LABEL = 1
SORT_METHOD_DATE = 2
SORT_METHOD_VIDEO_RATING = 3
SORT_METHOD_VIDEO_YEAR = 4
SORT_METHOD_EPISODE = 23
SORT_METHOD_TITLE = 7
SORT_METHOD_DATEADDED = 40


def addDirectoryItem(handle, url, listitem, is_folder=False, total_items=0):
    pass


def addDirectoryItems(handle, items, total_items=0):
    pass


def endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=True):
    pass


def setContent(handle, content):
    pass


def setResolvedUrl(handle, succeeded, listitem):
    pass


def addSortMethod(handle, sort_method):
    pass


def setPluginCategory(handle, category):
    pass
