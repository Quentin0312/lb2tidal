"""The sync run itself: resolve tracks and mirror playlists (§4.2)."""

from __future__ import annotations

import logging

import tidalapi

from . import listenbrainz, matching, tidal
from .config import Config
from .errors import RecommendationError, ServiceUnavailable
from .report import Entry, Report, Status
from .retry import RetriesExhausted
from .state import State

log = logging.getLogger(__name__)

#: Consecutive track failures after which the remote service is treated as down
#: and the recommendation is abandoned (§5.5).
FAILURE_LIMIT = 5


def target_name(prefix: str, recommendation: str) -> str:
    return f"{prefix}{recommendation.replace('-', ' ').title()}"


def resolve(
    session: tidalapi.Session,
    track: listenbrainz.Track,
    config: Config,
) -> int | None:
    """Best Tidal track ID for one ListenBrainz track, or None (FR-3)."""
    queries = [f"{track.artist} {track.title}".strip()]
    if track.artist:
        queries.append(track.title)  # fallback: the artist string may be the problem

    for query in queries:
        candidates = tidal.search_tracks(session, query, config.matching.search_limit)
        found = matching.best_match(
            candidates,
            track.artist,
            track.title,
            config.matching.threshold,
            config.matching.artist_weight,
        )
        if found is not None:
            candidate, score = found
            log.debug("%s — %s -> %s (%.2f)", track.artist, track.title, candidate.id, score)
            return candidate.id
    return None


def _resolve_all(
    session: tidalapi.Session,
    playlist: listenbrainz.Playlist,
    config: Config,
) -> tuple[list[int], list[tuple[str, str]]]:
    track_ids: list[int] = []
    misses: list[tuple[str, str]] = []
    consecutive_failures = 0

    for track in playlist.tracks:
        try:
            found = resolve(session, track, config)
        except RetriesExhausted as exc:
            consecutive_failures += 1
            if consecutive_failures >= FAILURE_LIMIT:
                raise ServiceUnavailable(
                    f"{FAILURE_LIMIT} consecutive lookups failed, treating Tidal as down ({exc})"
                ) from exc
            misses.append((track.artist, track.title))
            log.warning("MISS %s — %s (lookup failed)", track.artist, track.title)
            continue

        consecutive_failures = 0
        if found is None:
            misses.append((track.artist, track.title))
            log.info("MISS %s — %s", track.artist, track.title)
        else:
            track_ids.append(found)
            log.info("ok   %s — %s", track.artist, track.title)

    return track_ids, misses


def _sync_one(
    session: tidalapi.Session,
    client: listenbrainz.Client,
    name: str,
    stub: dict,
    config: Config,
    state: State,
    dry_run: bool,
    force: bool,
) -> Entry:
    playlist = client.fetch(name, stub)

    if not force and state.unchanged(name, playlist.mbid):
        detail = f"source playlist unchanged since {state.synced_at(name) or 'the last run'}"
        log.info("%s: %s", name, detail)
        return Entry(name=name, status=Status.SKIPPED, detail=detail)

    if playlist.skipped:
        log.warning("%s: %d track(s) had no title and were skipped", name, playlist.skipped)

    log.info("%s — %s (%d tracks)", name, playlist.title, len(playlist.tracks))
    track_ids, misses = _resolve_all(session, playlist, config)
    target = target_name(config.tidal.prefix, name)

    entry = Entry(
        name=name,
        status=Status.UPDATED,
        playlist_title=playlist.title,
        target=target,
        requested=len(playlist.tracks),
        matched=len(track_ids),
        missed=len(misses),
        misses=misses,
    )

    if dry_run:
        exists = tidal.find_playlist(session, target) is not None
        entry.status = Status.WOULD_UPDATE if exists else Status.WOULD_CREATE
        return entry

    target_playlist, created = tidal.ensure_playlist(session, target, playlist.description)
    changed = tidal.mirror(target_playlist, track_ids)

    if created:
        entry.status = Status.CREATED
    elif changed:
        entry.status = Status.UPDATED
    else:
        entry.status = Status.UNCHANGED

    state.record(name, playlist.mbid)
    return entry


def run(
    config: Config,
    *,
    dry_run: bool = False,
    force: bool = False,
    only: list[str] | None = None,
) -> Report:
    """Sync every configured recommendation, isolating per-recommendation failures."""
    report = Report()
    client = listenbrainz.Client(config.listenbrainz.user, config.listenbrainz.token)
    state = State(config.state_file)

    wanted = only or config.listenbrainz.recommendations
    index = client.recommendation_index()
    log.debug("available on the account: %s", ", ".join(sorted(index)) or "none")

    # A dry run still searches Tidal, so it needs a session too; it only skips writes.
    session = tidal.load_session(config.tidal.session_file)

    for name in wanted:
        stub = index.get(name)
        if stub is None:
            detail = "configured, but ListenBrainz has not generated it for this account"
            log.warning("%s: %s", name, detail)
            report.add(Entry(name=name, status=Status.NOT_AVAILABLE, detail=detail))
            continue

        try:
            report.add(
                _sync_one(session, client, name, stub, config, state, dry_run, force)
            )
        except (RecommendationError, RetriesExhausted, ValueError) as exc:
            log.error("%s: %s", name, exc)
            report.add(Entry(name=name, status=Status.FAILED, error=str(exc)))

    return report
