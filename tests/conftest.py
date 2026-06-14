# -*- coding: utf-8 -*-
"""
Insert Kodi stub modules into sys.modules before any addon code is imported.
This file is loaded automatically by pytest before test collection starts.
"""
import sys
import os

# Make the repo root importable so `resources.lib.*` works.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Add the stubs package to sys.path so we can import them directly.
STUBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kodi_stubs")
if STUBS_DIR not in sys.path:
    sys.path.insert(0, STUBS_DIR)

# Register each stub module under its Kodi name before any addon import runs.
from tests.kodi_stubs import xbmc as _xbmc
from tests.kodi_stubs import xbmcaddon as _xbmcaddon
from tests.kodi_stubs import xbmcgui as _xbmcgui
from tests.kodi_stubs import xbmcplugin as _xbmcplugin
from tests.kodi_stubs import xbmcvfs as _xbmcvfs

sys.modules.setdefault("xbmc", _xbmc)
sys.modules.setdefault("xbmcaddon", _xbmcaddon)
sys.modules.setdefault("xbmcgui", _xbmcgui)
sys.modules.setdefault("xbmcplugin", _xbmcplugin)
sys.modules.setdefault("xbmcvfs", _xbmcvfs)

import pytest


@pytest.fixture(autouse=True)
def _reset_addon_settings(tmp_path):
    """Isolate per-addon stub settings + the local watched store between tests."""
    _xbmcaddon.reset()
    from resources.lib import watched as _watched
    _watched.reset()
    _watched._store_path = lambda: os.path.join(str(tmp_path), "watched.json")
    from resources.lib import wnt2 as _wnt2
    _wnt2.reset_series_cache()
    _wnt2._series_cache_path = lambda: os.path.join(str(tmp_path), "wnt2_series.json")
    yield
    _xbmcaddon.reset()
    _watched.reset()
    _wnt2.reset_series_cache()
