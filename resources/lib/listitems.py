# -*- coding: utf-8 -*-
import re
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.constants import PLUGIN_URL
from resources.lib.playback import (
    browse_show_path,
    play_episode_path,
    play_movie_path,
)
from resources.lib.titles import title_for_media

ADDON = xbmcaddon.Addon()
ITER_PROPS_MAX = 20


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
    return art


def _helper_url(**params):
    return f"{PLUGIN_URL}/?{urlencode(params)}"


def _staff_name(node):
    name = node.get("name") or {}
    return name.get("userPreferred") or name.get("full") or ""


def _is_creator_role(role):
    role_up = (role or "").upper().strip()
    if not role_up or "STORYBOARD" in role_up:
        return False
    if role_up in {
        "ORIGINAL CREATOR",
        "STORY",
        "STORY & ART",
        "STORY AND ART",
        "ORIGINAL STORY",
        "CREATOR",
        "AUTHOR",
        "ORIGINAL PLAN",
        "ORIGINAL",
    }:
        return True
    if role_up.startswith(("ORIGINAL CREATOR", "ORIGINAL STORY")):
        return True
    return any(
        token in role_up
        for token in ("STORY & ART", "STORY AND ART", "ORIGINAL STORY", "ORIGINAL CREATOR")
    )


def _collect_creators(media):
    seen = set()
    creators = []

    def add(name, sid, job):
        key = (name, sid)
        if not name or key in seen:
            return
        seen.add(key)
        creators.append((name, sid, job))

    for edge in (media.get("staff") or {}).get("edges") or []:
        role = edge.get("role") or ""
        node = edge.get("node") or {}
        if _is_creator_role(role):
            add(_staff_name(node), str(node.get("id") or ""), role)

    if creators:
        return creators

    source = (media.get("source") or "").upper()
    if source not in {"MANGA", "NOVEL", "LIGHT_NOVEL", "WEB_NOVEL", "VISUAL_NOVEL", "OTHER"}:
        return creators

    for edge in (media.get("relations") or {}).get("edges") or []:
        rel_type = (edge.get("relationType") or "").upper()
        if rel_type not in {"ADAPTATION", "SOURCE", "PREQUEL", "ALTERNATIVE", "CHARACTER"}:
            continue
        node = edge.get("node") or {}
        node_type = (node.get("type") or "").upper()
        node_format = (node.get("format") or "").upper()
        if node_type not in {"MANGA", "NOVEL"} and node_format not in {"MANGA", "NOVEL", "ONE_SHOT"}:
            continue
        for staff_edge in (node.get("staff") or {}).get("edges") or []:
            role = staff_edge.get("role") or ""
            staff_node = staff_edge.get("node") or {}
            if _is_creator_role(role):
                add(_staff_name(staff_node), str(staff_node.get("id") or ""), role)
        if creators:
            break

    return creators


def apply_bingie_properties(li, media, detailed=False):
    """Set indexed properties Bingie info dialog reads from container 17195."""
    genres = media.get("genres") or []
    genre_line = ", ".join(genres)
    if genre_line:
        li.setProperty("Genre", genre_line)
    for idx, genre in enumerate(genres[:ITER_PROPS_MAX], start=1):
        li.setProperty(f"Genre.{idx}.Name", genre)
        li.setProperty(f"Genre.{idx}.TMDb_ID", genre)

    studios = []
    for edge in (media.get("studios") or {}).get("edges") or []:
        node = edge.get("node") or {}
        if node.get("name"):
            studios.append(node)

    studio_names = []
    for idx, studio in enumerate(studios[:ITER_PROPS_MAX], start=1):
        name = studio.get("name", "")
        li.setProperty(f"Studio.{idx}.Name", name)
        li.setProperty(f"Studio.{idx}.TMDB_ID", name)
        li.setProperty(f"Network.{idx}.Name", name)
        li.setProperty(f"Network.{idx}.TMDB_ID", name)
        studio_names.append(name)

    if studio_names:
        joined = " / ".join(studio_names)
        li.setProperty("studio", joined)
        li.setProperty("Studio", joined)
        li.setProperty("Network", joined)

    cast_names = []
    for idx, edge in enumerate((media.get("characters") or {}).get("edges") or [], start=1):
        if idx > ITER_PROPS_MAX:
            break
        role = edge.get("role") or ""
        char_node = edge.get("node") or {}
        char_name = _staff_name(char_node)
        vas = edge.get("voiceActors") or []
        va = vas[0] if vas else {}
        va_name = _staff_name(va) if va else ""
        va_id = str(va.get("id") or "")
        va_img = ((va.get("image") or {}).get("large") or "")
        if va_name:
            li.setProperty(f"Cast.{idx}.Name", va_name)
            li.setProperty(f"Cast.{idx}.name", va_name)
            li.setProperty(f"Cast.{idx}.Role", char_name)
            li.setProperty(f"Cast.{idx}.Thumb", va_img)
            li.setProperty(f"Cast.{idx}.TMDb_ID", va_id)
            cast_names.append(va_name)

    if cast_names:
        li.setProperty("cast", " / ".join(cast_names))

    directors, writers = [], []
    creators = _collect_creators(media)
    for edge in (media.get("staff") or {}).get("edges") or []:
        role = (edge.get("role") or "").upper()
        node = edge.get("node") or {}
        name = _staff_name(node)
        sid = str(node.get("id") or "")
        if not name:
            continue
        if "DIRECTOR" in role and "ASSISTANT DIRECTOR" not in role:
            directors.append((name, sid, role))
        elif "SERIES COMPOSITION" in role or "SCRIPT" in role or "SCREENPLAY" in role:
            writers.append((name, sid, role))

    director_names = []
    for idx, (name, sid, job) in enumerate(directors[:5], start=1):
        li.setProperty(f"Director.{idx}.name", name)
        li.setProperty(f"Director.{idx}.TMDb_ID", sid)
        li.setProperty(f"Director.{idx}.job", job)
        director_names.append(name)

    if director_names:
        li.setProperty("Director", " / ".join(director_names))

    creator_names = []
    for idx, (name, sid, job) in enumerate(creators[:3], start=1):
        li.setProperty(f"Creator.{idx}.name", name)
        li.setProperty(f"Creator.{idx}.TMDb_ID", sid)
        li.setProperty(f"Creator.{idx}.job", job)
        creator_names.append(name)

    if creator_names:
        li.setProperty("Creator", " / ".join(creator_names))

    writer_names = []
    for idx, (name, sid, job) in enumerate(writers[:5], start=1):
        li.setProperty(f"Writer.{idx}.name", name)
        li.setProperty(f"Writer.{idx}.TMDb_ID", sid)
        li.setProperty(f"Writer.{idx}.job", job)
        writer_names.append(name)

    if writer_names:
        li.setProperty("Writer", " / ".join(writer_names))

    score = media.get("averageScore")
    if score:
        rating = f"{score / 10.0:.1f}"
        li.setProperty("AniList_Rating", rating)
        li.setProperty("TMDb_Rating", rating)

    if media.get("status"):
        li.setProperty("Status", media["status"])

    if detailed:
        relations = []
        for edge in (media.get("relations") or {}).get("edges") or []:
            node = edge.get("node") or {}
            if node.get("idMal"):
                rel = edge.get("relationType") or ""
                relations.append(f"{rel}:{node.get('idMal')}")
        if relations:
            li.setProperty("relations", ",".join(relations[:10]))


def build_item(media, detailed=False):
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
    li.setProperty("tmdb_id", str(mal_id))
    li.setProperty("mal_id", str(mal_id))
    li.setProperty("anilist_id", str(media.get("id") or ""))
    li.setProperty("imdbnumber", "")
    try:
        li.setUniqueIDs({"tmdb": str(mal_id), "mal": str(mal_id)})
    except Exception:
        pass

    if not is_movie:
        browse = browse_show_path(mal_id)
        if browse:
            li.setProperty("folderpath", browse)
            li.setProperty("filenameandpath", browse)
            li.setProperty("IsPlayable", "false")

    apply_bingie_properties(li, media, detailed=detailed)

    li.setPath(PLUGIN_URL)
    return li


def build_detail_item(media):
    li = build_item(media, detailed=True)
    if not li:
        return None
    if _is_movie(media):
        play = play_movie_path(media)
        if play:
            li.setProperty("folderpath", play)
            li.setProperty("filenameandpath", play)
    return li


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
    play = play_episode_path(mal_id, episode, title=play_title or show_title)
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
    li.setProperty("tmdb_id", str(mal_id))
    li.setProperty("tmdb_type", "tv")
    if total_eps:
        li.setProperty("TotalEpisodes", str(total_eps))
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
    li.setInfo(
        "video",
        {
            "title": label,
            "tvshowtitle": show_title,
            "season": season,
            "episode": episode_count,
            "mediatype": "season",
        },
    )
    art = _episode_art_from_media(media) if media else {}
    if art:
        li.setArt(art)
        if art.get("landscape"):
            li.setProperty("landscape", art["landscape"])
    li.setProperty("DBType", "season")
    li.setProperty("DBTYPE", "season")
    li.setProperty("mal_id", str(mal_id))
    li.setProperty("folderpath", episodes_url)
    li.setProperty("filenameandpath", episodes_url)
    li.setProperty("TotalEpisodes", str(episode_count or 0))
    li.setPath(episodes_url)
    return li


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


def build_items(media_list, detailed=False):
    items = []
    for media in media_list:
        li = build_item(media, detailed=detailed)
        if li:
            items.append(li)
    return items
