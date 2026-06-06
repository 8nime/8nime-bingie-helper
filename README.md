# 8nime Bingie Helper

AniList-powered metadata and widget provider for the Bingie skin on Kodi.

## Overview

8nime Bingie Helper is a Kodi plugin that supplies the Bingie skin with home-screen hub widgets, More Info panels, and full anime metadata sourced from the AniList GraphQL API. It handles franchise and season grouping by mapping multi-cour series to canonical season numbers using the Fribb/anime-lists TVDB season map, so split cours appear as a single coherent franchise rather than unrelated entries. The addon does not play any content directly — when you choose to watch an episode or movie, playback is delegated to one of the supported player addons: Otaku, WatchNixtoons2, or Fanime F. It is developed and distributed as part of the 8nime Kodi build.

## Features

- **AniList My List sync** — pulls your Watching, Planning, and Continue Watching lists when authenticated with AniList
- **Continue Watching widget** — surfaces in-progress series ordered by last activity, filtered to episodes you have not yet completed
- **Franchise and season grouping** — collapses multi-cour series into numbered seasons using the Fribb TVDB map, with AniList relation walking as a fallback for unmapped titles
- **Episode list** — per-season episode grids with thumbnails sourced from AniList streaming episode data
- **More Info metadata** — full detail panels with synopsis, genres, score, characters, voice actors, staff credits, related titles, recommendations, and user reviews
- **Bingie hub widgets** — trending, popular this season, last season, all-time popular, new movies, OVA/ONA/Special browse, upcoming next season, and genre discovery rows
- **Search and autocomplete** — AniList-backed title search with live suggestion support for the Bingie search box
- **Score sync** — like or dislike an entry to write a score back to your AniList account
- **Rate-limit aware caching** — disk and in-memory GraphQL response cache with stale-on-error fallback and automatic 429 backoff

## Requirements

- Kodi 21 Omega or later
- Bingie skin
- AniList account (free — only required for My List and Continue Watching features)
- 8nime build, or a manual installation from the 8nime repository (see below)

## Installation

### Via 8nimeWizard (recommended)

Install the 8nime build using 8nimeWizard. The addon is included and configured automatically.

### Manual install from the 8nime repository

1. In Kodi, go to **Settings > File Manager > Add Source** and add `https://8nime.github.io/8nime-repo/repo/` with the name `8nime`.
2. Go to **Settings > Addons > Install from zip file**, select the `8nime` source, and install `repository.8nime`.
3. Go to **Settings > Addons > Install from repository > 8nime Repository** and install **8nime Bingie Helper**.

## AniList Setup

Open the addon settings and select **Authenticate with AniList**. Follow the on-screen PIN flow to link your account. Once authenticated, the My List, Continue Watching, and score-sync features become available. The addon works without authentication for all browse and search features.

## Development

No Kodi installation is required to run the test suite. Kodi stubs are bundled with the project.

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Related Repositories

| Repository | Purpose |
|---|---|
| [8nime-wizard](https://github.com/8nime/8nime-wizard) | Kodi build wizard — installs and updates the full 8nime build |
| [8nime-repo](https://github.com/8nime/8nime-repo) | Kodi addon repository hosting all 8nime addons |
| [8nime-bingie-helper](https://github.com/8nime/8nime-bingie-helper) | This addon — AniList metadata and widget provider for the Bingie skin |
