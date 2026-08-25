"""Run state: the last successfully synced playlist MBID per recommendation (§5.3).

If ListenBrainz has not issued a new playlist since the last successful sync,
nothing upstream changed and the recommendation is skipped without a Tidal call.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

VERSION = 1


class State:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # State is an optimisation: a corrupt file costs one redundant sync.
            log.warning("%s: unreadable, ignoring (%s)", self.path, exc)
            return
        if data.get("version") != VERSION:
            log.warning(
                "%s: version %s is not %d, ignoring", self.path, data.get("version"), VERSION
            )
            return
        entries = data.get("recommendations")
        if isinstance(entries, dict):
            self._entries = entries

    def unchanged(self, recommendation: str, mbid: str) -> bool:
        return self._entries.get(recommendation, {}).get("mbid") == mbid

    def synced_at(self, recommendation: str) -> str:
        return self._entries.get(recommendation, {}).get("synced_at", "")

    def record(self, recommendation: str, mbid: str) -> None:
        """Remember a successful sync. Called only after the mirror succeeded."""
        self._entries[recommendation] = {
            "mbid": mbid,
            "synced_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._save()

    def _save(self) -> None:
        payload = {"version": VERSION, "recommendations": self._entries}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            temp.replace(self.path)  # atomic, so a crash cannot truncate the state
        except OSError as exc:
            log.warning("%s: could not be written (%s)", self.path, exc)
