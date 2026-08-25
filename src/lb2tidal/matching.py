"""Normalisation and scoring.

This module is deliberately free of I/O so it can be tested exhaustively without
mocks, fixtures, or network (§4.1, §9).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Everything from the first marker onwards is dropped before comparison.
#: The unparenthesised ``feat.``/``ft.`` forms matter: ListenBrainz emits credits
#: as ``Apashe feat. Alina Pash``, which the parenthesised variants never match.
NOISE_MARKERS: tuple[str, ...] = (
    "(remaster",
    "- remaster",
    "(live",
    "(version",
    "(deluxe",
    "(bonus",
    "(radio edit",
    "- radio edit",
    "(feat.",
    "(ft.",
    " feat. ",
    " ft. ",
    # Soundtrack tagging: Tidal appends the show, ListenBrainz does not.
    "(from the",
    "(from ",
    # Phonk/edit variants, which both sides label inconsistently.
    "(slowed",
    "- slowed",
    "(sped up",
    "- sped up",
    "(reverb",
)


@dataclass(frozen=True)
class Candidate:
    """A search result, decoupled from any Tidal type so matching stays pure."""

    id: int
    artist: str
    title: str


def normalise(value: str | None) -> str:
    """Casefold, strip accents, cut at noise markers, keep only alphanumerics."""
    if not value:
        return ""

    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))

    cut = len(text)
    for marker in NOISE_MARKERS:
        found = text.find(marker)
        if found != -1:
            cut = min(cut, found)
    text = text[:cut]

    text = "".join(c for c in text if c.isalnum() or c.isspace())
    return " ".join(text.split())


def _ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def artist_similarity(candidate_norm: str, query_norm: str) -> float:
    """Similarity of two normalised artist strings, tolerant of dropped collaborators.

    ListenBrainz credits every artist (``JID & Kenny Mason``) where Tidal often
    lists only the principal (``JID``). Plain string similarity scores that pair
    at 0.33 — no better than two unrelated artists who happen to share a song
    title. So when one set of words contains the other, the artists are treated
    as the same. That is what separates a dropped collaborator from a homonym:
    ``{jid} <= {jid, kenny, mason}`` holds, ``{technicolor, stew}`` against
    ``{denzel, curry, gizzle, bren, joy}`` does not.
    """
    if not candidate_norm or not query_norm:
        return _ratio(candidate_norm, query_norm)

    candidate_words = set(candidate_norm.split())
    query_words = set(query_norm.split())
    if candidate_words <= query_words or query_words <= candidate_words:
        return 1.0
    return _ratio(candidate_norm, query_norm)


def score(
    candidate: Candidate,
    artist_norm: str,
    title_norm: str,
    artist_weight: float,
) -> float:
    """Weighted similarity of a candidate against pre-normalised query terms."""
    artist = artist_similarity(normalise(candidate.artist), artist_norm)
    title = _ratio(normalise(candidate.title), title_norm)
    return artist_weight * artist + (1.0 - artist_weight) * title


def best_match(
    candidates: list[Candidate],
    artist: str,
    title: str,
    threshold: float,
    artist_weight: float,
) -> tuple[Candidate, float] | None:
    """Highest-scoring candidate at or above ``threshold``, or None.

    Ties keep the earliest candidate, preserving Tidal's own relevance ordering.
    """
    artist_norm = normalise(artist)
    title_norm = normalise(title)

    best: Candidate | None = None
    best_score = -1.0
    for candidate in candidates:
        current = score(candidate, artist_norm, title_norm, artist_weight)
        if current > best_score:
            best, best_score = candidate, current

    if best is not None and best_score >= threshold:
        return best, best_score
    return None
