# -*- coding: utf-8 -*-
"""Minimal xbmcplugin stub for running addon code outside Kodi."""

SORT_METHOD_UNSORTED = 0
SORT_METHOD_LABEL = 1
SORT_METHOD_DATE = 2
SORT_METHOD_VIDEO_RATING = 3
SORT_METHOD_VIDEO_YEAR = 4


def addDirectoryItem(handle, url, listitem, is_folder=False, total_items=0):
    pass


def addDirectoryItems(handle, items, total_items=0):
    pass


def endOfDirectory(handle, succeeded=True, update_listing=False, cache_to_disc=True):
    pass


def setContent(handle, content):
    pass


def setResolvedUrl(handle, succeeded, listitem):
    pass


def addSortMethod(handle, sort_method):
    pass


def setPluginCategory(handle, category):
    pass
