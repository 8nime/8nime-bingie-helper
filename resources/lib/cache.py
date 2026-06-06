# -*- coding: utf-8 -*-
import hashlib
import json
import os
import time

import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
CACHE_TTL = 3600
CACHE_DIR = xbmcvfs.translatePath(
    f"special://profile/addon_data/{ADDON.getAddonInfo('id')}/cache/"
)


class ApiCache:
    """Memory + disk cache for GraphQL responses (1 hour TTL)."""

    def __init__(self, ttl=CACHE_TTL):
        self.ttl = ttl
        self._memory = {}
        self._ensure_dir()

    def _ensure_dir(self):
        if not xbmcvfs.exists(CACHE_DIR):
            xbmcvfs.mkdirs(CACHE_DIR)

    def _key(self, query, variables):
        raw = json.dumps({"q": query, "v": variables or {}}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _path(self, key):
        return os.path.join(CACHE_DIR, f"{key}.json")

    def get(self, query, variables=None):
        key = self._key(query, variables)
        now = time.time()

        mem = self._memory.get(key)
        if mem and now - mem["ts"] < self.ttl:
            return mem["data"]

        path = self._path(key)
        if xbmcvfs.exists(path):
            try:
                with xbmcvfs.File(path, "r") as handle:
                    payload = json.loads(handle.read())
                if now - payload.get("ts", 0) < self.ttl:
                    self._memory[key] = payload
                    return payload.get("data")
            except Exception as exc:
                xbmc.log(f"[AniListBingieHelper] Cache read failed: {exc}", xbmc.LOGDEBUG)

        return None

    def get_stale(self, query, variables=None):
        """Return cached data even past TTL — used when API is rate-limited."""
        key = self._key(query, variables)
        mem = self._memory.get(key)
        if mem:
            return mem.get("data")

        path = self._path(key)
        if xbmcvfs.exists(path):
            try:
                with xbmcvfs.File(path, "r") as handle:
                    payload = json.loads(handle.read())
                return payload.get("data")
            except Exception:
                pass
        return None

    def set(self, query, variables, data):
        if data is None:
            return
        key = self._key(query, variables)
        payload = {"ts": time.time(), "data": data}
        self._memory[key] = payload
        try:
            with xbmcvfs.File(self._path(key), "w") as handle:
                handle.write(json.dumps(payload))
        except Exception as exc:
            xbmc.log(f"[AniListBingieHelper] Cache write failed: {exc}", xbmc.LOGDEBUG)

    def stats(self):
        """Return disk cache file count and approximate size in bytes."""
        count = 0
        size = 0
        try:
            for name in xbmcvfs.listdir(CACHE_DIR)[1]:
                if not name.endswith(".json"):
                    continue
                path = os.path.join(CACHE_DIR, name)
                if not xbmcvfs.exists(path):
                    continue
                count += 1
                try:
                    st = xbmcvfs.Stat(path)
                    st_size = st.st_size() if callable(getattr(st, "st_size", None)) else st.st_size
                    size += int(st_size)
                except Exception:
                    pass
        except Exception:
            pass
        return count, size

    def clear_expired(self):
        """Remove on-disk entries past TTL. Returns number of files deleted."""
        now = time.time()
        removed = 0
        try:
            for name in xbmcvfs.listdir(CACHE_DIR)[1]:
                if not name.endswith(".json"):
                    continue
                path = os.path.join(CACHE_DIR, name)
                try:
                    with xbmcvfs.File(path, "r") as handle:
                        payload = json.loads(handle.read())
                    if now - payload.get("ts", 0) >= self.ttl:
                        xbmcvfs.delete(path)
                        removed += 1
                        key = name[:-5]
                        self._memory.pop(key, None)
                except Exception:
                    try:
                        xbmcvfs.delete(path)
                        removed += 1
                    except Exception:
                        pass
        except Exception as exc:
            xbmc.log(f"[AniListBingieHelper] Cache expiry cleanup failed: {exc}", xbmc.LOGDEBUG)
        return removed

    def clear_all(self):
        """Remove all cached API responses from memory and disk."""
        self._memory.clear()
        removed = 0
        try:
            for name in xbmcvfs.listdir(CACHE_DIR)[1]:
                if not name.endswith(".json"):
                    continue
                path = os.path.join(CACHE_DIR, name)
                if xbmcvfs.delete(path):
                    removed += 1
        except Exception as exc:
            xbmc.log(f"[AniListBingieHelper] Cache clear failed: {exc}", xbmc.LOGERROR)
        return removed


def get_api_cache():
    return ApiCache()


def format_cache_size(num_bytes):
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"
