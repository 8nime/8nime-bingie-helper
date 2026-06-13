# Bingie Skin — Complete Integration & Data Contract

> **Purpose.** This is the single authoritative map of every touchpoint between the **Bingie Kodi skin** and the **content-provider plugin** that feeds it, and the complete schema of data a provider must emit to drive a stable UX. It is written to be **agent-consumable**: every identifier (container ID, plugin path, `info=` route, `ListItem.*` InfoLabel, `ListItem.Property()` key, `ListItem.Art()` key, window property, skin setting) is quoted **verbatim**. Build against this; do not paraphrase identifiers.
>
> **Context.** The "8nime" build pairs the Bingie skin with `plugin.video.8nime.bingie.helper` (an AniList-backed provider) in place of the stock provider. Where 8nime diverges from stock, both are documented and the divergence is flagged.

## Source material (what this contract was reverse-engineered from)

| Component | Repo / path | Commit / version | Role |
|---|---|---|---|
| Bingie skin | `github.com/matke-84/skin.bingie` (branch `omega`) | `9f1c6eb` ("Quick fix") | **Authoritative demand side** — defines every widget, container, path, and the data each reads |
| TMDb engine (upstream) | `github.com/jurialmunkey/plugin.video.themoviedb.helper` | `bf098f9` / v6.15.6 | Reference provider engine the skin was designed around |
| Skin-side helper script | `github.com/cartmandos/script.bingie.helper` | `b098b62` | Library-side helper (`ratetitle`, `togglemylist`, `gettvshowid`, `playtrailer`) |
| Stock provider (the fork) | `plugin.video.tmdb.bingie.helper` v1.0.2 — binary zip in `github.com/matke-84/repository.bingie` (`omega/…/plugin.video.tmdb.bingie.helper-1.0.2.zip`); no source repo | confirmed v1.0.2 | The actual rebranded fork; uses the `TMDbBingieHelper.*` namespace |
| 8nime provider | `plugin.video.8nime.bingie.helper` (this repo) | v1.5.0 | AniList-backed drop-in replacement |
| 8nime skin patches | `8nime-wizard/config/skin-patches/anime/*.xml` | — | The actual widget wiring shipped in the 8nime build |

> ✅ **Provenance (resolved).** The stock provider is a **binary fork**, `plugin.video.tmdb.bingie.helper` v1.0.2, shipped only as a zip inside `matke-84/repository.bingie` (no public source repo; the addon.xml's GitHub URL is a dead link). It is a fork of `matke-84/plugin.video.themoviedb.helper`, itself a fork of jurialmunkey upstream. The `TMDbHelper.* → TMDbBingieHelper.*` namespace rename is achieved by swapping the bundled `script.module.jurialmunkey` for `script.module.bingie`, whose `window.py` is jurialmunkey's `window.py` with the default `prefix='TMDbHelper'` changed to `prefix='TMDbBingieHelper'`. That propagates to every `get_property()`/`WindowPropertySetter` call. **Net effect: all `TMDbBingieHelper.*` property names, the `info=` route names, and the reload/monitor mechanisms in this document are confirmed** (from the skin XML cross-checked against the fork's bundled modules), not merely inferred from upstream.

---

## Table of Contents

1. [System architecture & the four actors](#1-system-architecture--the-four-actors)
2. [The two state mechanisms: Widget Reload & Monitor Container](#2-the-two-state-mechanisms-widget-reload--monitor-container)
3. [Provider URL grammar & the `info=` route model](#3-provider-url-grammar--the-info-route-model)
4. [Home & hub windows, container-ID allocation, widget rows](#4-home--hub-windows-container-id-allocation-widget-rows)
5. [The widget item data contract (what EVERY list item must carry)](#5-the-widget-item-data-contract)
6. [The unified `info=` route catalogue](#6-the-unified-info-route-catalogue)
7. [More Info dialog (DialogVideoInfo) — the densest touchpoint surface](#7-more-info-dialog-touchpoints)
8. [Monitor container 17195 & window-property enrichment](#8-monitor-container-17195--window-property-enrichment)
9. [Window properties registry](#9-window-properties-registry)
10. [Skin settings & provider settings that affect wiring](#10-skin-settings--provider-settings)
11. [Search & autocomplete contract](#11-search--autocomplete-contract)
12. [Playback & navigation action grammar](#12-playback--navigation-action-grammar)
13. [The 8nime delta — AniList vs TMDb identity model](#13-the-8nime-delta)
14. [Gaps, ambiguities & known wiring risks](#14-gaps-ambiguities--known-wiring-risks)
15. [Appendix — critical identifier index](#15-appendix--critical-identifier-index)

---

## 1. System architecture & the four actors

Four cooperating actors produce the Bingie UX. A provider must satisfy the contract of all four.

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. BINGIE SKIN (skin.bingie)                                             │
│    - Defines hub windows, widget rows, containers, the More Info dialog. │
│    - Calls the provider via plugin:// content paths embedded in widgets. │
│    - Reads ListItem.* InfoLabels/Art/Property() from returned items.     │
│    - Reads Window(Home).Property(...) enrichment + Container(17195).      │
└──────────────┬───────────────────────────────────────────────────────────┘
               │ plugin://<provider>/?info=<route>&...   (directory listing)
               ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. CONTENT PROVIDER PLUGIN  (stock: plugin.video.tmdb.bingie.helper;     │
│    8nime: plugin.video.8nime.bingie.helper)                              │
│    - pluginsource: answers info= routes → builds ListItems → endOfDir.   │
│    - script (default.py): RunScript actions (sync_trakt, description,    │
│      clear_cache, select_artwork, refresh_details, close_dialog…).       │
│    - service (startup): the MONITOR loop (actor 3).                      │
└──────────────┬───────────────────────────────────────────────────────────┘
               │ writes Window(Home).Property(...) + Container(17195) item
               ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. MONITOR SERVICE  (background, started by skin onload)                 │
│    - Watches the focused item (container set via                         │
│      Skin.String(TMDbBingieHelper.MonitorContainer) = 17195).            │
│    - Enriches it: ratings, cast, crew, studio, network → writes them as  │
│      Window(Home).Property(...) and into the hidden Container(17195).     │
└──────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────┐
│ 4. PLAYER ADDON(S)  (8nime: Otaku / WatchNixtoons2 / Fanime F)           │
│    - The provider does NOT play. Item URLs / info=play hand off here.    │
└──────────────────────────────────────────────────────────────────────────┘
```

**Skin → provider bootstrap (set in the skin's `Home.xml`/`Startup.xml` `<onload>`):**
```xml
<onload>Skin.SetBool(TMDbBingieHelper.Service)</onload>          <!-- start monitor -->
<onload>Skin.SetBool(TMDbBingieHelper.DirectCallAuto)</onload>   <!-- auto direct-call info -->
<onload>Skin.SetString(TMDbBingieHelper.MonitorContainer,17195)</onload> <!-- container to watch -->
```

---

## 2. The two state mechanisms: Widget Reload & Monitor Container

These two mechanisms are the backbone of the integration. Get them wrong and widgets never refresh / metadata never appears.

### 2.1 Widget Reload (cache-busting refresh)

- **Every** widget content path embeds `&reload=$INFO[Window(Home).Property(TMDbBingieHelper.Widgets.Reload)]`.
- Kodi caches plugin directory results by URL. Because the `reload=` value is part of the URL, **changing the value of `Window(Home).Property(TMDbBingieHelper.Widgets.Reload)` changes every widget URL at once, forcing all widget containers to re-fetch.**
- Upstream jurialmunkey sets this via `container_refresh()` → `get_property('Widgets.Reload', set_property=<timestamp>)` (namespace `TMDbHelper.` in code; skin expects `TMDbBingieHelper.`).
- A forced variant exists: `reload=$INFO[System.Time(hh:mm:ss)]` (`PARAM_WIDGETS_RELOAD_FORCED`) — used for empty-search widgets to defeat stale cache.

> **Contract:** the provider (its service or its `container_refresh`-equivalent) **must write a changing value** to `Window(Home).Property(TMDbBingieHelper.Widgets.Reload)` whenever widgets should refresh (e.g. after a Trakt/AniList sync, login state change, or cache clear). **Confirmed unset in 8nime — see gap G4 (§14.2).**

### 2.2 Monitor Container 17195 (focused-item enrichment)

- `Container(17195)` is a **hidden, non-displayed** list. The skin tells the monitor which container to watch via `Skin.String(TMDbBingieHelper.MonitorContainer)` (= `17195`).
- The monitor service watches the **currently focused item** across the UI, fetches extended metadata, and writes it back two ways:
  1. As `Window(Home).Property(ListItem.<key>)` / `Window(Home).Property(<EnrichKey>)`.
  2. As a single ListItem pushed into `Container(17195)`, which the skin then reads as `Container(17195).ListItem.Property(<key>)` / `Container(17195).ListItem.Art(<key>)`.
- The skin reads `Container(17195)` extensively in the **More Info header** and **contextual paths** (director/writer/creator/genre/studio filmographies) — see §7, §8.

> **Contract:** widget list items only need to carry the *identity + base* fields (§5). The monitor service is responsible for the *extended* fields (cast/crew/ratings/studio/network indexed properties) landing in `Container(17195)` and on `Window(Home)`.

---

## 3. Provider URL grammar & the `info=` route model

**Base URL.** Stock: `plugin://plugin.video.tmdb.bingie.helper/`. 8nime: `plugin://plugin.video.8nime.bingie.helper/`.
(Skin XML uses both `…helper/?info=` and `…helper?info=` forms — the provider must accept the path with and without the trailing slash before `?`.)

**Canonical query grammar:**
```
plugin://<provider>/?info=<route>
   [&tmdb_type=movie|tv|person|collection|both|season|episode]
   [&tmdb_id=<int>] [&imdb_id=tt…] [&mal_id=<int>] [&anilist_id=<int>]   ← identity (provider-specific)
   [&query=<title>] [&year=<yyyy>] [&season=<n>] [&episode=<n>] [&episode_year=<yyyy>]
   [&page=<n>] [&limit=<n>] [&length=<n>] [&nextpage=true|false]
   [&widget=true] [&reload=<reload-token>] [&cacheonly=true] [&aggregate=true]
   [&with_genres=…] [&with_id=true|false] [&with_studio=…] [&with_companies=…] [&with_networks=…]
   [&sort_by=…] [&sort_how=…] [&filter_key=job&filter_value=Director|Writer|Creator]
   [&list_slug=…&list_name=…&plugin_category=…]   ← 8nime userlist params
```

**Parameter semantics:**

| Param | Meaning |
|---|---|
| `info` | **Required.** Names the route (see §6). |
| `tmdb_type` | Media kind. Drives item shape and which sub-paths the dialog builds. |
| `tmdb_id` / `imdb_id` / `mal_id` / `anilist_id` | Item identity. Stock uses `tmdb_id`/`imdb_id`; **8nime prefers `mal_id` then `anilist_id`** (see §13). |
| `widget=true` | Marks a widget (home/info row) request. Enables `reload=` injection; suppresses "Next Page". |
| `reload` | Cache-bust token = current value of `Window(Home).Property(TMDbBingieHelper.Widgets.Reload)`. |
| `cacheonly=true` | Return cached data only; never block on a network fetch (used by info-dialog rows so the dialog opens instantly). |
| `aggregate=true` | Aggregate multi-source results (cast/crew across episodes). |
| `nextpage=false` | Suppress the "Next Page" folder item (info-dialog rows, previews). |
| `length` / `limit` | Cap result count. |
| `filter_key=job&filter_value=…` | Person credit filter (Director/Writer/Creator). |
| `list_slug`,`list_name`,`plugin_category` | **8nime-specific** named-list params for `trakt_userlist` (see §6). |

---

## 4. Home & hub windows, container-ID allocation, widget rows

### 4.1 Hub windows

| Window ID | File (stock → 8nime patch) | Hub | `defaultcontrol` |
|---|---|---|---|
| `Home` / `10000` | `Home.xml` / `IncludesHomeBingie.xml` | Home (primary) | — |
| `1109` | `Custom_1109_BingieSearch.xml` | Search | `77777` |
| `1110` | `Custom_1110_TVShows_Hub.xml` | TV Shows | `77777` |
| `1111` | `Custom_1111_Movies_Hub.xml` | Movies | `77777` |
| `1112` | `Custom_1112_New_Hub.xml` | New / What's New | `77777` |
| `1113` | `Custom_1113_MyCustom_Hub.xml` | Custom | `77777` |
| `1114` | `Custom_1114_MyList_Hub.xml` | My List | `77777` |
| `1116` | `Custom_1116_PVR_Hub.xml` | PVR/Live | varies |
| `1117` | `Custom_1117_Categories_Hub.xml` | Category results (driven by `categorypath`) | — |
| `1118` | `Custom_1118_Something_Hub.xml` | Play Something (random) | — |
| `1119` | `Custom_1119_Category2_Hub.xml` | Genre picker (8nime: 15 anime genres) | — |
| `1120` | `Custom_1120_Music_Hub.xml` | Music | `77777` |
| `1101`/`1102` | `Custom_1101_StartUp.xml` / `Custom_1102_StartUp2.xml` | First-run startup (8nime) | `100` |
| `1190` | `IncludesDialogVideoInfo.xml` (`movieinformation`) | **More Info dialog** | `8000` |
| `1121` / `1122` | Custom plot / OSD text popups | text viewers | — |
| screensaver | `screensaver-bingie.xml` | Slideshow (container `1297`) | — |

All hubs share: `<include>HomeBingie</include>`, `<include>CustomBingieWinProps</include>`, `<include>Defs_TMDbBingieHelper_Loader</include>`. The vertical stack of widget rows is **grouplist container `77777`** (`pagecontrol=317`). Side menu is container `900`; focus restore: `SetFocus(900,$INFO[Window(Home).Property(menupos)])`.

### 4.2 Container-ID allocation

Widget container IDs are computed per hub (skinshortcuts template formula):

| Hub | Container ID formula | Example (widget N=1) |
|---|---|---|
| Main/Home (`10000`) | `{mainmenuid}{N+3002}` | `13003` (mainmenuid=1) |
| Movie Hub (`1111`) | `N + 6040` | `6041` |
| TV Show Hub (`1110`) | `N + 6050` | `6051` |
| New Hub (`1112`) | `N + 6050` | `6051` |
| Music Hub (`1120`) | `N + 6060` | `6061` |
| Search results | `N + 5040` | `5041`–`5060` |
| Search groupids | `N + 7540` | `7541` |

**Fixed / special containers:**

| ID | Purpose |
|---|---|
| `77777` | Vertical grouplist of all widget rows on a hub |
| `1508` | Spotlight (hero) widget |
| `15081` | Spotlight TV-show latest-episode prefetch (`dateadded desc`, limit 1) |
| `1510`–`1540` | PVR hub rows / Play-Something widget |
| `117` | Categories-hub results (content = `Window(Home).Property(categorypath)`) |
| `1297` | Screensaver slideshow |
| `17195` | **Monitor container** (hidden; see §8) |
| `500` / `1007` | Search preview panel / autocomplete suggestions |
| `50`,`352`,`353`,`354`,`1050`,`1234`,`5050`,`8999`,`2999`,`53001`–`53009`,`4000`–`4003` | More Info dialog (see §7) |
| `200`–`215` | Widget containers polled for clearlogo fallback |

### 4.3 Widget rows are defined by SkinShortcuts DATA files

Rows are data-driven via `script.skinshortcuts` DATA files (`shortcuts/*.DATA.xml`) instantiated through `template.xml`. Each shortcut item exposes these template properties:

| Property | Meaning |
|---|---|
| `widgetPath` | the `plugin://` content URL |
| `widgetName` | row header label |
| `widgetTarget` | `videos`/`music`/`pictures`/`programs`/`tvguide` |
| `widgetStyle` | layout: `default`/`poster`/`landscape`/`square` |
| `widgetSortBy` / `widgetSortOrder` | sort key + `ascending`/`descending` |
| `widgetLimit` | item count (or `$INFO[Skin.String(WidgetsGlobalLimit)]`) |
| `widgetTags` | `WidgetTagOverlayEnable`/`Disable` |
| `widgetid` / `mainmenuid` / `submenuid` | indices used in the container-ID formula & visibility |

### 4.4 8nime home/hub default widget paths

8nime defines its widget content in `IncludesPaths.xml` as `Def*Content` variables (each with a `*Widget` wrapper that checks `Skin.String(<VarName>.path)` for a user override first). All embed `&reload=$INFO[Window(Home).Property(TMDbBingieHelper.Widgets.Reload)]`.

| Variable | Row label | Route + key params |
|---|---|---|
| `DefWidgetContent` | Continue Watching | `info=anilist_nextup&widget=true&tmdb_type=tv` |
| `DefWidget1Content` | Trending Now | `info=trakt_trending&widget=true&tmdb_type=tv` |
| `DefWidget2Content` | Airing This Season | `info=trakt_userlist&list_slug=latest-tv-shows&list_name=Airing+This+Season` |
| `DefWidget3Content` | Popular | `info=trakt_userlist&list_slug=all-time-popular-tv` |
| `DefWidget4Content` | Top Rated | `info=trakt_userlist&list_slug=imdb-top-rated-tv-shows` |
| `DefWidget5Content` | Last Season | `info=trakt_userlist&list_slug=last-season-tv` |
| `DefMovieHubContent` | New Movies | `info=trakt_userlist&list_slug=new-movies` |
| `DefMovieHub1Content` | Popular | `info=trakt_userlist&list_slug=all-time-popular-movies` |
| `DefMovieHub2Content` | Top Rated | `info=trakt_userlist&list_slug=imdb-top-rated-movies` |
| `DefNewHub1Content` | Upcoming Anime | `info=anilist_upcoming&widget=true&tmdb_type=tv` |
| `DefNewHub2Content` | Airing Anime Movies | `info=trakt_userlist&list_slug=latest-releases` |
| `DefNewHub3Content` | Upcoming Anime Movies | `info=anilist_upcoming&widget=true&tmdb_type=movie` |
| `DefSomethingHubContent` | Random Anime | `info=random_popular&widget=true&tmdb_type=both` |
| `DefSpotlight*Content` | Spotlight (per hub) | `info=random_popular`/`random_trending&widget=true&tmdb_type=…` |
| `Path_MyList` | My List | `info=trakt_favorites&widget=true&tmdb_type=both&sort_by=added&sort_how=desc` |

**Named `trakt_userlist` slugs in use** (8nime): `latest-tv-shows`, `all-time-popular-tv`, `imdb-top-rated-tv-shows`, `last-season-tv`, `new-movies`, `all-time-popular-movies`, `imdb-top-rated-movies`, `latest-releases`.

### 4.5 Genre picker (window 1119 → 1117) and the anime genre remap

8nime's genre picker (window `1119`, 15 static items) on click sets `Window(Home).Property(category)`, `…(categorylabel)`, `…(categorypath)` then `ActivateWindow(1117,return)`. Window `1117` container `117` loads `Window(Home).Property(categorypath)` directly.

> **8nime divergence:** the genre widget *variable names* are inherited generic Bingie names (`CrimeTVShows`, `WarPoliticsTVShows`, `AnimeMovies`…) but their `with_genres` values are remapped to **anime genres**. e.g. `CrimeTVShows→Psychological`, `WarPoliticsTVShows→Mecha`, `FamilyTVShows→Slice of Life`, `AnimeMovies→Supernatural`, `WesternTVShows→Sports`, `AnimationTVShows→Adventure`, `DocumentaryMovies→Music`. All genre paths share:
> `info=discover&sort_by=popularity.desc&tmdb_type=<type>&with_genres=<genre>&with_id=False&widget=true&reload=…`

The 15 picker genres: Action, Adventure, Comedy, Drama, Fantasy, Romance, Sci-Fi, Horror, Mystery, Thriller, Slice of Life, Mecha, Psychological, Supernatural, Sports.

---

## 5. The widget item data contract

Every list item a provider returns is read by the skin via the keys below. **Bold = high-impact** (item appears broken/blank without it).

### 5.1 InfoLabels (`ListItem.<key>` via `setInfo`)

| Key | Used for |
|---|---|
| **`Title`** / `Label` | primary / fallback title |
| **`Plot`** | synopsis |
| `Tagline` | spotlight sublabel |
| **`Genre`** | genre row |
| **`Year`** / `Premiered` | year / date |
| `Rating` / `UserRating` | rating value |
| `MPAA` | content/age rating |
| `Duration` (+ `(h)`,`(m)`,`(mins)`,`(ss)`) | runtime |
| `Studio` / `Director` / `Writer` / `Cast` | credits strings |
| **`DBTYPE`** | `movie`/`tvshow`/`season`/`episode`/`set`/`artist`/`album`/`song` — drives routing & layout |
| `DBID` | Kodi library id (library items only) |
| **`FileNameAndPath`** / `FolderPath` / `Path` | play/browse target; `Path` is matched against `plugin://<provider>/` to detect plugin items |
| `IsFolder` / `IsResumable` / `PercentPlayed` / `IsWatched` | nav + progress |
| `IMDBNumber` (`tt…`) | IMDb id fallback |
| **`UniqueID(tmdb)`** / `UniqueID(imdb)` / `UniqueID(tvdb)` / `UniqueID(tvshow.tmdb)` | unique ids |
| `Set` | collection/set name |
| `TVShowTitle` / `Season` / `Episode` / `TotalEpisodes` / `TotalSeasons` / `UnWatchedEpisodes` | episodic metadata + progress bars |
| `Trailer` | trailer URL |
| `Icon` / `Thumb` | image fallbacks |

### 5.2 Art keys (`ListItem.Art(<key>)` via `setArt`) — with the skin's fallback chains

| Style / View | Fallback chain (first non-empty wins) |
|---|---|
| Poster (View `526` `PosterPanelBingie`) | `season.poster` → `tvshow.poster` → **`poster`** → `thumb` → `Icon` |
| Landscape (View `523` `ThumbsViewBingie`) | `thumb` (episodes) → `season.landscape` → **`landscape`** → `tvshow.landscape` → `tvshow.fanart` → `fanart` |
| Square (View `528` `SquarePosterPanelBingie`) | `fanart` → `thumb` |
| Clearlogo | **`clearlogo`** → `tvshow.clearlogo` (→ `artist.clearlogo`/`albumartist.clearlogo` for music) |
| Background/fanart | **`fanart`** → `tvshow.fanart` → `season.fanart` |
| Spotlight background | `landscape` → `tvshow.landscape` → `fanart` → `tvshow.fanart` → `thumb` |
| Also read | `banner`, `tvshow.banner`, `season.poster`, `clearart` |

> **Provide at minimum:** `poster`, `fanart`, `landscape`, `clearlogo`, `thumb`. For season/episode items also provide the `tvshow.*`/`season.*` prefixed variants. Episodes should set `thumb` (the episode still).

### 5.3 Identity & routing properties (`ListItem.Property(<key>)`)

| Key | Value | Why it matters |
|---|---|---|
| **`tmdb_id`** | TMDb numeric id | Trakt sync, recommendations, discover-by-id, filmography. **(8nime: see §13/§14.)** |
| `imdb_id` | `tt…` | query/lookup fallback |
| `tvdb_id` | TVDb id | secondary |
| **`tmdb_type`** | `movie`/`tv`/`person` | item shape; `person` switches to the cast overlay layout |
| **`DBTYPE`** | `movie`/`tvshow`/`season`/`episode`/`set`/`genre`/`category` | fallback when `ListItem.DBTYPE` is empty (plugin items) |
| `set.tmdb_id` | collection id | builds the `info=collection` path |
| `mediatype` | media type | general routing |
| **`mal_id`** | MyAnimeList id | **8nime primary identity** (see §13) |
| **`anilist_id`** | AniList id | 8nime fallback identity |
| `folderpath` | browse target | "More Episodes" browse for plugin shows |
| `landscape` / `banner` / `TVShowThumb` | art-as-property fallbacks | used in some widget layouts |
| `similartitle` / `genretitle` | row-header overrides ("Because you watched X") |
| `character` / `job` | cast/crew item detail |
| `Album_Description` / `Artist_Description` / `Artist_*` | music metadata |

### 5.4 UniqueIDs (`setUniqueId`)

`tmdb`, `imdb`, `tvdb`, `trakt`, `tvshow.tmdb`, `tvshow.tvdb`, `tvshow.imdb`. The skin reads `ListItem.UniqueID(tmdb)` etc.; **`tmdb` must be present** for stock-contract features.

### 5.5 Folder vs playable & item URLs (stock model)

| mediatype | `isFolder` | item URL |
|---|---|---|
| movie | `False` | `?info=play&tmdb_type=movie&tmdb_id={id}` |
| tvshow | `True` | `?info=seasons` (or `flatseasons` if `flatten_seasons=true`)`&tmdb_type=tv&tmdb_id={id}` |
| season | `True` | `?info=episodes&tmdb_type=tv&tmdb_id={id}&season={n}` |
| episode | `False` | `?info=play&tmdb_type=tv&tmdb_id={id}&season={s}&episode={e}` |
| person | `True` | `?info=credits_in_both&tmdb_type=person&tmdb_id={id}` |
| set | `True/False` | `?info=collection&tmdb_type=collection&tmdb_id={id}` |
| Next-Page item | `True` | parent params + `page=N+1`, `Property(specialsort)=bottom` |

---

## 6. The unified `info=` route catalogue

This table maps the routes the **skin calls** to their stock and 8nime handlers. `cacheonly`/`nextpage=false`/`aggregate` are common info-dialog flags.

| Skin context | Route (`info=`) | Stock engine class | 8nime handler | Returns | Notes |
|---|---|---|---|---|---|
| Trending row | `trakt_trending` | `ListTraktTrending` | `RouteHandler.trakt_trending` | items | global trending in 8nime |
| Popular row | `trakt_popular` | `ListTraktPopular` | `RouteHandler.trakt_popular` | items | season-scoped popular in 8nime |
| Named list rows | `trakt_userlist` | `ListTraktCustom` (uses `username`+`slug`) | `RouteHandler.trakt_userlist` (uses **`list_slug`**) | items | **param divergence** — see §14 |
| My List | `trakt_favorites` | `ListFavorites` | `RouteHandler.trakt_favorites` | items | `sort_by=added&sort_how=desc` |
| Continue Watching | `anilist_nextup` *(8nime)* | (stock: `trakt_ondeck`/`trakt_nextepisodes`) | `RouteHandler.anilist_nextup` | items | 8nime-named route |
| Upcoming | `anilist_upcoming` *(8nime)* | (stock: `upcoming`/`trakt_anticipated`) | `RouteHandler.anilist_upcoming` | items | 8nime-named route |
| Random spotlight | `random_popular` / `random_trending` | `ListTrakt*Randomised` | `RouteHandler.random_popular`/`random_trending` | 1 item | spotlight hero |
| Genre rows / contextual | `discover` | `ListDiscover` | `RouteHandler.discover` (+ `discover_extended`) | items | filters: `with_genres`,`with_id`,`sort_by` (8nime); stock also `with_companies`,`with_networks`,`primary_release_year` |
| Library browse | `dir_tv` / `dir_movie` / `dir_ova` *(8nime)* | `ListBaseDir` | `RouteHandler.dir_all`/`dir_ova` | folder/items | 8nime browses anime catalogue |
| Search | `search` | `ListSearch` | `RouteHandler.search` | items | keyboard if no `query` |
| Autocomplete | `autocomplete` *(8nime)* | (stock: `plugin.program.autocompletion`) | `RouteHandler.autocomplete` | items | **possibly orphaned** — see §14 |
| Cast (dialog + OSD) | `cast` | `ListCast` | `InfoHandler.cast` | person items | `cacheonly=true&aggregate=true` |
| Crew | `crew` | `ListCrew` | `InfoHandler.crew` | person items | |
| Recommendations | `recommendations` | `ListRecommendations` | `InfoHandler.recommendations` | items | `length=1&nextpage=false` |
| Relations / collection | `relations` *(8nime)* / `collection` | `ListSeries`/`ListTraktRelated` | `InfoHandler.relations` / `.collection` | items | 8nime maps Path_Collection→`relations` |
| Trailers | `videos` | `ListVideos` | `InfoHandler.videos` | video items | |
| Reviews | `trakt_comments` → 8nime `reviews` | `ListTraktComments` | `InfoHandler.reviews` | items | 8nime aliases `trakt_comments`→`reviews` |
| Next-up (dialog) | `trakt_upnext` | `ListUpNext` | `InfoHandler.trakt_upnext` | episode item | feeds Container(1234) |
| Posters | `posters` | `ListPoster` | `InfoHandler.posters` | image items | |
| Seasons / flat | `seasons` / `flatseasons` | `ListSeasons`/`ListFlatSeasons` | `InfoHandler.seasons`/`.flatseasons` | season/episode items | gated by `flatten_seasons` |
| Episodes | `episodes` | `ListEpisodes` | `InfoHandler.episodes` | episode items | |
| Details | `details` | `ListDetails` | `InfoHandler.details` | items | tvshow → seasons/flatseasons |
| Person filmography | `stars_in_movies`/`stars_in_tvshows`/`crew_in_movies`/`crew_in_tvshows`/`crew_in_both` | `ListStarred*`/`ListCrewed*` | `InfoHandler.*` | items | dialog credits & person panels; `filter_key=job&filter_value=Director|Writer|Creator` |

**RunScript actions (script entry, not directory):**
`sync_trakt` (like/dislike/reset/favorites/cache_refresh), `description` (Wikipedia/plot popup), `clear_cache` / `clear_expired_cache`, `select_artwork`, `refresh_details`, `close_dialog`, `add_path`, `call_path`.

---

## 7. More Info dialog touchpoints

Window `1190` (`movieinformation`), variants `BingieAltInfo` (floating) and `BingieInfoDialog` (full-screen), plus the `TMDB_Helper_Cast` person overlay. `defaultcontrol=8000` (action bar). The dialog detects plugin items via `String.IsEqual(ListItem.Path, plugin://<provider>/)`.

### 7.1 Data-bearing containers

| Container | Section | Path (route) | Visible when |
|---|---|---|---|
| `50` | Cast / voice-actor strip (always-on bottom) | `info=cast&nextpage=true&aggregate=true&{type}&{query}&{episode}` | always |
| `352` | Recommendations / similar | `info=recommendations&nextpage=false&length=1&{type}&{query}&reload=…` | `AdditionalInfo==similar` |
| `353` | Collection / relations | `info=relations&{type}&{query}&nextpage=false&cacheonly=true&reload=…` | `ListItem.Set` or `Container(17195).ListItem.Set` non-empty |
| `354` | Trailers & videos | `info=videos&nextpage=false&cacheonly=true&{type}&{query}` (limit 20) | `AdditionalInfo==trailers` |
| `1050` | Reviews / Trakt comments | `info=trakt_comments&{type}&{query}&cacheonly=true&limit=20` | `AdditionalInfo==plot` |
| `1234` | Hidden next-ep (plugin/no-library) | `info=trakt_upnext&mal_id={mal_id}` *(or `tmdb_id=…`)*`&tmdb_type=tv&cacheonly=true` | plugin tvshow, no DBID |
| `5050` | Hidden next-ep (library) | `videodb://inprogresstvshows/{DBID}/-2/` | library tvshow |
| `53001` | Cast grid | `info=cast&nextpage=false&cacheonly=true&aggregate=true&…` | 8999 label = Cast |
| `53002` | Crew grid | `info=crew&…` | 8999 label = Crew |
| `53003` | More from genre | `info=discover&with_genres={Genre.1.Name}&with_id=False&…` | 8999 label = Genre |
| `53004` | Posters | `info=posters&{type}&{query}&nextpage=false&limit=20&cacheonly=true` | 8999 label = Posters |
| `53005` | More from director | `info=crew_in_both&tmdb_type=person&filter_key=job&filter_value=Director&tmdb_id={Director.1.TMDb_ID}&query={Director.1.name}&…` | 8999 label = Director (movie/episode) |
| `53006` | More from year | `info=discover&year={Year}&sort_by=popularity.desc&…` | 8999 label = Year |
| `53007` | More from writer | `info=crew_in_both&…filter_value=Writer&tmdb_id={Writer.1.TMDb_ID}&…` | 8999 label = Writer (movie) |
| `53008` | More from studio/network | `info=discover&with_studio={Studio.1.Name}&…` *(stock: `with_companies={Studio.1.TMDB_ID}`)* | 8999 label = Studio/Network |
| `53009` | More from creator | `info=crew_in_both&…filter_value=Creator&tmdb_id={Creator.1.TMDb_ID}&…` | 8999 label = Creator (tvshow/episode) |
| `4000`–`4003` | Person: stars/crew in movies/shows | `info=stars_in_movies`/`stars_in_tvshows`/`crew_in_movies`/`crew_in_tvshows&limit={cast_number}&…` | person overlay, container 2999 |

**Path-parameter VARs** (how `{type}`/`{query}`/`{episode}` resolve):
- `Path_Param_Type` → `&tmdb_type=movie|tv|person` from `ListItem.DBTYPE`.
- `Path_Param_Query` (priority): `&mal_id=` → `&anilist_id=` → `&imdb_id=` (movie) → `&query={TVShowTitle}&episode_year=` (episodic) → `&tmdb_id=` (person) → `&query={Title}&year=` → `&query={Label}`.
- `Path_Param_EpisodeSpecific` → `&season=N` or `&season=N&episode=N`.
- `reload` → `$INFO[Window(Home).Property(TMDbBingieHelper.Widgets.Reload)]`.

### 7.2 Sub-navigation menus

**Container `8999`** (Credits sub-nav, static list) selects which `53xxx` shows, matched by `Container(8999).ListItem.Label`:
Cast `$LOCALIZE[206]`→53001 · Crew `[31089]`→53002 · Director `[20339]`→53005 · Writer `[31488]`→53007 · Creator `[31530]`→53009 · Studio/Network `[572]`/`[705]`→53008 · Genre `[135]`→53003 · Year `[345]`→53006 · Posters `[31529]`→53004.

**Container `2999`** (person overlay sub-nav): Info `[14116]` · Cast in Movies `[31519]`→4000 · Cast in Shows `[31508]`→4001 · Crew in Movies `[31509]`→4002 · Crew in Shows `[31510]`→4003.

### 7.3 Action buttons

| ID | Button | Built-in fired |
|---|---|---|
| `80` | Play | `Dialog.Close(movieinformation)` + `AlarmClock(PlayMovie,PlayMedia($ESCINFO[ListItem.FileNameAndPath]),00:01,silent)` (fallback `FolderPath`) |
| `90` / `52` | Resume / Play from beginning | `PlayMedia(…,resume)` / `PlayMedia(…,noresume)` |
| `51` / `8181` | Play next ep (library / helper) | `PlayMedia($ESCINFO[Container(5050|1234).ListItem.FileNameAndPath],resume)` |
| `53` | More episodes / browse | `SetProperty(BaseWindow,1,Home)` + `ActivateWindow(Videos,videodb://tvshows/titles/{DBID}/-2/,return)` or `ActivateWindow(Videos,$ESCINFO[ListItem.Property(folderpath)],return)` |
| `54` / `541` | Trailer / open trailer panel | `PlayMedia($ESCINFO[ListItem.Trailer],1)` or IMDb-trailers plugin or `RunScript(script.bingie.helper,action=playtrailer,…)`; `541` sets `AdditionalInfo=trailers` |
| `60`/`62`/`63`/`622` | open Plot / Similar / Credits / Collection panel | `SetProperty(AdditionalInfo,plot|similar|cast|set)` |
| `7001`–`7004` | Library rating (thumbs) | `RunScript(script.bingie.helper,action=ratetitle,rateaction=like|dislike|reset)` |
| **`7011`/`7033`/`7055`** | Trakt/AniList like / dislike / reset | `RunScript(<provider>,sync_trakt,tmdb_id={tmdb_id},{type},sync_type=like|dislike|reset)` — gated by `Window(Home).Property(AniListBingieHelper.HasToken)` |
| `561` | Add to Favourites | `RunScript(<provider>,sync_trakt,tmdb_id={tmdb_id},{type},sync_type=favorites)` (falls back to `Container(17195).ListItem.Property(tmdb_id)`) |
| `562` | Cache refresh | `RunScript(<provider>,sync_trakt,…,cache_refresh)` (hidden by default) |
| `56`/`57` | Add/Remove My List | `RunScript(script.bingie.helper,action=togglemylist)` |
| `10` | Artwork selector | `RunScript(<provider>,select_artwork,tmdb_id={tmdb},tmdb_type=…)` |
| `1040` | Wikipedia/description | `RunScript(<provider>,description={Title},tmdb_type=…)` |
| `6`/`612` | Refresh details | `RunScript(<provider>,refresh_details,tmdb_id={tmdb},tmdb_type=…)` |

> **8nime note:** the `sync_trakt`/`select_artwork`/`refresh_details` buttons pass **`tmdb_id={tmdb_id}`**, but 8nime's `default.py:sync_trakt_rating` expects **`mal_id`** (falling back to `anilist_id`). This identity mismatch is a key wiring risk — see §14.

### 7.4 Header / detail InfoLabel resolution (read by the synopsis panel)

The header resolves each field through a fallback chain across `ListItem.*`, `Window.Property(*)`, `Window(Home).Property(*)`, and `Container(17195).ListItem.*`. Key VARs:

| VAR | Resolution chain (abridged) |
|---|---|
| `BingieInfoLabel` | `ListItem.Title` → `Container(17195).ListItem.Label` → `Window(Home).Property(AniListBingieHelper.Title)` → `ListItem.Label` |
| `BingieInfoGenre` | `ListItem.Genre` → `Window.Property(Genre)` → `Container(17195).ListItem.Property(Genre.1.Name)`+`.2`+`.3` |
| `BingieInfoStudio` | `ListItem.Studio` → `Window.Property(Network|Studio)` → `Container(17195).ListItem.Property(Network.1.Name)` → `…Property(studio)` |
| `BingieInfoDirector` | `ListItem.Director` → `Container(17195).ListItem.Director` |
| `BingieInfoWriter` | `ListItem.Writer` (movie) → `Container(17195).ListItem.Writer` |
| `BingieInfoCreator` | `Window.Property(Creator)` → `Container(17195).ListItem.Property(Creator.1.name)`+`.2`+`.3` → `ListItem.Writer` |
| `BingieInfoCast` | `ListItem.Property(cast)` → `Container(17195).ListItem.Property(Cast.1.name)…Cast.5.name` |
| `BingieInfoClearlogo` | `Container.ListItem.Art(tvshow.clearlogo)` → `Art(clearlogo)` |

Also read directly: `ListItem.Tagline`, `ListItem.Season`/`Episode`, `ListItem.UniqueID(tmdb)`, `ListItem.Property(mal_id|anilist_id|imdb_id|tmdb_id|tmdb_type|folderpath)`, `ListItem.IMDBNumber`, `Window.Property(AdditionalInfo|subtitle)`.

---

## 8. Monitor container 17195 & window-property enrichment

The monitor service (8nime: `service.py`, `AniListBingieService`, 350 ms poll) does the heavy lifting that widget items don't carry.

**8nime poll loop:** detect focused item → resolve identity (`ListItem.Property(mal_id)` → `UniqueID(mal)` → regex `mal_id=\d+` in path) → `AniListClient.get_media(mal_id)` → build enriched ListItem (+ franchise season/episode totals) → write properties to Home (and dialog) windows + push the item into `Container(17195)`. Also runs `_sync_auth_property()` setting `Window(Home).Property(AniListBingieHelper.HasToken)` = `"1"`/cleared.

**Keys the skin reads from `Container(17195).ListItem.Property(…)`** (case-sensitive — must match exactly):

| Key (verbatim) | Used for |
|---|---|
| `tmdb_id` | **universal fallback id for every `sync_trakt` call** |
| `Genre.1.Name` / `.2.Name` / `.3.Name` | genre row + `discover` path |
| `Cast.1.name` … `Cast.5.name` | inline cast row |
| `Director.1.name`…`.5.name` + `Director.N.TMDb_ID` | director row + filmography path |
| `Creator.1.name`…`.3.name` + `Creator.N.TMDb_ID` | creator row + filmography path |
| `Writer.1.name`…`.5.name` + `Writer.N.TMDb_ID` + `Writer.N.job` | writer row + Screenplay check |
| `Studio.1.Name` / `Network.1.Name` / `studio` | studio/network row + `discover` path |
| `Top250` | ranking badge |
| `Set` (`Container(17195).ListItem.Set`) | collection name / button label |
| also: `Container(17195).ListItem.Art(landscape|fanart|clearlogo|clearart)` | art fallbacks |

**Enrichment window properties (8nime sets on Home):** `AniListBingieHelper.HasToken`, `AniListBingieHelper.EnrichedMalId`, `AniListBingieHelper.Title`, `AList_Rating`, `TMDb_Rating`, `Status`, `cast`, `studio`/`Studio`, `Network`/`Network.1.Name`, `Genre`, `Creator`/`Creator.1.name`, `Writer`.

> **Casing & namespace are contract.** Note the skin sometimes reads `Genre.1.Name` (capital N) and `Cast.1.name` (lower n) inconsistently — a provider must emit exactly what each touchpoint reads. §14 tracks confirmed mismatches.

---

## 9. Window properties registry

All on `Window(Home)` unless noted `Window.Property` (dialog-scope).

**Service / helper control:** `TMDbBingieHelper.Service` (Skin.Bool, start monitor), `TMDbBingieHelper.DirectCallAuto`, `TMDbBingieHelper.DisableRatings`, `TMDbBingieHelper.MonitorContainer` (Skin.String `17195`).

**Reload / refresh:** **`TMDbBingieHelper.Widgets.Reload`** (the cache-bust token, §2.1), `widgetreload` (MyList variant), `flushWidgetProps` (triggers `Custom_1157` to clear the cached `ListItem.*` Home properties).

**Player (set during playback):** `TMDbBingieHelper.Player.clearlogo`, `…Player.clearart`, `…Player.mpaa`/`MPAA`, `…Player.TMDb_ID`, `…Player.TVShow.TMDb_ID` (read by `Path_OSD_Cast`/`Path_OSD_Crew`).

**Dialog-scope (`Window.Property`):** `AdditionalInfo` (`cast|similar|trailers|plot|set` — the active sub-panel), `subtitle`, `ShowPlayBeginning`, `DisablePosterFade`, `PlaySearchTrailer`, `TrailerPlayIcon`/`TrailerClipIcon`, `HideNowPlaying`.

**Dialog→Home signals:** `CloseInfoDialog`, `BaseWindow`, `NoFadeOut`, `BusyInfoDialogTrailer`, `ListItem.TVShowID`, `KeepTVShowID`, `IsInMyList`.

**8nime:** `AniListBingieHelper.HasToken` (auth gate for buttons 7011/7033/7055/group 701), `AniListBingieHelper.Title`, `AniListBingieHelper.EnrichedMalId`, `TMDbBingieHelper.WidgetContainer` (focused widget id, read by the service).

**Categories:** `category` (genre slug), `categorylabel`, `categorypath` (8nime: full plugin path for container 117).

**Startup (8nime):** `StartupMask`, `finishBingieStartup1`, `finishBingieStartup2`, `menupos`.

**Rating popups:** `ratelike`, `ratedislike`, `RateTitle`, `RateTitle.Action`. **Text popups (1121/1122):** `header`/`textbox`, `osdheader`/`osdtextbox`/`osdgenre`/`osdyear`/`osdrating`.

---

## 10. Skin settings & provider settings

### 10.1 Skin settings that affect data wiring (8nime defaults shown where known)

| Setting | Type | 8nime default | Effect |
|---|---|---|---|
| `UseBingieInfoDialog` | bool | `true` | use Bingie info dialog (window 1190) vs Kodi default |
| `UseBingieOSD` | bool | `true` | custom OSD |
| `WidgetsGlobalLimit` | string | `25` | items per widget row |
| `SearchLimit` | string | `20` | search results shown |
| `widgetstyle` | string | `poster` | global layout (`poster`/`landscape`/`square`) |
| `spotlighthome.path` / `spotlightnew.path` / `spotlighttvshows.path` / `spotlightmovies.path` | string | `…helper/?info=trakt_trending&tmdb_type=tv|movie` | spotlight hero source (8nime → helper) |
| `cast_number` | string | — | cast list limit (`stars_in_*` paths) |
| `EnableRatings` / `ratings_Trakt` | bool | `false` | 8nime disables TMDb/Trakt ratings (uses AniList) |
| `ratings_IMDB`/`_TMdb`/`_RT`/`_Metacritic`/… | bool | `true` | rating badges shown |
| `videoinfo_button_*` | bool | `true` | which info-dialog buttons show |
| `details_row_*` | bool | `true` | which detail rows show |
| `DisableSpotlightContent` / `DisableDummySpotlight` | bool | — | spotlight gating |
| `DisableSearchSuggestions` / `EnableBingieSearchFullKeyboard` | bool | — | search behavior |
| `flatten_seasons` *(provider setting, mirrored)* | bool | — | tvshow → `seasons` vs `flatseasons` |
| `BingieFirstStartupDone` / `BingieSecondStartupDone` | bool | `true` (8nime) | suppress first-run windows |

### 10.2 8nime provider settings (`resources/settings.xml`)

| ID | Type | Default | Effect |
|---|---|---|---|
| `anilist_login` | action | — | runs Otaku AniList login (`plugin://plugin.video.otaku/watchlist_login/anilist?auth_dialog=true`); token is shared via Otaku |
| `title_language` | string | `english` | `romaji`/`english` title shown in items |
| `playback_plugin` | string | `watchnixtoons2` | default player: `otaku`/`watchnixtoons2`/`fanime_f` |
| `clear_cache` / `clear_expired_cache` | action | — | manual AniList cache invalidation (1 h TTL) |

### 10.3 Stock provider settings worth mirroring

`flatten_seasons`, `widgets_nextpage`, `pagemulti_tmdb`/`pagemulti_trakt` (list length), `language`, `fanarttv_lookup`, `trakt_token`, `mdblist_apikey`, `omdb_apikey`, `default_player_movies`/`default_player_episodes`, `monitor_userlist`/`monitor_userslug` (home-spotlight seed).

### 10.4 Otaku bridge settings (8nime, `otaku.settings.snippet.xml`)

`browser.api=anilist`, `anilist.enabled=true`, `watchlist.update.enabled=true`, `nextup.enabled=true`. The 8nime helper reuses Otaku's stored AniList token.

---

## 11. Search & autocomplete contract

Window `1109`. Flow:
1. Virtual keyboard (grouplist `9000`) builds `Skin.String(CustomSearchTerm)` letter-by-letter; result containers `5041`–`5060` refresh as it changes. (Native keyboard if `EnableBingieSearchFullKeyboard`.)
2. **Autocomplete (container `1007`)** — *stock* loads `plugin://plugin.program.autocompletion?info=autocomplete&id=$INFO[Skin.String(CustomSearchTerm)]`. Suggestion items carry `ListItem.Property(path)`; on focus the skin sets `Window.Property(SuggestionPath)` to it.
3. **Preview (container `500`)** — `<content browse="never" limit="100" target="videos">$INFO[Window.Property(SuggestionPath)]</content>`.
4. Selecting a suggestion sets `Skin.String(CustomSearchTerm)` = `ListItem.Label`.

> **8nime:** the helper exposes an `autocomplete` route that returns items whose `Property(path)` previews an `info=search` URL — **but** whether the 8nime skin patch repoints container `1007`/`500` at the helper (vs leaving stock `plugin.program.autocompletion`) is unconfirmed (§14).

---

## 12. Playback & navigation action grammar

| Intent | Built-in |
|---|---|
| Play plugin item | `PlayMedia($ESCINFO[ListItem.FileNameAndPath])` (or `FolderPath`); resume-aware `,resume` / `,noresume` |
| Play library item | `PlayMedia(videodb://movies/{DBID})` / `…/tvshows/{DBID}` |
| Play next ep (offset) | `PlayMedia($ESCINFO[Container(5050).ListItem.Path],isdir,playoffset={N-1})` |
| Deferred play (let dialog close) | `AlarmClock(PlayMovie,PlayMedia(…),00:01,silent)` (`00:04` from the Cast window) |
| Open info | `Action(Info)` |
| Browse seasons (library) | `ActivateWindow(Videos,videodb://tvshows/titles/{DBID}/-2/,return)` |
| Browse folder (plugin) | `ActivateWindow(Videos,$ESCINFO[ListItem.FileNameAndPath],return)` |
| Close cast window + nav | `RunScript(<provider>,close_dialog=1190,call_path={…})` |
| Trakt/AniList sync | `RunScript(<provider>,sync_trakt,tmdb_id={tmdb_id},{type},sync_type=watchlist|favorites|like|dislike|reset)` / `,cache_refresh` |
| IMDb trailer | `PlayMedia(plugin://plugin.video.imdb.trailers/?action=play_id&imdb={imdb_id},1)` |
| Library tvshow lookup | `RunScript(script.bingie.helper,action=gettvshowid,dbid={DBID})` |

**8nime playback handoff** (`playback.py`): `info=play` resolves at click-time to the configured player — Otaku (`plugin://plugin.video.otaku/play/{mal_id}/{episode}`), WatchNixtoons2 (search by series title), or Fanime F (`plugin.video.fanimef`, keyboard search only). Default = WatchNixtoons2.

---

## 13. The 8nime delta

The stock contract is **TMDb-centric**; 8nime is **AniList-centric**. This single fact drives most of the wiring risk.

| Concern | Stock (TMDb) | 8nime (AniList) | Implication |
|---|---|---|---|
| Primary identity | `tmdb_id` (+ `UniqueID(tmdb)`) | **`mal_id`** then `anilist_id` | Skin touchpoints keyed on `tmdb_id` need a translation or population |
| Property namespace | `TMDbHelper.*` (engine) / `TMDbBingieHelper.*` (fork) | `TMDbBingieHelper.*` (kept) + `AniListBingieHelper.*` (new) | Reload/monitor props kept; auth/title props added |
| Path query building | `tmdb_id`/`imdb_id`/`query` | adds `mal_id`/`anilist_id` first | 8nime patched `Path_Param_Query` accordingly |
| discover filters | `with_genres={Genre.1.TMDb_ID}&with_id=True`, `with_companies={Studio.1.TMDB_ID}` | `with_genres={Genre.1.Name}&with_id=False`, `with_studio={Studio.1.Name}` | helper must accept **name-based** filters |
| Ratings | TMDb/IMDb/RT/Trakt | AniList (`AList_Rating`) | 8nime disables TMDb rating badges |
| Reviews route | `trakt_comments` | aliased to `reviews` | handled in `INFO_ROUTES` |
| Continue/Upcoming | `trakt_ondeck`/`upcoming` | `anilist_nextup`/`anilist_upcoming` | renamed routes; skin patched to call them |
| Auth | Trakt token | Otaku-shared AniList token | gate prop renamed `AniListBingieHelper.HasToken` |
| Playback | TMDb "players" JSON | Otaku/WNT2/Fanime handoff | provider never resolves streams itself |

---

## 14. Gaps, ambiguities & known wiring risks

> **Verified gap register.** Every item below was confirmed against source (skin XML + the `plugin.video.tmdb.bingie.helper` v1.0.2 fork + the 8nime helper code) by two adversarial verification passes. Each carries a stable **gap ID** (`G#`), severity, the exact mismatch, **file:line evidence**, and a fix direction. **Severity:** 🔴 breaks a feature (user-visible failure) · 🟠 degrades UX · 🟡 cosmetic / latent. Use these IDs to track fixes; they are the actionable backbone of this document.

### 14.0 Rehaul status (branch `rehaul/one-request-per-view`)
The one-request-per-view re-architecture closes the register as follows (helper + skin-patch changes; 312 unit tests green):
- **G1/G3** (sync_trakt/cache_refresh dispatch) — FIXED: `default.py:main()` now parses positional action tokens.
- **G2** (identity) — FIXED: items emit a real-or-surrogate `tmdb_id` (`identity.to_tmdb_id`); `sync_trakt_rating` reverse-maps the inbound `tmdb_id`→mal (`identity.resolve_mal_id`).
- **G4** (reload token) — FIXED: `window_state.bump_widget_reload()` writes it after sync/cache actions.
- **G5** (hub enrichment) — DISSOLVED: the 350 ms monitor is deleted; each view's request is self-sufficient (lean rows / rich spotlight) and the More-Info header is request-backed.
- **G6** (artwork/refresh) — FIXED: `select_artwork` (cover/banner override via `art_overrides.py`) + `refresh_details` handlers added.
- **G7** (genre panel) — FIXED: `routes.discover()` no longer defaults an unknown genre to Action.
- **G9** (autocomplete) — already handled by `apply-anime-bingie.py:patch_custom_search_window` (repoints container 1007 to the helper).
- **G11** (spotlight cast-thumb) — FIXED: `enrichment.apply_spotlight` sets `IMDb_Rating`/`Trakt_Rating`.
- **G13** (next-ep play) — works via the deferred `info=play` URL that `play()` resolves to the exact episode server-side per backend.
- **Critical skin patch:** `Container(17195)` is now bound to a request-backed `info=details` path (`patch_tmdbbingie_loader`), replacing the deleted monitor feed.

### 14.1 Provenance — RESOLVED ✅
The `plugin.video.tmdb.bingie.helper` v1.0.2 fork was located (binary zip in `matke-84/repository.bingie`). The `TMDbBingieHelper.*` namespace, the 27 `info=` route names, the reload mechanism, and the monitor-container mechanism are now **confirmed** (see the source table & provenance note at the top). The fork's service monitor *does* write `Window(Home).Property(TMDbBingieHelper.Widgets.Reload)` on item change — which is exactly what 8nime fails to replicate (G4 below).

### 14.2 🔴 Breaks-feature gaps (fix these first)

| ID | Gap | Skin expects | 8nime does | Evidence | Fix direction |
|---|---|---|---|---|---|
| **G1** | **`sync_trakt` RunScript never dispatches** — the action is passed as a *positional* token `sync_trakt` (no `=`), but `main()` builds its args with `dict(arg.split("=",1) for arg in argv if "=" in arg)`, so `sync_trakt` is silently dropped. `args.get("sync_trakt")` is always `None`; the code falls through to `show_description()` → user sees *"No AniList description found."* | every rating button to like/dislike/reset/favorite | nothing (wrong branch) | `default.py:109` (arg parse), `default.py:121` (dispatch); buttons `IncludesDialogVideoInfo.xml` 7011/7033/7055/561 | Detect the positional action token (e.g. accept `sync_trakt` as a bare argv member, or change the skin calls to `action=sync_trakt`). This single bug disables **all** Trakt/AniList rating + favourites. |
| **G2** | **Identity mismatch: buttons send `tmdb_id`, script wants `mal_id`** — even after G1, `sync_trakt_rating` reads `mal_id`→`anilist_id`. `build_item` never sets `tmdb_id` for show/movie items (only person items do), so `ListItem.Property(tmdb_id)` is empty → fallback reads `Container(17195).ListItem.Property(tmdb_id)` which holds an **AniList staff id** (meaningless for rating). | `tmdb_id` carries the rateable id | anime items carry no `tmdb_id`; 17195 carries a staff id | `default.py:77–83`, `listitems.py:283–378` | Either set `tmdb_id = mal_id` in `build_item`, or teach `sync_trakt_rating` to treat the `tmdb_id` slot as an opaque id and prefer `mal_id`. |
| **G3** | **`cache_refresh` never runs** — passed as positional `cache_refresh` instead of `sync_type=cache_refresh`, so `sync_type` is `None` and the function returns silently. | button 562 refreshes cache | no-op | `default.py:84`, `IncludesDialogVideoInfo.xml:740` | Same arg-parse fix as G1, or pass `sync_type=cache_refresh`. |
| **G4** | **`TMDbBingieHelper.Widgets.Reload` is never SET** — the constant exists but has zero callers; nothing ever writes it to the Home window. Every widget `&reload=` token is therefore static → widgets cache indefinitely; changing watchlist / syncing / clearing cache never forces a refresh. (The stock fork sets this from its service monitor.) | a changing reload token to bust widget cache | token never changes | `constants.py:13` (defined, unused) | Have `service.py` write a fresh `System.Time`/counter value to `Window(Home).Property(TMDbBingieHelper.Widgets.Reload)` on relevant events (sync, login, cache clear, periodic). |
| **G5** | **Hub/spotlight enrichment broken** — `service._current_mal_id()` reads `Skin.String(TMDbBingieHelper.WidgetContainer)` and calls `.isdigit()`, but the skin sets that property to the string `"Home"` on hub pages → check fails → the service never reads the focused item's `mal_id` outside the info dialog. `Container(17195)` stays empty on hubs, so spotlight art fallbacks (`Container(17195).ListItem.Art(landscape/fanart/clearlogo)`) are always blank on the home/hub screens. | focused hub item enriched into 17195 | only the info dialog enriches | `service.py:112`, `IncludesFunctions.xml:61` | Handle the non-digit `WidgetContainer` value (resolve the active hub's widget container, or fall back to `Container.Current`/focused container). |
| **G6** | **`select_artwork` & `refresh_details` buttons are completely dead** — (a) no dispatch branch for either action exists in `default.py`; (b) the buttons pass `tmdb_id=$INFO[ListItem.UniqueID(tmdb)]`, but `build_item` sets `UniqueID(mal)` not `UniqueID(tmdb)`, so the id is empty anyway. | buttons 10 / 6 / 612 work | nothing | `default.py:108–141` (no handler), `listitems.py:349` (`UniqueID(mal)`), `IncludesDialogVideoInfo.xml:845–899` | Add `select_artwork` and `refresh_details` handlers keyed on `mal_id`; have buttons pass `mal_id`. |

### 14.3 🟠 Degrades-UX gaps

| ID | Gap | Evidence | Fix direction |
|---|---|---|---|
| **G7** | **`Genre.1.TMDb_ID` holds a genre *name*, not a numeric id.** The genre-credits panel builds `info=discover&with_genres={Genre.1.TMDb_ID}&with_id=True`; with `with_id=True` the helper expects a numeric id and falls back to **Action** for any non-numeric value. (The home genre rows avoid this by using `with_id=False`.) | `listitems.py:173`, `routes.py:326–329` | Either emit a numeric genre id, or make the 53003 path use `with_id=False` + genre name. |
| **G9** | **`autocomplete` route is orphaned.** Search container `1007` still calls `plugin://plugin.program.autocompletion`; the 8nime helper's `autocomplete` handler is never invoked. Live suggestions are not AniList-backed. | `routes.py:380`, `Custom_1109_BingieSearch.xml:124` | Repoint container 1007's content at `plugin://plugin.video.8nime.bingie.helper/?info=autocomplete&id=…` (or remove the dead route). |
| **G13** | **"Play Next episode" degrades on the default backend.** `trakt_upnext` returns a `FileNameAndPath` that is the deferred `info=play` route; for the default search-based players (WatchNixtoons2/Fanime) this opens a results/search window rather than playing the exact next episode. Works correctly only for Otaku. | `info_routes.py:555–561`, `playback.py` | Inherent backend limitation; document it, or prefer Otaku for the next-episode action. |
| **G14** | **~6 stock routes return empty directories** — `trakt_mostplayed`, `trakt_mostviewers`, `trending_week`, `most_voted`, `top_rated`, `revenue_movies` are not handled by `RouteHandler`. Only hit if a user invokes stock Bingie widget shortcuts, but they dead-end silently. | `routes.py:156–165` (dispatch table) | Map them to the nearest AniList equivalent or alias to existing routes. |

### 14.4 🟡 Cosmetic / latent

| ID | Gap | Evidence | Note |
|---|---|---|---|
| **G11** | `IMDb_Rating` / `Trakt_Rating` never set → the spotlight **cast thumb never appears** (its visibility is gated on a rating being present), even for 9.0+ anime. | `listitems.py`, `IncludesHomeBingie.xml:337–399` | Set these to the AniList average-score value. |
| **G12** | `Top250` property never set → ranking badge always hidden. | `service.py:25–37` | Populate if a ranking source is available, else accept. |
| **G10** | `clearlogo` art key never set (AniList has no logo art) → skin falls back to the text title. | `listitems.py:63–85` | Acceptable; optionally source logos from Fanart.tv/TMDb. |
| **G15** | `MONITOR_CONTAINER` hardcoded to `17195` rather than read from `Skin.String(TMDbBingieHelper.MonitorContainer)`. | `service.py:18` | Harmless today (skin always uses 17195); a latent coupling. |

### 14.5 Candidates that were checked and found OK ✅ (do **not** spend time here)

| Suspected gap | Verdict | Evidence |
|---|---|---|
| `relations` / `collection` mis-wired | OK — `relations()` correctly aliases `collection()` | `info_routes.py:439` |
| `discover` rejects `with_studio` / genre-by-name | OK — `discover_extended` honors `with_studio`; `with_id=False` genre path works | `info_routes.py:792` |
| Enrichment window-id mismatch (12003 vs 1190) | OK for the info dialog — `getCurrentWindowDialogId()` returns 1190, which hosts container 17195 via the `Defs_TMDbBingieHelper_Loader` include | `DialogVideoInfo.xml:24` |
| Container(1234) next-ep visibility | OK — 8nime patch adds `| !String.IsEmpty(ListItem.Property(mal_id))` | `IncludesDialogVideoInfo.xml:58` |
| Property casing for Director/Creator/Writer/Cast | OK — both `X.{N}.Name` and `X.{N}.name` are emitted, covering both skin read sites | `listitems.py:209–210` |

### 14.6 Remaining ambiguities (need a human decision)
- 🟠 **Spotlight has two competing sources.** `Skin.String(spotlighthome.path)` = `info=trakt_trending&tmdb_type=tv` vs `$VAR[DefSpotlightWidgetContent]` = `info=random_popular&tmdb_type=both`. Decide which should win so the hero is deterministic (and note G5 means hub-spotlight enrichment is currently blank regardless).
- 🟠 **Person/cast overlay bio fields.** The overlay reads `ListItem.Property(Gender|Department|Birthday|Deathday|Age|Born|Biography)`; AniList supplies only a subset. Decide which to populate vs accept blank.
- 🟠 **Suggested fix ordering.** G1 → G2 → G4 are the highest leverage (they restore ratings, favourites, and widget refresh — the core interactive loop). G5/G6 next (spotlight enrichment + artwork/refresh). G7/G9 are quick wins.

---

## 15. Appendix — critical identifier index

**Plugin base URL:** `plugin://plugin.video.8nime.bingie.helper/` (stock: `plugin://plugin.video.tmdb.bingie.helper/`)

**Must-set window properties:** `TMDbBingieHelper.Widgets.Reload` (reload token), `TMDbBingieHelper.MonitorContainer`=`17195`, `TMDbBingieHelper.Service`, `AniListBingieHelper.HasToken`.

**Monitor container:** `17195` (hidden; holds focused-item enrichment).

**Info dialog window:** `1190` (`movieinformation`); action bar `8000`; credits sub-nav `8999`; person sub-nav `2999`.

**Identity properties:** `mal_id` (8nime primary) → `anilist_id` → `imdb_id` / `tmdb_id`; `UniqueID(tmdb)`; `tmdb_type` (`movie|tv|person`); `DBTYPE`.

**Essential art keys:** `poster`, `fanart`, `landscape`, `clearlogo`, `thumb` (+ `tvshow.*`/`season.*` variants).

**Essential InfoLabels:** `Title`, `Plot`, `Genre`, `Year`, `DBTYPE`, `FileNameAndPath`, `TVShowTitle`/`Season`/`Episode`/`TotalEpisodes`/`TotalSeasons`/`UnWatchedEpisodes`.

**Container 17195 indexed props (verbatim casing):** `tmdb_id`, `Genre.{1..3}.Name`, `Cast.{1..5}.name`, `Director.{1..5}.name`+`.TMDb_ID`, `Creator.{1..3}.name`+`.TMDb_ID`, `Writer.{1..5}.name`+`.TMDb_ID`+`.job`, `Studio.1.Name`, `Network.1.Name`, `Top250`, `Set`.

**Routes the skin calls (must all be served):** `trakt_trending`, `trakt_popular`, `trakt_userlist`, `trakt_favorites`, `anilist_nextup`, `anilist_upcoming`, `random_popular`, `random_trending`, `discover`, `dir_tv`, `dir_movie`, `dir_ova`, `search`, `autocomplete`, `cast`, `crew`, `recommendations`, `relations`/`collection`, `videos`, `trakt_comments`(→`reviews`), `trakt_upnext`, `posters`, `seasons`/`flatseasons`, `episodes`, `details`, `stars_in_movies`, `stars_in_tvshows`, `crew_in_movies`, `crew_in_tvshows`, `crew_in_both`.

**RunScript actions:** `sync_trakt` (`like|dislike|reset|favorites|cache_refresh`), `description`, `clear_cache`, `clear_expired_cache`, `select_artwork`, `refresh_details`, `close_dialog`, `add_path`, `call_path`.

**Reload pattern (verbatim):** `reload=$INFO[Window(Home).Property(TMDbBingieHelper.Widgets.Reload)]`

---

*Generated 2026-06-08 from source: skin.bingie `9f1c6eb`, plugin.video.tmdb.bingie.helper v1.0.2 (binary fork in matke-84/repository.bingie), themoviedb.helper `bf098f9` (v6.15.6, upstream engine), script.bingie.helper `b098b62`, the 8nime build skin patches, and `plugin.video.8nime.bingie.helper` v1.5.0. §14 (gap register) reflects two completed adversarial verification passes with file:line evidence. Raw per-area research is preserved under `.bingie-research/` (sections 01–07).*
