# -*- coding: utf-8 -*-
"""Minimal xbmc stub for running addon code outside Kodi."""

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4


def log(msg, level=LOGINFO):
    pass


def sleep(ms):
    # No-op in tests: real waiting only slows the suite (e.g. default.py's
    # post-refresh spinner-settle sleep). Tests assert behaviour, not timing.
    pass


def translatePath(path):
    return path


def getCondVisibility(condition):
    return False


def executebuiltin(cmd):
    pass


def getInfoLabel(label):
    return ""
