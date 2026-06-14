# -*- coding: utf-8 -*-
"""
Integration tests for listitems.py — AniList media dicts -> Kodi ListItems.

All Kodi modules are stubbed via conftest.py / kodi_stubs. No network calls.
"""
import json
import os
import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helpers — import after stubs are registered
# ---------------------------------------------------------------------------
from resources.lib.listitems import (
    _clean_description,
    _is_movie,
    _trailer_url,
    _build_art,
    _is_creator_role,
    _collect_creators,
    build_item,
    build_items,
    build_cast_item,
    build_crew_item,
    build_episode_item,
    build_season_item,
    build_review_item,
    build_video_item,
    build_detail_item,
    build_spotlight_item,
)
import resources.lib.season_map as season_map
import resources.lib.identity as identity


def _reset_season_map(by_anilist=None, tvdb_members=None):
    season_map._BY_ANILIST = by_anilist or {}
    season_map._BY_MAL = {}
    season_map._TVDB_MEMBERS = tvdb_members or {}
    season_map._LOADED = True
    season_map._BY_TMDB = None
    season_map._BY_TMDB_SRC = None


@pytest.fixture(autouse=True)
def _isolate_season_map():
    # Keep tmdb_id derivation hermetic (no disk cache, unmapped -> surrogate) and
    # ensure no artwork override leaks in from another test module.
    _reset_season_map()
    import resources.lib.art_overrides as _ao
    _ao._CACHE = {}
    yield


# ---------------------------------------------------------------------------
# _clean_description
# ---------------------------------------------------------------------------
class TestCleanDescription:
    def test_none_returns_empty(self):
        assert _clean_description(None) == ""

    def test_plain_text_unchanged(self):
        assert _clean_description("Hello world") == "Hello world"

    def test_br_tag_replaced_with_newline(self):
        result = _clean_description("Line one<br>Line two")
        assert "\n" in result
        assert "Line one" in result
        assert "Line two" in result

    def test_br_slash_tag_replaced(self):
        result = _clean_description("A<br/>B")
        assert "A" in result and "B" in result and "<br" not in result

    def test_html_tags_stripped(self):
        result = _clean_description("<b>Bold</b> and <i>italic</i>")
        assert "<b>" not in result
        assert "<i>" not in result
        assert "Bold" in result
        assert "italic" in result

    def test_kodi_italic_tags_stripped(self):
        result = _clean_description("[I]italic text[/I]")
        assert "[I]" not in result
        assert "[/I]" not in result
        assert "italic text" in result

    def test_kodi_bold_tags_stripped(self):
        result = _clean_description("[B]bold[/B]")
        assert "[B]" not in result
        assert "bold" in result

    def test_strips_leading_trailing_whitespace(self):
        result = _clean_description("  hello  ")
        assert result == "hello"

    def test_complex_html(self):
        html = "<p>Tanjiro joins the <b>Flame Hashira</b> on the <i>Mugen Train</i>.</p>"
        result = _clean_description(html)
        assert "Tanjiro joins the" in result
        assert "Flame Hashira" in result
        assert "<p>" not in result


# ---------------------------------------------------------------------------
# _is_movie
# ---------------------------------------------------------------------------
class TestIsMovie:
    def test_tv_is_not_movie(self):
        assert _is_movie({"format": "TV"}) is False

    def test_movie_format(self):
        assert _is_movie({"format": "MOVIE"}) is True

    def test_one_shot_is_movie(self):
        assert _is_movie({"format": "ONE_SHOT"}) is True

    def test_ova_not_movie(self):
        assert _is_movie({"format": "OVA"}) is False

    def test_missing_format_not_movie(self):
        assert _is_movie({}) is False

    def test_lowercase_format(self):
        assert _is_movie({"format": "movie"}) is True


# ---------------------------------------------------------------------------
# _trailer_url
# ---------------------------------------------------------------------------
class TestTrailerUrl:
    def test_youtube_trailer(self):
        media = {"trailer": {"id": "abc123", "site": "youtube"}}
        url = _trailer_url(media)
        assert url == "plugin://plugin.video.youtube/play/?video_id=abc123"

    def test_dailymotion_trailer(self):
        media = {"trailer": {"id": "xyz", "site": "dailymotion"}}
        url = _trailer_url(media)
        assert "dailymotion" in url
        assert "xyz" in url

    def test_no_trailer(self):
        assert _trailer_url({}) is None
        assert _trailer_url({"trailer": {}}) is None

    def test_unknown_site_returns_none(self):
        media = {"trailer": {"id": "id1", "site": "vimeo"}}
        assert _trailer_url(media) is None


# ---------------------------------------------------------------------------
# _build_art
# ---------------------------------------------------------------------------
class TestBuildArt:
    def test_tv_art_includes_tvshow_keys(self):
        media = {
            "coverImage": {
                "extraLarge": "https://example.com/cover-xl.jpg",
                "large": "https://example.com/cover-l.jpg",
            },
            "bannerImage": "https://example.com/banner.jpg",
        }
        art = _build_art(media, is_movie=False)
        assert "tvshow.poster" in art
        assert "tvshow.fanart" in art
        assert art["poster"] == "https://example.com/cover-xl.jpg"
        assert art["fanart"] == "https://example.com/banner.jpg"

    def test_movie_art_no_tvshow_keys(self):
        media = {
            "coverImage": {"extraLarge": "https://example.com/cover.jpg", "large": None},
            "bannerImage": "https://example.com/banner.jpg",
        }
        art = _build_art(media, is_movie=True)
        assert "tvshow.poster" not in art
        assert "poster" in art

    def test_empty_media_returns_empty_dict(self):
        art = _build_art({}, is_movie=False)
        assert art == {}

    def test_fallback_to_large_cover_when_no_extra_large(self):
        media = {
            "coverImage": {"extraLarge": None, "large": "https://example.com/large.jpg"},
            "bannerImage": None,
        }
        # no bannerImage and no extraLarge → backdrop falls back to poster (large)
        art = _build_art(media, is_movie=False)
        assert art["poster"] == "https://example.com/large.jpg"


# ---------------------------------------------------------------------------
# _is_creator_role
# ---------------------------------------------------------------------------
class TestIsCreatorRole:
    def test_original_creator_role(self):
        assert _is_creator_role("Original Creator") is True

    def test_story_role(self):
        assert _is_creator_role("Story") is True

    def test_story_and_art_role(self):
        assert _is_creator_role("Story & Art") is True

    def test_director_not_creator(self):
        assert _is_creator_role("Director") is False

    def test_storyboard_not_creator(self):
        assert _is_creator_role("Storyboard") is False

    def test_empty_role_not_creator(self):
        assert _is_creator_role("") is False

    def test_none_role_not_creator(self):
        assert _is_creator_role(None) is False

    def test_author_is_creator(self):
        assert _is_creator_role("Author") is True


# ---------------------------------------------------------------------------
# build_item — the main pipeline test
# ---------------------------------------------------------------------------
class TestBuildItem:
    @pytest.fixture
    def tv_media(self):
        return load_fixture("anime_detail.json")

    def test_returns_none_when_no_mal_id(self):
        assert build_item({"id": 999, "idMal": None}) is None

    def test_label_is_english_title(self, tv_media):
        li = build_item(tv_media)
        assert li is not None
        assert "Demon Slayer" in li.label

    def test_info_year(self, tv_media):
        li = build_item(tv_media)
        info = li._info.get("video", {})
        assert info["year"] == 2021

    def test_info_mediatype_tvshow(self, tv_media):
        li = build_item(tv_media)
        info = li._info.get("video", {})
        assert info["mediatype"] == "tvshow"

    def test_info_mediatype_movie(self):
        movie = load_fixture("anime_detail.json")
        movie["format"] = "MOVIE"
        li = build_item(movie)
        assert li._info["video"]["mediatype"] == "movie"

    def test_info_rating(self, tv_media):
        li = build_item(tv_media)
        info = li._info.get("video", {})
        assert abs(info["rating"] - 8.3) < 0.01

    def test_info_genre(self, tv_media):
        li = build_item(tv_media)
        info = li._info.get("video", {})
        assert "Action" in info["genre"]

    def test_info_plot_html_cleaned(self, tv_media):
        li = build_item(tv_media)
        info = li._info.get("video", {})
        assert "<b>" not in info["plot"]
        assert "<br" not in info["plot"]
        assert "Mugen Train" in info["plot"]

    def test_info_trailer_url(self, tv_media):
        li = build_item(tv_media)
        info = li._info.get("video", {})
        assert "youtube" in info.get("trailer", "")

    def test_info_duration_converted_to_seconds(self, tv_media):
        li = build_item(tv_media)
        info = li._info.get("video", {})
        # 23 minutes -> 23 * 60 = 1380 seconds
        assert info["duration"] == 1380

    def test_art_poster_set(self, tv_media):
        li = build_item(tv_media)
        assert li._art.get("poster", "").startswith("https://")

    def test_art_fanart_set(self, tv_media):
        li = build_item(tv_media)
        assert li._art.get("fanart", "").startswith("https://")

    def test_property_mal_id(self, tv_media):
        li = build_item(tv_media)
        assert li._properties["mal_id"] == "40748"

    def test_property_anilist_id(self, tv_media):
        li = build_item(tv_media)
        assert li._properties["anilist_id"] == "101922"

    def test_property_dbtype_tvshow(self, tv_media):
        li = build_item(tv_media)
        assert li._properties["DBType"] == "tvshow"

    def test_property_dbtype_movie_for_movie(self):
        movie = load_fixture("anime_detail.json")
        movie["format"] = "MOVIE"
        li = build_item(movie)
        assert li._properties["DBType"] == "movie"

    def test_property_tmdb_type_tv(self, tv_media):
        li = build_item(tv_media)
        assert li._properties["tmdb_type"] == "tv"

    def test_lean_row_omits_rich_props(self, tv_media):
        # Lean browse rows carry base fields only; the indexed enrichment props
        # (Genre.N.Name/Studio/Director/Creator/AniList_Rating) belong to the
        # spotlight + More-Info header tiers, not browse rows.
        li = build_item(tv_media)
        assert li._properties.get("Genre.1.Name") is None
        assert li._properties.get("Director") is None
        assert li._properties.get("Creator") is None
        assert li._properties.get("AniList_Rating") is None

    def test_genre_infolabel_present_on_lean(self, tv_media):
        # Base genre stays available via the infolabel for row display.
        li = build_item(tv_media)
        assert "Action" in li._info["video"]["genre"]

    def test_tmdb_id_surrogate_when_unmapped(self, tv_media):
        _reset_season_map()
        li = build_item(tv_media)
        tmdb_id = int(li._properties["tmdb_id"])
        assert identity.is_surrogate(tmdb_id)
        assert identity.decode_surrogate(tmdb_id) == ("anilist", 101922)
        assert li._unique_ids.get("tmdb") == str(tmdb_id)

    def test_tmdb_id_real_when_mapped(self, tv_media):
        _reset_season_map(by_anilist={"101922": [359556, 1, 85937, 1, None]})
        li = build_item(tv_media)
        assert li._properties["tmdb_id"] == "85937"
        assert li._unique_ids.get("tmdb") == "85937"

    def test_folderpath_set_for_tv(self, tv_media):
        li = build_item(tv_media)
        fp = li._properties.get("folderpath", "")
        assert "mal_id=40748" in fp
        assert "seasons" in fp

    def test_media_without_description(self):
        media = load_fixture("anime_detail.json")
        media["description"] = None
        li = build_item(media)
        assert li._info["video"]["plot"] == ""


class TestBuildItems:
    def test_filters_out_media_without_mal_id(self):
        media_list = load_fixture("anime_list.json")
        items = build_items(media_list)
        # The fixture has one entry with idMal=null; it must be skipped.
        assert len(items) == 2

    def test_all_items_have_labels(self):
        media_list = load_fixture("anime_list.json")
        items = build_items(media_list)
        for li in items:
            assert li.label


# ---------------------------------------------------------------------------
# build_detail_item — the More-Info header tier (full enrichment)
# ---------------------------------------------------------------------------
class TestBuildDetailItem:
    @pytest.fixture
    def tv_media(self):
        return load_fixture("anime_detail.json")

    def test_header_carries_indexed_genre(self, tv_media):
        li = build_detail_item(tv_media)
        assert li._properties.get("Genre.1.Name") == "Action"

    def test_header_carries_studio(self, tv_media):
        li = build_detail_item(tv_media)
        assert "ufotable" in li._properties.get("Studio", "")

    def test_header_carries_rating_and_status(self, tv_media):
        li = build_detail_item(tv_media)
        assert li._properties.get("AniList_Rating") == "8.3"
        assert li._properties.get("Status") == "FINISHED"

    def test_header_carries_director_and_creator(self, tv_media):
        li = build_detail_item(tv_media)
        assert "Sotozaki" in li._properties.get("Director", "")
        assert "Gotouge" in li._properties.get("Creator", "")


# ---------------------------------------------------------------------------
# build_spotlight_item — the rich hero tier (enrichment + G11 ratings)
# ---------------------------------------------------------------------------
class TestBuildSpotlightItem:
    @pytest.fixture
    def tv_media(self):
        return load_fixture("anime_detail.json")

    def test_spotlight_carries_indexed_props(self, tv_media):
        li = build_spotlight_item(tv_media)
        assert li._properties.get("Genre.1.Name") == "Action"
        assert li._properties.get("AniList_Rating") == "8.3"

    def test_spotlight_sets_imdb_trakt_ratings_for_cast_thumb(self, tv_media):
        # G11: the hero cast-thumb/rating UI is gated on a rating being present;
        # mirror the AniList score into the IMDb/Trakt slots so it shows.
        li = build_spotlight_item(tv_media)
        assert li._properties.get("IMDb_Rating") == "8.3"
        assert li._properties.get("Trakt_Rating") == "8.3"

    def test_spotlight_omits_relations_summary(self, tv_media):
        # The relations summary is a detailed/header-only property.
        li = build_spotlight_item(tv_media)
        assert li._properties.get("relations") is None


# ---------------------------------------------------------------------------
# build_cast_item
# ---------------------------------------------------------------------------
class TestBuildCastItem:
    def test_returns_none_when_no_name(self):
        va = {"id": 1, "name": {}, "image": {}}
        assert build_cast_item(va, "Tanjiro") is None

    def test_label_is_va_name(self):
        va = {"id": 95549, "name": {"userPreferred": "Natsuki Hanae"}, "image": {"large": "https://example.com/img.jpg"}}
        li = build_cast_item(va, "Tanjiro Kamado")
        assert li.label == "Natsuki Hanae"

    def test_role_property(self):
        va = {"id": 95549, "name": {"userPreferred": "Natsuki Hanae"}, "image": {"large": ""}}
        li = build_cast_item(va, "Tanjiro Kamado")
        assert li._properties["role"] == "Tanjiro Kamado"

    def test_dbtype_person(self):
        va = {"id": 95549, "name": {"userPreferred": "Natsuki Hanae"}, "image": {}}
        li = build_cast_item(va, "Char")
        assert li._properties["DBType"] == "person"


# ---------------------------------------------------------------------------
# build_crew_item
# ---------------------------------------------------------------------------
class TestBuildCrewItem:
    def test_returns_none_when_no_name(self):
        assert build_crew_item({"id": 1, "name": {}}, "Director") is None

    def test_label_and_job(self):
        node = {"id": 123, "name": {"userPreferred": "Haruo Sotozaki"}, "image": {}}
        li = build_crew_item(node, "Director")
        assert li.label == "Haruo Sotozaki"
        assert li._properties["job"] == "Director"


# ---------------------------------------------------------------------------
# build_episode_item
# ---------------------------------------------------------------------------
class TestBuildEpisodeItem:
    def test_label_defaults_to_sxxeyy(self):
        li = build_episode_item(40748, 3, "Demon Slayer", total_eps=7)
        assert "S01E03" in li.label

    def test_label_uses_ep_name_when_provided(self):
        li = build_episode_item(40748, 1, "Demon Slayer", ep_name="Flame Hashira")
        assert "Flame Hashira" in li.label

    def test_info_episode_number(self):
        li = build_episode_item(40748, 5, "Demon Slayer")
        assert li._info["video"]["episode"] == 5

    def test_info_season(self):
        li = build_episode_item(40748, 5, "Demon Slayer", season=2)
        assert li._info["video"]["season"] == 2

    def test_info_tvshowtitle(self):
        li = build_episode_item(40748, 1, "My Show Title")
        assert li._info["video"]["tvshowtitle"] == "My Show Title"

    def test_property_mal_id(self):
        li = build_episode_item(40748, 1, "Demon Slayer")
        assert li._properties["mal_id"] == "40748"

    def test_property_dbtype_episode(self):
        li = build_episode_item(40748, 1, "Demon Slayer")
        assert li._properties["DBType"] == "episode"

    def test_path_is_deferred_play_route(self):
        # Episode items route through the helper's own info=play route; the
        # actual backend URL (Otaku/WNT2/Fanime) is resolved later at click
        # time by play(), so the click works per the configured plugin.
        li = build_episode_item(40748, 3, "Demon Slayer")
        assert "plugin.video.8nime.bingie.helper" in li._path
        assert "info=play" in li._path
        assert "mal_id=40748" in li._path
        assert "episode=3" in li._path

    def test_episode_item_is_playable(self):
        li = build_episode_item(40748, 3, "Demon Slayer")
        assert li._properties.get("IsPlayable") == "true"

    def test_total_episodes_property(self):
        li = build_episode_item(40748, 1, "Demon Slayer", total_eps=26)
        assert li._properties["TotalEpisodes"] == "26"

    def test_aired_date_set_in_info(self):
        li = build_episode_item(40748, 1, "Demon Slayer", ep_aired="2021-10-10")
        assert li._info["video"].get("aired") == "2021-10-10"

    def test_in_progress_sets_partial_resume_point(self):
        # In-progress episode -> the skin renders a PARTIAL bar at pos/dur (IsResumable),
        # and playcount stays 0 so the full "fake" bar does NOT show.
        li = build_episode_item(40748, 3, "Demon Slayer", resume_pos=600, resume_dur=1440)
        tag = li.getVideoInfoTag()
        assert tag.isResumable() is True
        assert tag.getPercentPlayed() == 42  # round(600/1440*100)
        assert li._info["video"]["playcount"] == 0

    def test_completed_sets_playcount_not_resume(self):
        # Completed episode -> playcount=1 (full bar), NOT resumable (no partial bar).
        li = build_episode_item(40748, 3, "Demon Slayer", watched=True)
        assert li._info["video"]["playcount"] == 1
        assert li.getVideoInfoTag().isResumable() is False
        assert li.getVideoInfoTag().getPercentPlayed() == 0

    def test_unwatched_has_no_resume_point(self):
        li = build_episode_item(40748, 3, "Demon Slayer")
        assert li._info["video"]["playcount"] == 0
        assert li.getVideoInfoTag().isResumable() is False

    def test_resume_ignored_without_duration(self):
        # No known duration -> can't compute a fraction, so no resume point.
        li = build_episode_item(40748, 3, "Demon Slayer", resume_pos=600, resume_dur=0)
        assert li.getVideoInfoTag().getResumeTime() == 0

    def test_resume_ignored_when_position_past_duration(self):
        li = build_episode_item(40748, 3, "Demon Slayer", resume_pos=1500, resume_dur=1440)
        assert li.getVideoInfoTag().getResumeTime() == 0


# ---------------------------------------------------------------------------
# build_season_item
# ---------------------------------------------------------------------------
class TestBuildSeasonItem:
    def test_label_default(self):
        li = build_season_item(40748, "Demon Slayer", 7)
        assert "Season 1" in li.label

    def test_label_custom(self):
        li = build_season_item(40748, "Demon Slayer", 7, label="Mugen Train Arc")
        assert li.label == "Mugen Train Arc"

    def test_info_season_number(self):
        li = build_season_item(40748, "Demon Slayer", 7, season=2)
        assert li._info["video"]["season"] == 2

    def test_info_episode_count(self):
        li = build_season_item(40748, "Demon Slayer", 7)
        assert li._info["video"]["episode"] == 7

    def test_property_dbtype_season(self):
        li = build_season_item(40748, "Demon Slayer", 7)
        assert li._properties["DBType"] == "season"

    def test_path_is_episodes_url(self):
        li = build_season_item(40748, "Demon Slayer", 7)
        assert "episodes" in li._path
        assert "mal_id=40748" in li._path

    def test_season_carries_year_rating_classification(self):
        media = {"startDate": {"year": 2021}, "averageScore": 83, "format": "TV", "isAdult": False}
        li = build_season_item(40748, "Demon Slayer", 7, season=1, media=media)
        info = li._info["video"]
        assert info["year"] == 2021
        assert abs(info["rating"] - 8.3) < 0.01
        assert info["mpaa"] == "PG-13"
        assert li._properties.get("AniList_Rating") == "8.3"

    def test_season_adult_classification(self):
        media = {"isAdult": True, "format": "TV"}
        li = build_season_item(40748, "X", 12, media=media)
        assert li._info["video"]["mpaa"] == "R18+"


# ---------------------------------------------------------------------------
# build_review_item
# ---------------------------------------------------------------------------
class TestBuildReviewItem:
    def test_returns_none_when_no_content(self):
        review = {"user": {"name": "User1"}, "summary": "", "body": ""}
        assert build_review_item(review) is None

    def test_label_is_summary_when_available(self):
        review = {
            "user": {"name": "User1", "avatar": {}},
            "summary": "Great anime!",
            "body": "Full review text here.",
            "score": 90,
        }
        li = build_review_item(review)
        assert li.label == "Great anime!"

    def test_author_property(self):
        review = {
            "user": {"name": "CoolUser", "avatar": {}},
            "summary": "A review",
            "body": "Great show.",
        }
        li = build_review_item(review)
        assert li._properties["author"] == "CoolUser"

    def test_content_property_contains_body(self):
        review = {
            "user": {"name": "CoolUser", "avatar": {}},
            "summary": "A review",
            "body": "<b>Amazing</b> show.",
        }
        li = build_review_item(review)
        # body should have HTML stripped
        assert "Amazing" in li._properties["content"]
        assert "<b>" not in li._properties["content"]


# ---------------------------------------------------------------------------
# build_video_item
# ---------------------------------------------------------------------------
class TestBuildVideoItem:
    def test_youtube_trailer_item(self):
        media = load_fixture("anime_detail.json")
        li = build_video_item(media)
        assert li is not None
        assert "Trailer" in li.label
        assert "youtube" in li._path

    def test_non_youtube_returns_none(self):
        media = {"title": {"english": "Test"}, "trailer": {"id": "x", "site": "vimeo"}}
        assert build_video_item(media) is None

    def test_no_trailer_returns_none(self):
        media = {"title": {"english": "Test"}, "trailer": None}
        assert build_video_item(media) is None
