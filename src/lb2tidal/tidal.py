"""Tidal session lifecycle, search and playlist writes (§5.4, §6.1)."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import tidalapi
from tidalapi.playlist import UserPlaylist

from .errors import AuthError, RecommendationError
from .matching import Candidate
from .retry import with_retry

log = logging.getLogger(__name__)

#: Tidal rejects large batches; the playlist is refilled in chunks of this size.
ADD_CHUNK = 50


def _harden(path: Path) -> None:
    """The session file holds a refresh token granting full account access (NFR-4)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, stat.S_IRWXU)
    if path.exists():
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def load_session(session_file: Path) -> tidalapi.Session:
    """Restore a saved session, or fail with an actionable message (NFR-2)."""
    session = tidalapi.Session()

    if not session_file.is_file():
        raise AuthError(f"no Tidal session at {session_file}. Run: lb2tidal login")

    try:
        session.load_session_from_file(session_file)
    except Exception as exc:  # tidalapi raises assorted types for a bad file
        raise AuthError(f"{session_file}: unusable session ({exc}). Run: lb2tidal login") from exc

    if not session.check_login():
        raise AuthError(f"{session_file}: session expired. Run: lb2tidal login")

    # Refreshing the token rewrites the file; keep the permissions tight.
    _harden(session_file)
    return session


def login(session_file: Path, force: bool = False) -> tidalapi.Session:
    """Run the OAuth device flow and persist the session (FR-8).

    Uses the device flow, not PKCE: PKCE needs a browser redirect and is unusable
    over SSH.
    """
    session = tidalapi.Session()

    if session_file.is_file() and not force:
        try:
            session.load_session_from_file(session_file)
            if session.check_login():
                raise AuthError(
                    f"a valid session already exists at {session_file}. "
                    "Use --force to replace it."
                )
        except AuthError:
            raise
        except Exception:  # unreadable or stale: replacing it is the point
            session = tidalapi.Session()

    session.login_oauth_simple(fn_print=lambda message: print(message, flush=True))

    if not session.check_login():
        raise AuthError("authorisation was not completed")

    session_file.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(session_file.parent, stat.S_IRWXU)
    session.save_session_to_file(session_file)
    _harden(session_file)
    log.info("session saved to %s", session_file)
    return session


def search_tracks(session: tidalapi.Session, query: str, limit: int) -> list[Candidate]:
    """Search Tidal, returning results as plain Candidates so matching stays pure."""

    def call() -> list[Candidate]:
        results = session.search(query, models=[tidalapi.media.Track], limit=limit)
        found = []
        for track in results.get("tracks") or []:
            artist = track.artist.name if track.artist else ""
            found.append(Candidate(id=track.id, artist=artist or "", title=track.name or ""))
        return found

    return with_retry(f"search {query!r}", call)


def find_playlist(session: tidalapi.Session, name: str) -> UserPlaylist | None:
    """Look a playlist up by exact name among the user's own playlists."""
    matches = [p for p in with_retry("list playlists", session.user.playlists) if p.name == name]

    if len(matches) > 1:
        raise RecommendationError(
            f"{len(matches)} playlists are named {name!r}; refusing to guess which to update"
        )
    if not matches:
        return None
    return UserPlaylist(session, matches[0].id)


def ensure_playlist(
    session: tidalapi.Session, name: str, description: str
) -> tuple[UserPlaylist, bool]:
    """Return the target playlist, creating it if absent. Second value: was created."""
    existing = find_playlist(session, name)
    if existing is not None:
        return existing, False

    log.info("creating playlist %r", name)
    created = with_retry(
        f"create playlist {name!r}",
        lambda: session.user.create_playlist(name, description),
    )
    return created, True


def current_track_ids(playlist: UserPlaylist) -> list[int]:
    """Every track ID currently in the playlist, fully paginated."""
    tracks = with_retry("read playlist", playlist.tracks_paginated)
    return [track.id for track in tracks]


def mirror(playlist: UserPlaylist, track_ids: list[int]) -> bool:
    """Replace the playlist contents. Returns False when already identical (FR-5).

    Tidal offers no atomic replace, so the playlist is briefly empty between the
    clear and the first add.
    """
    if current_track_ids(playlist) == track_ids:
        return False

    with_retry("clear playlist", playlist.clear)
    for start in range(0, len(track_ids), ADD_CHUNK):
        chunk = [str(i) for i in track_ids[start : start + ADD_CHUNK]]
        with_retry("add tracks", lambda c=chunk: playlist.add(c))
    return True
