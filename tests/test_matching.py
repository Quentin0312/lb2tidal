"""Table-driven tests for normalisation and scoring (§9).

`matching` is free of I/O, so nothing here needs mocks, fixtures, or network.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from lb2tidal.matching import Candidate, best_match, normalise

THRESHOLD = 0.62
ARTIST_WEIGHT = 0.4

CORPUS = Path(__file__).parent / "corpus.csv"


def _load_corpus() -> list[tuple[str, str, str, str, str]]:
    rows = []
    with CORPUS.open(encoding="utf-8") as handle:
        for line in csv.DictReader(row for row in handle if not row.startswith("#")):
            rows.append(
                (
                    line["kind"],
                    line["lb_artist"],
                    line["lb_title"],
                    line["cand_artist"],
                    line["cand_title"],
                )
            )
    return rows


CORPUS_ROWS = _load_corpus()


# --- normalisation --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Radiohead", "radiohead"),
        ("RADIOHEAD", "radiohead"),
        ("  Radiohead  ", "radiohead"),
        ("Beyoncé", "beyonce"),
        ("Sigur Rós", "sigur ros"),
        ("Mötley Crüe", "motley crue"),
        ("D.A.N.C.E.", "dance"),
        ("AC/DC", "acdc"),
        ("Multiple   spaces", "multiple spaces"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalise(raw: str | None, expected: str) -> None:
    assert normalise(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Karma Police (Remastered)", "karma police"),
        ("Come As You Are - Remastered 2011", "come as you are"),
        ("Time (Live at Pompeii)", "time"),
        ("Let It Be (Deluxe Edition)", "let it be"),
        ("Around the World (Radio Edit)", "around the world"),
        ("Song (Bonus Track)", "song"),
        ("Track (Version 2)", "track"),
        ("Witch (feat. Alina Pash)", "witch"),
        ("Witch (ft. Alina Pash)", "witch"),
        # ListenBrainz emits credits unparenthesised; this is the real-world form.
        ("Apashe feat. Alina Pash", "apashe"),
        ("Artist ft. Guest", "artist"),
    ],
)
def test_normalise_strips_noise_markers(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_normalise_keeps_non_latin_scripts() -> None:
    assert normalise("宇多田ヒカル") == "宇多田ヒカル"


# --- matching against the labelled corpus ---------------------------------


@pytest.mark.parametrize(
    ("kind", "lb_artist", "lb_title", "cand_artist", "cand_title"),
    CORPUS_ROWS,
    ids=[f"{k}:{a}-{t}" for k, a, t, _, _ in CORPUS_ROWS],
)
def test_corpus(
    kind: str, lb_artist: str, lb_title: str, cand_artist: str, cand_title: str
) -> None:
    candidates = [Candidate(id=1, artist=cand_artist, title=cand_title)]
    result = best_match(candidates, lb_artist, lb_title, THRESHOLD, ARTIST_WEIGHT)

    if kind == "match":
        assert result is not None, f"{lb_artist} — {lb_title} should match {cand_title!r}"
    elif kind == "reject":
        assert result is None, f"{lb_artist} — {lb_title} should NOT match {cand_title!r}"
    else:  # xfail: a known false positive at the current, uncalibrated defaults
        pytest.xfail(
            f"{lb_artist} — {lb_title} wrongly matches {cand_artist} — {cand_title} "
            "at the inherited defaults (see M4)"
        )


# --- selection, determinism, tie-breaking ---------------------------------


def test_best_match_picks_highest_score() -> None:
    candidates = [
        Candidate(id=1, artist="Radiohead", title="Creep (Acoustic)"),
        Candidate(id=2, artist="Radiohead", title="Creep"),
        Candidate(id=3, artist="Radiohead", title="Creep (Live)"),
    ]
    result = best_match(candidates, "Radiohead", "Creep", THRESHOLD, ARTIST_WEIGHT)
    assert result is not None
    assert result[0].id == 2


def test_ties_keep_tidal_ordering() -> None:
    candidates = [
        Candidate(id=11, artist="Radiohead", title="Creep"),
        Candidate(id=22, artist="Radiohead", title="Creep"),
    ]
    result = best_match(candidates, "Radiohead", "Creep", THRESHOLD, ARTIST_WEIGHT)
    assert result is not None
    assert result[0].id == 11, "the first result Tidal returned must win a tie"


def test_no_candidates_is_a_miss() -> None:
    assert best_match([], "Radiohead", "Creep", THRESHOLD, ARTIST_WEIGHT) is None


def test_matching_is_deterministic() -> None:
    candidates = [
        Candidate(id=1, artist="Korn", title="Coming Undone"),
        Candidate(id=2, artist="Korn", title="Coming Undone (Remix)"),
    ]
    runs = {
        best_match(candidates, "Korn", "Coming Undone", THRESHOLD, ARTIST_WEIGHT)[0].id
        for _ in range(20)
    }
    assert runs == {1}


def test_threshold_of_one_rejects_near_misses() -> None:
    candidates = [Candidate(id=1, artist="Radiohead", title="Creepy")]
    assert best_match(candidates, "Radiohead", "Creep", 1.0, ARTIST_WEIGHT) is None


def test_artist_weight_of_zero_ignores_the_artist() -> None:
    candidates = [Candidate(id=1, artist="Completely Different", title="Creep")]
    assert best_match(candidates, "Radiohead", "Creep", THRESHOLD, 0.0) is not None
