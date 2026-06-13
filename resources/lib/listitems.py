# -*- coding: utf-8 -*-
import re
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import art_overrides, enrichment, identity
from resources.lib.constants import PLUGIN_URL
from resources.lib.playback import (
    browse_show_path,
    helper_play_url,
    play_episode_path,
    play_movie_path,
)
from resources.lib.titles import title_for_media

ADDON = xbmcaddon.Addon()

# The indexed-property enrichment + its staff helpers now live in enrichment.py
# (so build_item can apply them by richness tier). Re-exported here for callers
# and tests that still import them from listitems.
ITER_PROPS_MAX = enrichment.ITER_PROPS_MAX
_staff_name = enrichment._staff_name
_is_creator_role = enrichment._is_creator_role
_collect_creators = enrichment._collect_creators
apply_bingie_properties = enrichment.apply_indexed


def _title(media):
    return title_for_media(media)


def _clean_description(text):
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("[I]", "").replace("[/I]", "")
    text = text.replace("[B]", "").replace("[/B]", "")
    return text.strip()


def _is_movie(media):
    fmt = (media.get("format") or "").upper()
    return fmt == "MOVIE" or fmt == "ONE_SHOT"


def _trailer_url(media):
    trailer = media.get("trailer") or {}
    site = (trailer.get("site") or "").lower()
    video_id = trailer.get("id")
    if site == "youtube" and video_id:
        return f"plugin://plugin.video.youtube/play/?video_id={video_id}"
    if site == "dailymotion" and video_id:
        return f"plugin://plugin.video.dailymotion_com/?url={video_id}&mode=playVideo"
    return None


def _build_art(media, is_movie):
    cover = media.get("coverImage") or {}
    poster = cover.get("extraLarge") or cover.get("large")
    banner = media.get("bannerImage")
    backdrop = banner or poster
    if not backdrop:
        return {}

    thumb = cover.get("large") or poster or backdrop
    landscape = banner or poster

    art = {
        "poster": poster,
        "thumb": thumb,
        "icon": thumb,
        "banner": banner or backdrop,
        "landscape": landscape,
        "fanart": backdrop,
        "fanart1": backdrop,
        "fanart2": backdrop,
    }
    if not is_movie:
        art.update(
            {
                "tvshow.poster": poster,
                "tvshow.thumb": thumb,
                "tvshow.banner": art["banner"],
                "tvshow.landscape": landscape,
                "tvshow.fanart": backdrop,
                "tvshow.fanart1": backdrop,
                "tvshow.fanart2": backdrop,
            }
        )
    # User artwork override (More-Info 'Change artwork', G6) wins over AniList art.
    override = art_overrides.get(media.get("idMal"))
    if override.get("poster"):
        art["poster"] = override["poster"]
        if not is_movie:
            art["tvshow.poster"] = override["poster"]
    if override.get("fanart"):
        art["fanart"] = override["fanart"]
        if not is_movie:
            art["tvshow.fanart"] = override["fanart"]
    return art


def _helper_url(**params):
    return f"{PLUGIN_URL}/?{urlencode(params)}"


def _tmdb_id_str(media, mal_id):
    """Skin-facing tmdb_id (real Fribb id or stable surrogate); falls back to mal."""
    tmdb_id = identity.to_tmdb_id(anilist_id=media.get("id") if media else None, mal_id=mal_id)
    return str(tmdb_id) if tmdb_id is not None else str(mal_id)


def _apply_tier(li, media, tier):
    """Apply the richness tier. Lean rows carry only the base fields set above."""
    if tier == "header":
        enrichment.apply_header(li, media)
    elif tier == "spotlight":
        enrichment.apply_spotlight(li, media)


def build_item(media, tier="lean"):
    mal_id = media.get("idMal")
    if not mal_id:
        return None

    is_movie = _is_movie(media)
    label = _title(media)
    li = xbmcgui.ListItem(label=label)

    start = media.get("startDate") or {}
    year = start.get("year") or 0
    score = media.get("averageScore")
    plot = _clean_description(media.get("description"))
    genres = media.get("genres") or []
    episodes = media.get("episodes") or 0
    studio_names = []
    for edge in (media.get("studios") or {}).get("edges") or []:
        name = (edge.get("node") or {}).get("name")
        if name:
            studio_names.append(name)

    info = {
        "title": label,
        "year": year,
        "plot": plot,
        "genre": ", ".join(genres),
        "mediatype": "movie" if is_movie else "tvshow",
    }
    if studio_names:
        info["studio"] = " / ".join(studio_names)
    if not is_movie:
        progress = media.get("_progress") or 0
        if progress:
            info["episode"] = progress
        info["status"] = media.get("status") or ""
        if episodes:
            info["season"] = 1

    if score:
        info["rating"] = score / 10.0

    trailer_url = _trailer_url(media)
    if trailer_url:
        info["trailer"] = trailer_url

    duration = media.get("duration")
    if duration:
        info["duration"] = int(duration) * 60

    li.setInfo("video", info)

    art = _build_art(media, is_movie)
    if art:
        li.setArt(art)
        li.setProperty("fanart", art["fanart"])
        li.setProperty("landscape", art.get("landscape", art["fanart"]))

    dbtype = "movie" if is_movie else "tvshow"
    li.setProperty("DBType", dbtype)
    li.setProperty("DBTYPE", dbtype)
    li.setProperty("mediatype", dbtype)
    li.setProperty("tmdb_type", "movie" if is_movie else "tv")
    # Skin-facing identity is tmdb_id everywhere (real Fribb id or surrogate);
    # mal_id/anilist_id are retained as internal props the helper reverse-maps from.
    tmdb_str = _tmdb_id_str(media, mal_id)
    li.setProperty("tmdb_id", tmdb_str)
    li.setProperty("mal_id", str(mal_id))
    li.setProperty("anilist_id", str(media.get("id") or ""))
    li.setProperty("imdbnumber", "")
    try:
        li.setUniqueIDs({"tmdb": tmdb_str, "mal": str(mal_id)})
    except Exception:
        pass

    # The skin's Play button does PlayMedia($INFO[ListItem.FolderPath]) /
    # PlayMedia($INFO[ListItem.FilenameAndPath]) (FolderPath+isdir = navigate,
    # FilenameAndPath = play). Wire those so Play actually resolves through the
    # helper's info=play route (which the configured provider then plays).
    if is_movie:
        play = helper_play_url(mal_id, is_movie=True, title=label)
        li.setProperty("IsPlayable", "true")
        li.setProperty("folderpath", play)
        li.setProperty("filenameandpath", play)
        _apply_tier(li, media, tier)
        li.setPath(play)
        return li

    # TV: clicking navigates into the seasons browse (FolderPath), while the Play
    # button plays the latest aired episode (FilenameAndPath, no episode -> play()
    # resolves the latest). This is what the spotlight "Play" expects.
    browse = browse_show_path(mal_id)
    if browse:
        li.setProperty("folderpath", browse)
        li.setProperty("IsPlayable", "false")
    li.setProperty("filenameandpath", helper_play_url(mal_id, title=label))

    _apply_tier(li, media, tier)

    li.setPath(PLUGIN_URL)
    return li


def build_detail_item(media):
    """More-Info header item: the full extended-metadata tier."""
    return build_item(media, tier="header")


def build_spotlight_item(media):
    """Spotlight hero item: the rich tier (ratings + cast for the hero panel)."""
    return build_item(media, tier="spotlight")


def build_cast_item(va, character_name, index=0):
    name = _staff_name(va)
    if not name:
        return None
    li = xbmcgui.ListItem(label=name)
    thumb = ((va.get("image") or {}).get("large") or "")
    art = {"thumb": thumb, "poster": thumb, "icon": thumb} if thumb else {}
    if art:
        li.setArt(art)
    li.setInfo("video", {"title": name, "plot": character_name, "mediatype": "video"})
    li.setProperty("DBType", "person")
    li.setProperty("DBTYPE", "person")
    li.setProperty("tmdb_type", "person")
    # Person items carry the AniList staff/VA id in the tmdb_id slot by design; the
    # helper's crew_in_* routes interpret it as a staff id (not a Fribb tmdb id).
    li.setProperty("tmdb_id", str(va.get("id") or ""))
    li.setProperty("role", character_name)
    li.setProperty("Cast.1.Name", name)
    li.setProperty("Cast.1.Role", character_name)
    li.setProperty("Cast.1.Thumb", thumb)
    li.setPath(PLUGIN_URL)
    return li


def build_crew_item(staff_node, role):
    name = _staff_name(staff_node)
    if not name:
        return None
    li = xbmcgui.ListItem(label=name)
    thumb = ((staff_node.get("image") or {}).get("large") or "")
    art = {"thumb": thumb, "poster": thumb, "icon": thumb} if thumb else {}
    if art:
        li.setArt(art)
    li.setInfo("video", {"title": name, "plot": role, "mediatype": "video"})
    li.setProperty("DBType", "person")
    li.setProperty("DBTYPE", "person")
    li.setProperty("tmdb_type", "person")
    # AniList staff id in the tmdb_id slot (see build_cast_item).
    li.setProperty("tmdb_id", str(staff_node.get("id") or ""))
    li.setProperty("job", role)
    li.setPath(PLUGIN_URL)
    return li


def build_video_item(media, trailer=None):
    trailer = trailer or media.get("trailer") or {}
    site = (trailer.get("site") or "").lower()
    video_id = trailer.get("id")
    if site != "youtube" or not video_id:
        return None
    label = f"{_title(media)} Trailer"
    li = xbmcgui.ListItem(label=label)
    thumb = f"https://img.youtube.com/vi/{video_id}/0.jpg"
    li.setArt({"thumb": thumb, "poster": thumb, "icon": thumb})
    li.setInfo("video", {"title": label, "plot": "YouTube", "mediatype": "video"})
    li.setProperty("DBType", "video")
    li.setProperty("DBTYPE", "video")
    li.setPath(f"plugin://plugin.video.youtube/play/?video_id={video_id}")
    return li


def build_review_item(review, index=0):
    user = review.get("user") or {}
    author = user.get("name") or "AniList User"
    summary = review.get("summary") or ""
    body = _clean_description(review.get("body") or "")
    content = body or summary
    if not content:
        return None
    label = summary or f"Review by {author}"
    li = xbmcgui.ListItem(label=label)
    avatar = ((user.get("avatar") or {}).get("large") or "")
    if avatar:
        li.setArt({"thumb": avatar, "poster": avatar, "icon": avatar})
    li.setInfo("video", {"title": label, "plot": content, "mediatype": "video"})
    li.setProperty("DBType", "review")
    li.setProperty("author", author)
    li.setProperty("content", content)
    li.setProperty("review.author", author)
    li.setProperty("review.content", content)
    li.setPath(PLUGIN_URL)
    return li


def _episode_art_from_media(media, episode=1, thumb_url=None):
    """Episode art. Prefers a real per-episode still (Kitsu); falls back to show art."""
    cover = media.get("coverImage") or {}
    poster = cover.get("extraLarge") or cover.get("large")
    banner = media.get("bannerImage") or poster
    landscape = thumb_url or banner or poster
    if not landscape:
        return {}
    fanart = banner or poster or landscape
    return {
        "thumb": landscape,
        "poster": poster or landscape,
        "icon": landscape,
        "landscape": landscape,
        "fanart": fanart,
        "tvshow.thumb": landscape,
        "tvshow.poster": poster or landscape,
        "tvshow.landscape": landscape,
        "tvshow.fanart": fanart,
        "season.landscape": landscape,
    }


def build_episode_item(
    mal_id,
    episode,
    show_title,
    total_eps=0,
    art=None,
    season=1,
    label=None,
    media=None,
    thumb_url=None,
    play_title=None,
    ep_name=None,
    ep_plot=None,
    ep_aired=None,
    play_episode=None,
):
    season = int(season or 1)
    episode = int(episode or 1)
    # Prefer the real TMDB episode title for the label ("3. Abrupt Approach");
    # fall back to SxxExx when TMDB has no name.
    if not label:
        label = f"{episode}. {ep_name}" if ep_name else f"S{season:02d}E{episode:02d}"
    li = xbmcgui.ListItem(label=label)
    # show_title is the franchise umbrella (display/tvshowtitle). play_title is the
    # per-cour season-specific title used by search-based backends (WNT2/fanime),
    # where "{title} Episode {N}" must disambiguate the season. Otaku ignores it
    # (resolves by mal_id+local episode), so falling back to show_title is safe.
    # Route through the deferred info=play route (resolved at click time by the
    # play() handler) rather than baking the backend URL into the item. Otaku
    # resolves to a playable; search backends (WNT2/Fanime) return a directory
    # that can't be set as a playable path -- play() opens those via ActivateWindow.
    # Setting the search URL directly here made clicking an episode try to "play a
    # folder" and silently fail.
    # play_episode lets a TMDB-split season display a season-local number while
    # playing the absolute AniList episode the backends key on (defaults to the
    # displayed episode for normal cours).
    play = helper_play_url(mal_id, play_episode or episode, title=play_title or show_title)
    info = {
        "title": ep_name or label,
        "tvshowtitle": show_title,
        "season": season,
        "episode": episode,
        "mediatype": "episode",
    }
    if ep_plot:
        info["plot"] = ep_plot
    if ep_aired:
        info["aired"] = ep_aired
        info["premiered"] = ep_aired
    li.setInfo("video", info)
    if not art:
        art = _episode_art_from_media(media, episode, thumb_url=thumb_url) if media else {}
        if not art and thumb_url:
            art = {"thumb": thumb_url, "landscape": thumb_url, "icon": thumb_url}
    if art:
        li.setArt(art)
        if art.get("landscape"):
            li.setProperty("landscape", art["landscape"])
        if art.get("fanart"):
            li.setProperty("fanart", art["fanart"])
    li.setProperty("DBType", "episode")
    li.setProperty("DBTYPE", "episode")
    li.setProperty("mediatype", "episode")
    li.setProperty("mal_id", str(mal_id))
    li.setProperty("tmdb_id", _tmdb_id_str(media, mal_id))
    li.setProperty("tmdb_type", "tv")
    if total_eps:
        li.setProperty("TotalEpisodes", str(total_eps))
    li.setProperty("IsPlayable", "true")
    li.setProperty("folderpath", play)
    li.setProperty("filenameandpath", play)
    li.setPath(play)
    return li


def build_season_item(mal_id, show_title, episode_count, season=1, label=None, media=None):
    season = int(season or 1)
    status = ((media or {}).get("status") or "").upper()
    if not label:
        if status == "NOT_YET_RELEASED" and not episode_count:
            label = f"Season {season} (Upcoming)"
        else:
            label = f"Season {season}"
    li = xbmcgui.ListItem(label=label)
    params = {
        "info": "episodes",
        "mal_id": str(mal_id),
        "tmdb_type": "tv",
        "season": str(season),
    }
    episodes_url = _helper_url(**params)
    media = media or {}
    start = media.get("startDate") or {}
    year = start.get("year") or 0
    score = media.get("averageScore")
    season_info = {
        "title": label,
        "tvshowtitle": show_title,
        "season": season,
        "episode": episode_count,
        "mediatype": "season",
    }
    # Per-season classification/rating/year so the More-Info seasons list is
    # complete on first paint (the header request bundles all seasons).
    if year:
        season_info["year"] = year
        season_info["premiered"] = "%04d-01-01" % int(year)
    if score:
        season_info["rating"] = score / 10.0
    season_info["mpaa"] = _classification(media)
    li.setInfo("video", season_info)
    if score:
        rating = f"{score / 10.0:.1f}"
        li.setProperty("AniList_Rating", rating)
        li.setProperty("TMDb_Rating", rating)
    art = _episode_art_from_media(media) if media else {}
    if art:
        li.setArt(art)
        if art.get("landscape"):
            li.setProperty("landscape", art["landscape"])
    li.setProperty("DBType", "season")
    li.setProperty("DBTYPE", "season")
    li.setProperty("mal_id", str(mal_id))
    li.setProperty("tmdb_id", _tmdb_id_str(media, mal_id))
    li.setProperty("folderpath", episodes_url)
    li.setProperty("filenameandpath", episodes_url)
    li.setProperty("TotalEpisodes", str(episode_count or 0))
    li.setPath(episodes_url)
    return li


def _classification(media):
    """Derive a coarse content classification from AniList (no MPAA on AniList)."""
    if media.get("isAdult"):
        return "R18+"
    fmt = (media.get("format") or "").upper()
    if fmt in ("MOVIE", "ONE_SHOT"):
        return "PG-13"
    return "PG-13"


def build_poster_item(media, label=None):
    mal_id = media.get("idMal")
    if not mal_id:
        return None
    cover = media.get("coverImage") or {}
    poster = cover.get("extraLarge") or cover.get("large")
    if not poster:
        return None
    li = xbmcgui.ListItem(label=label or _title(media))
    li.setArt({"poster": poster, "thumb": poster, "icon": poster})
    li.setInfo("video", {"title": label or _title(media), "mediatype": "image"})
    li.setProperty("DBType", "image")
    li.setPath(poster)
    return li


def build_items(media_list, tier="lean"):
    items = []
    for media in media_list:
        li = build_item(media, tier=tier)
        if li:
            items.append(li)
    return items
