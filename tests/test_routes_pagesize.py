# -*- coding: utf-8 -*-
"""Category page-size tests: AniList caps perPage at 50, so a 100-item category
page is assembled by merging two consecutive AniList pages. client.browse is
stubbed to record which AniList pages were requested."""
from unittest.mock import patch

from resources.lib.routes import RouteHandler, CATEGORY_VIEW_SIZE


def _recorder(pages, has_next=True):
    def browse(variables, trending=False):
        pages.append(variables["page"])
        return ([], has_next)
    return browse


class TestCategoryPageSize:
    def test_constant_is_100(self):
        assert CATEGORY_VIEW_SIZE == 100

    def test_category_merges_two_anilist_pages(self):
        h = RouteHandler(1, {"info": "dir_tv", "page": "1"})
        pages = []
        h.client.browse = _recorder(pages)
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_all()
        assert pages == [1, 2]

    def test_category_view_page_2_fetches_3_and_4(self):
        h = RouteHandler(1, {"info": "dir_tv", "page": "2"})
        pages = []
        h.client.browse = _recorder(pages)
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_all()
        assert pages == [3, 4]

    def test_ova_category_also_merges(self):
        h = RouteHandler(1, {"info": "dir_ova", "page": "1"})
        pages = []
        h.client.browse = _recorder(pages)
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.dir_ova()
        assert pages == [1, 2]

    def test_non_category_browse_is_single_page(self):
        h = RouteHandler(1, {"info": "trakt_trending", "page": "1"})
        pages = []
        h.client.browse = _recorder(pages, has_next=False)
        with patch("resources.lib.routes.build_items", return_value=[]):
            h.trakt_trending()
        assert pages == [1]
