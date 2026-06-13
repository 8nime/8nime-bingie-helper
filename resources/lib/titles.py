# -*- coding: utf-8 -*-
import re

import xbmcaddon

ADDON = xbmcaddon.Addon()
_NON_LATIN_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0e00-\u0e7f]")


def _best_english_synonym(synonyms):
    candidates = []
    for synonym in synonyms or []:
        text = (synonym or "").strip()
        if not text or _NON_LATIN_RE.search(text):
            continue
        if len(text) < 3:
            continue
        candidates.append(text)
    if not candidates:
        return ""
    return max(candidates, key=len)


def title_sort():
    """AniList MediaSort that matches the configured display title language.

    A name-sorted catalogue browse should read A->Z in the SAME titles the list
    shows, so map the helper's title_language setting onto AniList's verified
    MediaSort enum (TITLE_ROMAJI / TITLE_ENGLISH, both ascending by default).
    """
    preferred = ADDON.getSetting("title_language") or "english"
    return "TITLE_ROMAJI" if preferred == "romaji" else "TITLE_ENGLISH"


def title_for_media(media):
    titles = media.get("title") or {}
    preferred = ADDON.getSetting("title_language") or "english"
    if preferred == "romaji":
        return titles.get("romaji") or titles.get("english") or titles.get("userPreferred") or "Unknown"
    english = titles.get("english")
    if english:
        return english
    synonym = _best_english_synonym(media.get("synonyms"))
    if synonym:
        return synonym
    return titles.get("romaji") or titles.get("userPreferred") or "Unknown"
