# -*- coding: utf-8 -*-
"""Minimal xbmcvfs stub for running addon code outside Kodi."""
import os


def translatePath(path):
    # Map Kodi special:// paths to temp dir equivalents
    if path.startswith("special://profile/"):
        relative = path[len("special://profile/"):]
        return os.path.join("/tmp/kodi-profile", relative)
    if path.startswith("special://home/"):
        relative = path[len("special://home/"):]
        return os.path.join("/tmp/kodi-home", relative)
    return path


def exists(path):
    return os.path.exists(path)


def mkdirs(path):
    os.makedirs(path, exist_ok=True)
    return True


def File(path, mode="r"):
    return open(path, mode)
