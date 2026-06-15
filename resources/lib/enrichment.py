# -*- coding: utf-8 -*-
"""Indexed-property enrichment the Bingie skin reads (genre/studio/cast/crew/ratings).

These properties were formerly side-loaded by the 350ms background monitor into
the hidden Container(17195). The monitor is gone; each view's single request now
applies the right richness tier INLINE so the data is final on first paint:

  - lean rows  -> base display fields only (handled in listitems.build_item; no
                  call here).
  - spotlight  -> apply_spotlight(): the indexed props + IMDb/Trakt ratings, so
                  the hero panel's cast-thumb/rating UI shows (gap G11) without a
                  monitor.
  - More-Info  -> apply_header(): the full extended metadata the dialog header and
                  Container(17195) credit-drilldowns read.

Pure module (no Kodi deps beyond the ListItem passed in); imported by listitems.
"""

ITER_PROPS_MAX = 20


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


def apply_indexed(li, media, detailed=False):
    """Set the indexed properties Bingie reads (genre/studio/cast/crew/ratings).

    Shared by apply_header/apply_spotlight. `detailed=True` additionally emits the
    relations summary the More-Info dialog uses.
    """
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
        # The home/hub spotlight cast-thumb + rating circle (Container 17195, fed by the
        # details/apply_header item) gates on IMDb_Rating AND Trakt_Rating too, so mirror
        # the AniList average into them HERE -- not only in apply_spotlight, whose item
        # the circle never reads -- else the circle stays hidden for every 8+/9+ title
        # (R3-1 / gap G11).
        li.setProperty("IMDb_Rating", rating)
        li.setProperty("Trakt_Rating", rating)

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


def apply_header(li, media):
    """Full extended metadata for the More-Info header (request-backed, no monitor).

    Phase 4 extends this with the franchise season/episode totals.
    """
    apply_indexed(li, media, detailed=True)


def apply_spotlight(li, media):
    """Rich hero item: the indexed props -- which now include the IMDb/Trakt rating
    mirror the hero panel's cast-thumb/rating circle is gated on (set in apply_indexed
    so the details-backed Container 17195 gets them too; see R3-1 / gap G11)."""
    apply_indexed(li, media, detailed=False)
