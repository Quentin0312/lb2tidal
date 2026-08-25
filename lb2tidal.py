#!/usr/bin/env python3
"""
lb2tidal — pousse les playlists de recommandation ListenBrainz vers Tidal.

Dépendances :
    pip install tidalapi requests

Config par variables d'environnement :
    LB_USER      ton pseudo ListenBrainz (obligatoire)
    LB_TOKEN     token LB, optionnel (utile si tes playlists sont privées)
    LB_SOURCES   sources à synchro, séparées par des virgules
                 (défaut: weekly-jams,weekly-exploration,daily-jams)
    TIDAL_SESSION  chemin du fichier de session Tidal
                 (défaut: ~/.config/lb2tidal/tidal.json)
    PREFIX       préfixe des playlists créées côté Tidal (défaut: "LB · ")

Usage :
    python lb2tidal.py            # synchro
    python lb2tidal.py --dry-run  # montre juste le matching, n'écrit rien

Au premier lancement, tidalapi affiche une URL link.tidal.com à ouvrir pour
autoriser l'appli. Le token est ensuite réutilisé et rafraîchi tout seul.
"""

import os
import pathlib
import sys
from difflib import SequenceMatcher

import requests
import tidalapi

LB_API = "https://api.listenbrainz.org/1"
LB_USER = os.environ.get("LB_USER")
LB_TOKEN = os.environ.get("LB_TOKEN")
SOURCES = [s.strip() for s in os.environ.get(
    "LB_SOURCES", "weekly-jams,weekly-exploration,daily-jams").split(",") if s.strip()]
PREFIX = os.environ.get("PREFIX", "LB · ")
SESSION_FILE = pathlib.Path(
    os.environ.get("TIDAL_SESSION", "~/.config/lb2tidal/tidal.json")).expanduser()

DRY_RUN = "--dry-run" in sys.argv
MATCH_THRESHOLD = 0.62  # score mini pour accepter un résultat de recherche Tidal


# --------------------------------------------------------------------------
# ListenBrainz
# --------------------------------------------------------------------------

def lb_get(path, **params):
    headers = {"Authorization": f"Token {LB_TOKEN}"} if LB_TOKEN else {}
    r = requests.get(f"{LB_API}{path}", headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def dig(d, *keys, default=None):
    """Accès imbriqué tolérant aux clés manquantes."""
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def playlist_source(pl):
    """Récupère l'identifiant d'algo (weekly-jams, etc.) d'une playlist JSPF."""
    ext = dig(pl, "extension", "https://musicbrainz.org/doc/jspf#playlist", default={})
    src = dig(ext, "additional_metadata", "algorithm_metadata", "source_patch")
    if src:
        return src
    # Repli : on devine à partir du titre ("Weekly Jams for toto, week of ...")
    title = (pl.get("title") or "").lower()
    for candidate in SOURCES:
        if candidate.replace("-", " ") in title:
            return candidate
    return None


def latest_recommendation_playlists():
    """Retourne {source: jspf_playlist} — la plus récente de chaque source."""
    data = lb_get(f"/user/{LB_USER}/playlists/createdfor", count=50)
    found = {}
    for item in data.get("playlists", []):
        pl = item.get("playlist", {})
        src = playlist_source(pl)
        if src in SOURCES and src not in found:  # l'API renvoie du plus récent au plus ancien
            mbid = pl["identifier"].rstrip("/").split("/")[-1]
            found[src] = lb_get(f"/playlist/{mbid}")["playlist"]
    return found


def jspf_tracks(pl):
    """[(artiste, titre), ...] depuis une playlist JSPF."""
    out = []
    for t in pl.get("track", []):
        title = (t.get("title") or "").strip()
        artist = (t.get("creator") or "").strip()
        if title:
            out.append((artist, title))
    return out


# --------------------------------------------------------------------------
# Tidal
# --------------------------------------------------------------------------

def tidal_session():
    session = tidalapi.Session()
    if SESSION_FILE.exists():
        try:
            session.load_session_from_file(SESSION_FILE)
        except Exception:
            pass
    if not session.check_login():
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        session.login_oauth_simple()  # affiche une URL à ouvrir
        session.save_session_to_file(SESSION_FILE)
    return session


def norm(s):
    s = s.lower()
    for junk in ("(remastered)", "- remastered", "(feat.", "(ft.", "(live)"):
        s = s.split(junk)[0]
    return "".join(c for c in s if c.isalnum() or c.isspace()).strip()


def score(cand_artist, cand_title, artist, title):
    a = SequenceMatcher(None, norm(cand_artist), norm(artist)).ratio()
    t = SequenceMatcher(None, norm(cand_title), norm(title)).ratio()
    return 0.4 * a + 0.6 * t


def find_track(session, artist, title):
    """Cherche le meilleur match Tidal, ou None."""
    for query in (f"{artist} {title}", title):
        try:
            res = session.search(query, models=[tidalapi.media.Track], limit=15)
        except Exception as e:
            print(f"    ! recherche échouée ({e})")
            continue
        best, best_score = None, 0.0
        for tr in res.get("tracks", []):
            s = score(tr.artist.name if tr.artist else "", tr.name, artist, title)
            if s > best_score:
                best, best_score = tr, s
        if best and best_score >= MATCH_THRESHOLD:
            return best
    return None


def get_or_create_playlist(session, name, description=""):
    for pl in session.user.playlists():
        if pl.name == name:
            return tidalapi.playlist.UserPlaylist(session, pl.id)
    return session.user.create_playlist(name, description)


def replace_tracks(playlist, track_ids):
    """Vide la playlist puis y remet les pistes (index décroissant = pas de décalage)."""
    for i in range(len(playlist.tracks()) - 1, -1, -1):
        playlist.remove_by_index(i)
    for i in range(0, len(track_ids), 50):  # Tidal n'aime pas les gros batchs
        playlist.add(track_ids[i:i + 50])


# --------------------------------------------------------------------------

def main():
    if not LB_USER:
        sys.exit("LB_USER n'est pas défini.")

    playlists = latest_recommendation_playlists()
    if not playlists:
        sys.exit("Aucune playlist trouvée. Vérifie LB_USER et LB_SOURCES.")

    session = None if DRY_RUN else tidal_session()

    for src, pl in playlists.items():
        wanted = jspf_tracks(pl)
        print(f"\n=== {src} — {pl.get('title')} ({len(wanted)} pistes)")

        if DRY_RUN:
            for artist, title in wanted:
                print(f"    {artist} — {title}")
            continue

        ids, missing = [], []
        for artist, title in wanted:
            match = find_track(session, artist, title)
            if match:
                ids.append(match.id)
                print(f"  ok   {artist} — {title}")
            else:
                missing.append(f"{artist} — {title}")
                print(f"  MISS {artist} — {title}")

        name = f"{PREFIX}{src.replace('-', ' ').title()}"
        target = get_or_create_playlist(session, name, pl.get("annotation", "")[:400])
        replace_tracks(target, ids)
        print(f"  -> {name} : {len(ids)}/{len(wanted)} pistes")
        if missing:
            print("  introuvables sur Tidal : " + ", ".join(missing))


if __name__ == "__main__":
    main()