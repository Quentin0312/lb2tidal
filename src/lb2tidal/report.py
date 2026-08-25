"""Run report model and rendering (FR-7, §5.7).

The report is the summary emitted *after* every recommendation has been
processed; logging is the event stream emitted during processing (§5.6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1


class Status:
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    NOT_AVAILABLE = "not-available"
    FAILED = "failed"
    WOULD_CREATE = "would-create"
    WOULD_UPDATE = "would-update"


#: Statuses that mean "this recommendation is fine", for exit-code purposes (§6.4).
SUCCESSFUL = frozenset(
    {
        Status.CREATED,
        Status.UPDATED,
        Status.UNCHANGED,
        Status.SKIPPED,
        Status.NOT_AVAILABLE,
        Status.WOULD_CREATE,
        Status.WOULD_UPDATE,
    }
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Entry:
    name: str
    status: str
    playlist_title: str = ""
    target: str = ""
    requested: int = 0
    matched: int = 0
    missed: int = 0
    misses: list[tuple[str, str]] = field(default_factory=list)
    error: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "status": self.status}
        if self.playlist_title:
            data["playlist_title"] = self.playlist_title
        if self.target:
            data["target"] = self.target
        if self.status == Status.FAILED:
            data["error"] = self.error
        elif self.status in (Status.SKIPPED, Status.NOT_AVAILABLE):
            data["detail"] = self.detail
        else:
            data["requested"] = self.requested
            data["matched"] = self.matched
            data["missed"] = self.missed
            data["misses"] = [{"artist": a, "title": t} for a, t in self.misses]
        return data


@dataclass
class Report:
    started_at: str = field(default_factory=_now)
    finished_at: str = ""
    exit_code: int = 0
    entries: list[Entry] = field(default_factory=list)

    def add(self, entry: Entry) -> None:
        self.entries.append(entry)

    def finish(self, exit_code: int) -> None:
        self.finished_at = _now()
        self.exit_code = exit_code

    @property
    def failures(self) -> int:
        return sum(1 for e in self.entries if e.status == Status.FAILED)

    def render_json(self) -> str:
        return json.dumps(
            {
                "version": SCHEMA_VERSION,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "exit_code": self.exit_code,
                "recommendations": [e.as_dict() for e in self.entries],
            },
            indent=2,
            ensure_ascii=False,
        )

    def render_text(self) -> str:
        if not self.entries:
            return "no recommendations processed"

        lines: list[str] = []
        for entry in self.entries:
            header = f"=== {entry.name}"
            if entry.playlist_title:
                header += f" — {entry.playlist_title}"
            lines.append(header)

            if entry.status == Status.FAILED:
                lines.append(f"    failed — {entry.error}")
                continue
            if entry.status in (Status.SKIPPED, Status.NOT_AVAILABLE):
                lines.append(f"    {entry.status} — {entry.detail}")
                continue

            lines.append(
                f"    {entry.requested} requested · "
                f"{entry.matched} matched · {entry.missed} missed"
            )
            if entry.status == Status.UNCHANGED:
                lines.append("    playlist already up to date")
            else:
                lines.append(f"    playlist {entry.status}: {entry.target}")
            if entry.misses:
                lines.append("    misses:")
                lines.extend(f"      {artist} — {title}" for artist, title in entry.misses)
        return "\n".join(lines)
