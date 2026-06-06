# -*- coding: utf-8 -*-
import sys

from resources.lib.router import Router

if __name__ == "__main__":
    Router(int(sys.argv[1]), sys.argv[2][1:]).run()
