# -*- coding: utf-8 -*-
"""The versioned debug tracer: no-op when off, writes to 8nime.debug when on."""
import os

from resources.lib import debuglog


class TestDebugLog:
    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.setattr(debuglog, "enabled", lambda: False)
        debuglog.dbg("should not write")
        assert not os.path.exists(debuglog._path())

    def test_writes_when_enabled(self, monkeypatch):
        monkeypatch.setattr(debuglog, "enabled", lambda: True)
        debuglog.dbg("hello trace 42")
        with open(debuglog._path(), encoding="utf-8") as handle:
            body = handle.read()
        assert "hello trace 42" in body

    def test_enabled_reads_setting(self, monkeypatch):
        import xbmcaddon
        monkeypatch.setattr(debuglog._ADDON, "getSetting",
                            lambda key: "true" if key == "debug_logging" else "")
        assert debuglog.enabled() is True
