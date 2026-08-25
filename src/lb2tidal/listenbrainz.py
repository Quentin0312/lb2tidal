"""ListenBrainz API client and JSPF parsing (FR-1, FR-2).

Only two endpoints are used, both plain JSON GETs, which is why no client
library is pulled in (§4.3.3).
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Any

import requests

from .retry import TIMEOUT, with_retry

log = logging.getLogger(__name__)

API = "https://api.listenbrainz.org/1"
JSPF_PLAYLIST_EXT = "https://musicbrainz.org/doc/jspf#playlist"

#: How many entries of ``createdfor`` to scan. ListenBrainz returns newest first
#: and generates a handful of recommendations per user, so one page is ample.
PAGE_SIZE = 50

_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_MBID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


@dataclass(frozen=True)
class Track:
    artist: str
    title: str


@dataclass(frozen=True)
class Playlist:
    """One ListenBrainz recommendation playlist, already parsed."""

    recommendation: str
    mbid: str
    title: str
    description: str
    tracks: list[Track]
    skipped: int


def strip_html(raw: str | None) -> str:
    """ListenBrainz serves ``annotation`` as HTML; playlist descriptions are text."""
    if not raw:
        return ""
    text = _TAG.sub(" ", raw)
    text = html.unescape(text)
    return _WHITESPACE.sub(" ", text).strip()


def _mbid_from(identifier: Any) -> str:
    """Pull an MBID out of a JSPF identifier, which may be a string or a list."""
    if isinstance(identifier, list):
        identifier = identifier[0] if identifier else ""
    match = _MBID.search(str(identifier))
    return match.group(1) if match else ""


class Client:
    def __init__(self, user: str, token: str = "") -> None:
        self.user = user
        self._session = requests.Session()
        if token:
            self._session.headers["Authorization"] = f"Token {token}"

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        url = f"{API}{path}"

        def call() -> dict[str, Any]:
            response = self._session.get(url, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            return response.json()

        # ``path`` is safe to log; the token lives in a header, never in the URL.
        return with_retry(f"GET {path}", call)

    def recommendation_index(self) -> dict[str, dict[str, Any]]:
        """Map each available recommendation to its most recent playlist stub."""
        data = self._get(f"/user/{self.user}/playlists/createdfor", count=PAGE_SIZE)
        found: dict[str, dict[str, Any]] = {}

        for entry in data.get("playlists", []):
            stub = entry.get("playlist", {})
            name = self._recommendation_of(stub)
            if name and name not in found:  # newest first, so the first wins
                found[name] = stub
        return found

    @staticmethod
    def _recommendation_of(stub: dict[str, Any]) -> str:
        extension = stub.get("extension", {}).get(JSPF_PLAYLIST_EXT, {})
        metadata = extension.get("additional_metadata", {})
        patch = metadata.get("algorithm_metadata", {}).get("source_patch")
        if patch:
            return str(patch)

        title = str(stub.get("title", "")).casefold()
        for known in ("weekly-exploration", "weekly-jams", "daily-jams"):
            if known.replace("-", " ") in title:
                log.warning("no source_patch on %r, matched %r by title", stub.get("title"), known)
                return known
        return ""

    def fetch(self, recommendation: str, stub: dict[str, Any]) -> Playlist:
        """Fetch and parse the full JSPF for one recommendation (FR-2)."""
        mbid = _mbid_from(stub.get("identifier"))
        if not mbid:
            raise ValueError(f"{recommendation}: playlist has no usable identifier")

        payload = self._get(f"/playlist/{mbid}")["playlist"]

        tracks: list[Track] = []
        skipped = 0
        for item in payload.get("track", []):
            title = str(item.get("title") or "").strip()
            if not title:
                skipped += 1
                continue
            tracks.append(Track(artist=str(item.get("creator") or "").strip(), title=title))

        return Playlist(
            recommendation=recommendation,
            mbid=mbid,
            title=str(payload.get("title") or ""),
            description=strip_html(payload.get("annotation"))[:500],
            tracks=tracks,
            skipped=skipped,
        )
