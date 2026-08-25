"""Configuration loading, merging and validation (§5.1).

Three layers, later overriding earlier: config file, environment, CLI flags.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError

#: Recommendation algorithms ListenBrainz is known to generate. A name outside
#: this set is a typo and fails validation, rather than silently resolving to
#: ``not-available`` at runtime (FR-1).
KNOWN_RECOMMENDATIONS: frozenset[str] = frozenset(
    {
        "weekly-jams",
        "weekly-exploration",
        "daily-jams",
        "top-discoveries-for-year",
        "top-missed-recordings-for-year",
    }
)

DEFAULT_RECOMMENDATIONS: tuple[str, ...] = ("weekly-jams", "weekly-exploration")
LOG_LEVELS: frozenset[str] = frozenset({"debug", "info", "warning", "error"})

#: Deprecated bare names inherited from the prototype, removed in v2.0.
LEGACY_ENV: dict[str, str] = {
    "LB_USER": "LB2TIDAL_LB_USER",
    "LB_TOKEN": "LB2TIDAL_LB_TOKEN",
    "LB_SOURCES": "LB2TIDAL_LB_RECOMMENDATIONS",
    "TIDAL_SESSION": "LB2TIDAL_TIDAL_SESSION",
    "PREFIX": "LB2TIDAL_PREFIX",
}


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


def default_config_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "lb2tidal" / "config.toml"


def default_state_path() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "lb2tidal" / "state.json"


def default_session_path() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "lb2tidal" / "tidal.json"


@dataclass
class ListenBrainzConfig:
    user: str = ""
    token: str = ""
    recommendations: list[str] = field(default_factory=lambda: list(DEFAULT_RECOMMENDATIONS))


@dataclass
class TidalConfig:
    session_file: Path = field(default_factory=default_session_path)
    prefix: str = "LB · "


@dataclass
class MatchingConfig:
    threshold: float = 0.80
    artist_weight: float = 0.4
    search_limit: int = 15


@dataclass
class RunConfig:
    log_level: str = "info"


@dataclass
class Config:
    listenbrainz: ListenBrainzConfig = field(default_factory=ListenBrainzConfig)
    tidal: TidalConfig = field(default_factory=TidalConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    run: RunConfig = field(default_factory=RunConfig)
    state_file: Path = field(default_factory=default_state_path)


_SCHEMA: dict[str, set[str]] = {
    "listenbrainz": {"user", "token", "recommendations"},
    "tidal": {"session_file", "prefix"},
    "matching": {"threshold", "artist_weight", "search_limit"},
    "run": {"log_level"},
}


def _read_file(path: Path) -> dict[str, Any]:
    """Parse the TOML config, rejecting unknown sections and keys outright."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: cannot be read: {exc}") from exc

    for section, values in data.items():
        if section not in _SCHEMA:
            raise ConfigError(f"{path}: unknown section [{section}]")
        if not isinstance(values, dict):
            raise ConfigError(f"{path}: [{section}] must be a table")
        for key in values:
            if key not in _SCHEMA[section]:
                raise ConfigError(f"{path}: unknown key '{key}' in [{section}]")
    return data


def _split_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _apply_env(config: Config, warn: list[str]) -> None:
    for legacy, current in LEGACY_ENV.items():
        if legacy in os.environ and current not in os.environ:
            os.environ[current] = os.environ[legacy]
            warn.append(f"{legacy} is deprecated, use {current} (removed in v2.0)")

    if value := os.environ.get("LB2TIDAL_LB_USER"):
        config.listenbrainz.user = value
    if value := os.environ.get("LB2TIDAL_LB_TOKEN"):
        config.listenbrainz.token = value
    if value := os.environ.get("LB2TIDAL_LB_RECOMMENDATIONS"):
        config.listenbrainz.recommendations = _split_list(value)
    if value := os.environ.get("LB2TIDAL_TIDAL_SESSION"):
        config.tidal.session_file = Path(value).expanduser()
    if value := os.environ.get("LB2TIDAL_PREFIX"):
        config.tidal.prefix = value
    if value := os.environ.get("LB2TIDAL_LOG_LEVEL"):
        config.run.log_level = value.lower()


def _apply_file(config: Config, data: dict[str, Any]) -> None:
    lb = data.get("listenbrainz", {})
    config.listenbrainz.user = lb.get("user", config.listenbrainz.user)
    config.listenbrainz.token = lb.get("token", config.listenbrainz.token)
    if "recommendations" in lb:
        config.listenbrainz.recommendations = lb["recommendations"]

    tidal = data.get("tidal", {})
    if "session_file" in tidal:
        config.tidal.session_file = Path(str(tidal["session_file"])).expanduser()
    config.tidal.prefix = tidal.get("prefix", config.tidal.prefix)

    matching = data.get("matching", {})
    config.matching.threshold = matching.get("threshold", config.matching.threshold)
    config.matching.artist_weight = matching.get("artist_weight", config.matching.artist_weight)
    config.matching.search_limit = matching.get("search_limit", config.matching.search_limit)

    run = data.get("run", {})
    config.run.log_level = str(run.get("log_level", config.run.log_level)).lower()


def _validate(config: Config) -> None:
    lb = config.listenbrainz
    if not lb.user:
        raise ConfigError(
            "listenbrainz.user is not set "
            "(config file, or LB2TIDAL_LB_USER in the environment)"
        )

    if not isinstance(lb.recommendations, list) or not lb.recommendations:
        raise ConfigError("listenbrainz.recommendations must be a non-empty list")

    unknown = [name for name in lb.recommendations if name not in KNOWN_RECOMMENDATIONS]
    if unknown:
        known = ", ".join(sorted(KNOWN_RECOMMENDATIONS))
        raise ConfigError(f"unknown recommendation(s): {', '.join(unknown)}. Known: {known}")

    if len(set(lb.recommendations)) != len(lb.recommendations):
        raise ConfigError("listenbrainz.recommendations contains duplicates")

    matching = config.matching
    if not 0.0 <= matching.threshold <= 1.0:
        raise ConfigError(f"matching.threshold must be within [0, 1], got {matching.threshold}")
    if not 0.0 <= matching.artist_weight <= 1.0:
        raise ConfigError(
            f"matching.artist_weight must be within [0, 1], got {matching.artist_weight}"
        )
    if matching.search_limit < 1:
        raise ConfigError(f"matching.search_limit must be >= 1, got {matching.search_limit}")

    if config.run.log_level not in LOG_LEVELS:
        raise ConfigError(
            f"run.log_level must be one of {', '.join(sorted(LOG_LEVELS))}, "
            f"got '{config.run.log_level}'"
        )


def load(path: Path | None = None) -> tuple[Config, list[str]]:
    """Build a validated Config. Returns it alongside any deprecation warnings.

    A missing config file is not an error: the tool then runs from the
    environment alone. An explicitly requested file that is missing *is* one.
    """
    config = Config()
    warn: list[str] = []

    explicit = path is not None
    target = path or default_config_path()
    if target.is_file():
        _apply_file(config, _read_file(target))
    elif explicit:
        raise ConfigError(f"{target}: no such config file")

    _apply_env(config, warn)
    _validate(config)
    return config, warn
