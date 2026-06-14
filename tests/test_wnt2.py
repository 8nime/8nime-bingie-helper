# -*- coding: utf-8 -*-
"""WatchNixtoons2 resolver tests. No live network — _request / movie_list are
patched per test; the regex parsing and scoring run on fixture strings."""
from unittest.mock import MagicMock, patch

from resources.lib import wnt2


def _resp(text):
    r = MagicMock()
    r.text = text
    return r


class TestNorm:
    def test_strips_punctuation_and_lowercases(self):
        assert wnt2._norm("Re:ZERO -Starting Life-") == "re zero starting life"

    def test_collapses_whitespace(self):
        assert wnt2._norm("  A   B  ") == "a b"


class TestPairScore:
    def test_exact_is_one(self):
        assert wnt2._pair_score("re zero", "re zero") == 1.0

    def test_containment_beats_fuzzy(self):
        assert wnt2._pair_score("re zero starting life", "re zero") > 0.9

    def test_unrelated_is_low(self):
        assert wnt2._pair_score("naruto", "bleach") < 0.5

    def test_empty_is_zero(self):
        assert wnt2._pair_score("", "x") == 0.0


class TestBestSeries:
    def test_exact_match_beats_superset(self):
        cands = [("/a", "Naruto Shippuden"), ("/b", "Naruto")]
        link, name, score = wnt2.best_series(cands, "naruto")
        assert (link, name, score) == ("/b", "Naruto", 1.0)

    def test_no_titles_returns_none(self):
        assert wnt2.best_series([("/a", "X")]) == (None, None, 0.0)


class TestSlice:
    def test_extracts_segment_with_start(self):
        assert wnt2._slice("xxSTARTmidENDyy", "START", "END") == "STARTmid"

    def test_missing_start_returns_empty(self):
        assert wnt2._slice("abc", "Z", "Y") == ""


class TestEpisodeNumber:
    def test_basic(self):
        assert wnt2._episode_number("Episode 12 English Subbed") == 12

    def test_leading_zero(self):
        assert wnt2._episode_number("Episode 03") == 3

    def test_no_number(self):
        assert wnt2._episode_number("Movie") is None


class TestMatchEpisode:
    EPS = [
        ("/e12", "Episode 12", "sub"),
        ("/e1s", "Episode 1", "sub"),
        ("/e1d", "Episode 1", "dub"),
    ]

    def test_prefers_requested_sub(self):
        assert wnt2.match_episode(self.EPS, 1, lang="sub") == ("/e1s", "Episode 1", "sub")

    def test_prefers_requested_dub(self):
        assert wnt2.match_episode(self.EPS, 1, lang="dub") == ("/e1d", "Episode 1", "dub")

    def test_no_match_returns_none(self):
        assert wnt2.match_episode(self.EPS, 99) is None


class TestEpisodeSeason:
    def test_unmarked_is_one(self):
        assert wnt2._episode_season("Episode 1 English Subbed") == 1

    def test_season_marker(self):
        assert wnt2._episode_season("Season 4 Episode 10 English Subbed") == 4

    def test_ordinal_season(self):
        assert wnt2._episode_season("2nd Season Episode 3") == 2

    def test_roman_sequel(self):
        assert wnt2._episode_season("Mushoku Tensei II: Jobless Reincarnation Episode 1") == 2


class TestEpisodeNumberFractional:
    def test_drops_fractional_special(self):
        # "Episode 12.5" is a special; it must not collide with integer ep 12.
        assert wnt2._episode_number("Season 2 Episode 12.5 English Dubbed") is None

    def test_keeps_letter_suffix(self):
        assert wnt2._episode_number("Episode 1B English Subbed") == 1


class TestEpisodeLang:
    def test_uses_data_lang_attr(self):
        assert wnt2._episode_lang("Episode 1", "dub") == "dub"

    def test_parses_dub_from_name(self):
        assert wnt2._episode_lang("Episode 1 English Dubbed", None) == "dub"

    def test_parses_sub_from_name(self):
        assert wnt2._episode_lang("Episode 1 English Subbed", None) == "sub"

    def test_unknown(self):
        assert wnt2._episode_lang("Episode 1", None) is None


class TestMatchesShow:
    def test_bare_name_always_matches(self):
        assert wnt2._matches_show("Episode 1 English Subbed", ["anything"]) is True

    def test_spinoff_prefix_filtered(self):
        # 'Visions of Coleus' is a spin-off embedded on the Slime page.
        assert wnt2._matches_show(
            "Visions of Coleus Episode 1 English Dubbed",
            ["that time i got reincarnated as a slime"],
        ) is False

    def test_show_titled_episode_matches(self):
        assert wnt2._matches_show(
            "Mushoku Tensei: Jobless Reincarnation Episode 1 English Dubbed",
            ["mushoku tensei jobless reincarnation"],
        ) is True


class TestMatchEpisodeSeasonAware:
    # A wcostream-style aggregated list (newest season first), with an OVA and a
    # fractional special that must lose to the real season-1 episode.
    EPS = [
        ("/s4e1", "Season 4 Episode 1 English Subbed", "sub"),
        ("/s2e1", "Season 2 Episode 1 English Subbed", "sub"),
        ("/s2e13", "Season 2 Episode 13 English Dubbed", "dub"),
        ("/ova1", "OVA Episode 1 English Subbed", "sub"),
        ("/sp", "Episode 1.5 English Subbed", "sub"),
        ("/s1e1d", "Episode 1 English Dubbed", "dub"),
        ("/s1e1s", "Episode 1 English Subbed", "sub"),
    ]

    def test_season_one_skips_newer_seasons_and_ova(self):
        # The original bug: bare number match returned Season 4. Season-aware must
        # return the unmarked season-1 episode, and a real one over the OVA.
        assert wnt2.match_episode(self.EPS, 1, season=1) == ("/s1e1s", "Episode 1 English Subbed", "sub")

    def test_targets_requested_season(self):
        assert wnt2.match_episode(self.EPS, 1, season=4) == ("/s4e1", "Season 4 Episode 1 English Subbed", "sub")

    def test_offset_maps_to_continuous_number(self):
        # Split-cour part 2: cour-local ep1 + offset 12 -> wcostream Season 2 ep13.
        hit = wnt2.match_episode(self.EPS, 1, season=2, offset=12)
        assert hit == ("/s2e13", "Season 2 Episode 13 English Dubbed", "dub")

    def test_offset_zero_is_part_one(self):
        assert wnt2.match_episode(self.EPS, 1, season=2, offset=0) == ("/s2e1", "Season 2 Episode 1 English Subbed", "sub")


class TestSearchSeriesParse:
    def test_parses_link_and_title(self):
        html = (
            'aramamotoru <a href="/anime/show" title="Show Name"> '
            '<img src="/img.jpg"> cizgiyazisi'
        )
        with patch.object(wnt2, "_request", return_value=_resp(html)):
            res = wnt2.search_series("show", "https://x", MagicMock())
        assert res == [("/anime/show", "Show Name")]


class TestEpisodeListParse:
    def test_parses_episodes(self):
        html = (
            'x name="pid" '
            '<a href="/show-episode-1-english-subbed" data-lang="sub">Episode 1</a> '
            '<a href="/show-episode-2-english-subbed" data-lang="sub">Episode 2</a> '
            "<!--CAT PAGE end"
        )
        with patch.object(wnt2, "_request", return_value=_resp(html)):
            eps = wnt2.episode_list("/anime/show", "https://x", MagicMock())
        assert [e[1] for e in eps] == ["Episode 1", "Episode 2"]
        assert eps[0][0] == "/show-episode-1-english-subbed"

    def test_second_call_is_cached_no_refetch(self):
        html = (
            'x name="pid" '
            '<a href="/show-episode-1-english-subbed" data-lang="sub">Episode 1</a> '
            "<!--CAT PAGE end"
        )
        with patch.object(wnt2, "_request", return_value=_resp(html)) as req:
            wnt2.episode_list("/anime/show", "https://x", MagicMock())
            wnt2.episode_list("/anime/show", "https://x", MagicMock())
        assert req.call_count == 1  # second resolve reused the parsed list


class TestResolveMovieUrl:
    MOVIES = [
        ("/x-english-dubbed", "X English Dubbed"),
        ("/x-english-subbed", "X English Subbed"),
    ]

    def test_prefers_subbed_variant(self):
        with patch.object(wnt2, "movie_list", return_value=self.MOVIES):
            url, dbg = wnt2.resolve_movie_url(["X"], "https://b", lang="sub")
        assert url == "/x-english-subbed"

    def test_prefers_dubbed_when_asked(self):
        with patch.object(wnt2, "movie_list", return_value=self.MOVIES):
            url, dbg = wnt2.resolve_movie_url(["X"], "https://b", lang="dub")
        assert url == "/x-english-dubbed"

    def test_below_min_score_returns_none(self):
        with patch.object(wnt2, "movie_list", return_value=[("/zzz", "Totally Different")]):
            url, dbg = wnt2.resolve_movie_url(["Frieren"], "https://b")
        assert url is None


class TestActionResolveUrl:
    def test_format(self):
        u = wnt2.actionresolve_url("/show-episode-1")
        assert u.startswith("plugin://plugin.video.watchnixtoons2/?")
        assert "action=actionResolve" in u
        assert "show-episode-1" in u
