# -*- coding: utf-8 -*-
import sys

import xbmcplugin

from resources.lib.parser import parse_params
from resources.lib.routes import RouteHandler


class Router:
    def __init__(self, handle, paramstring):
        self.handle = handle
        self.params = parse_params(paramstring)

    def run(self):
        try:
            RouteHandler(self.handle, self.params).run()
        except Exception as exc:
            import xbmc

            xbmc.log(f"[AniListBingieHelper] Router error: {exc}", xbmc.LOGERROR)
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
