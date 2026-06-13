# -*- coding: utf-8 -*-
"""Category browses fetch a single AniList page per view, so paging forward is
one fast round trip (the old 100-item, two-fetch merge was the slow-next-page
cause). client.browse is stubbed to record which AniList pages were requested."""
from unittest.mock import patch

from resources.lib.routes import RouteHandler


def _recorder(pages, has_next=True):
    def browse(variables, trending=False):
        pages.append(variables["page"])
        return ([], has_next)
    return browse


class TestCategoryPageSize:
    def test_category_is_single_page(self):
        h = RouteHandler(1, {"info": "dir_tv", "page": "1"})
        pages = []
        h.client.browse = _recorder(pages)
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_all()
        assert pages == [1]

    def test_category_view_page_2_fetches_page_2(self):
        h = RouteHandler(1, {"info": "dir_tv", "page": "2"})
        pages = []
        h.client.browse = _recorder(pages)
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_all()
        assert pages == [2]

    def test_ova_category_single_page(self):
        h = RouteHandler(1, {"info": "dir_ova", "page": "1"})
        pages = []
        h.client.browse = _recorder(pages)
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_ova()
        assert pages == [1]

    def test_non_category_browse_is_single_page(self):
        h = RouteHandler(1, {"info": "trakt_trending", "page": "1"})
        pages = []
        h.client.browse = _recorder(pages, has_next=False)
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.trakt_trending()
        assert pages == [1]
