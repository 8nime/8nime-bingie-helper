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
    import time
    time.sleep(ms / 1000.0)


def translatePath(path):
    return path


def getCondVisibility(condition):
    return False


def executebuiltin(cmd):
    pass


def getInfoLabel(label):
    return ""
