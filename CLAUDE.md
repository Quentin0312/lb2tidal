# CLAUDE.md

## What this is

`lb2tidal` mirrors ListenBrainz recommendation playlists into Tidal. One-way and
idempotent: ListenBrainz is the source of truth.

**`docs/SPECIFICATION.md` is the reference.** It carries the requirements
(FR-*/NFR-*), the detailed behaviour, and — more usefully — *why* each decision
was made and what was rejected. Read the relevant section before changing
behaviour; do not re-derive a decision it already settles.

## Commands

```sh
pip install -e ".[dev]"
ruff check .          # must be clean
pytest                # must be green
lb2tidal sync --dry-run   # integration test: hits the real APIs, writes nothing
```

## Conventions not visible from the code

- **`matching.py` must stay free of I/O.** It is the only module under
  automated test, precisely because it has no dependencies to mock (§9).
- **Only `matching.py` is unit-tested, on purpose.** Every other failure mode is
  loud (crash, exit code, journald). A matching regression is silent — it puts
  the wrong track in a playlist. Do not add mock-based tests for `tidal.py`;
  they would test the mock.
- **`cli.py` holds no business logic** beyond argument parsing and exit-code
  mapping. The run lives in `sync.py`.
- **Never log the Tidal session file's contents or the ListenBrainz token.** The
  session holds a refresh token granting full account access; it is written
  `0600` (NFR-4).
- Docs and code comments are in English; the repository is public.

## Traps

- **The `src` layout is load-bearing.** A `lb2tidal.py` at the repository root
  shadows the package and breaks imports — that is exactly what happened to the
  prototype.
- **`dict.get(k, default)` returns the default only when the key is absent.**
  ListenBrainz sends `"annotation": null`, which crashed the prototype.
- **ListenBrainz `annotation` is HTML**, and JSPF `identifier` is a *list*.
- **Tidal `UserPlaylist.add()` takes string IDs**, and `tracks()` silently
  truncates — use `tracks_paginated()`.
- **Matching defaults are calibrated but narrowly** (§5.2): 100 live tracks, all
  of which existed on Tidal. `artist_weight` is still unvalidated and the miss
  path has never run in production.
