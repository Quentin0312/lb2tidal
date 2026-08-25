"""Argument parsing and exit-code mapping (§6). No business logic lives here."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, sync, tidal
from .config import Config, load
from .errors import AuthError, ConfigError
from .report import Report
from .state import State

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CONFIG = 2
EXIT_AUTH = 3
EXIT_ALL_FAILED = 4
EXIT_INTERRUPTED = 130


def _setup_logging(level: str, timestamps: bool) -> None:
    """Level-prefixed lines on stderr. journald adds its own timestamps."""
    fmt = "%(levelname)-7s %(message)s"
    if timestamps:
        fmt = "%(asctime)s " + fmt
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


COMMANDS = ("login", "sync", "status")


def _common_options() -> argparse.ArgumentParser:
    """Flags accepted both before and after the subcommand."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="PATH", help="path to config.toml")
    common.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        help="override run.log_level",
    )
    common.add_argument(
        "--timestamps", action="store_true", help="prefix log lines with a timestamp"
    )
    return common


def _build_parser() -> argparse.ArgumentParser:
    common = _common_options()
    parser = argparse.ArgumentParser(
        prog="lb2tidal",
        description="Mirror ListenBrainz recommendation playlists into Tidal.",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"lb2tidal {__version__}")

    commands = parser.add_subparsers(dest="command")

    login = commands.add_parser(
        "login", parents=[common], help="authorise this machine against Tidal"
    )
    login.add_argument(
        "--force", action="store_true", help="replace an existing valid session"
    )

    sync_cmd = commands.add_parser(
        "sync", parents=[common], help="mirror playlists (default command)"
    )
    sync_cmd.add_argument(
        "--dry-run", action="store_true", help="resolve and report, write nothing"
    )
    sync_cmd.add_argument(
        "--recommendation",
        action="append",
        metavar="NAME",
        help="sync only this recommendation; repeatable",
    )
    sync_cmd.add_argument(
        "--force", action="store_true", help="ignore run state and re-sync everything"
    )
    sync_cmd.add_argument("--json", action="store_true", help="emit the report as JSON")

    commands.add_parser(
        "status", parents=[common], help="show configuration and session state"
    )
    return parser


def _exit_code(report: Report) -> int:
    if not report.entries:
        return EXIT_OK
    failures = report.failures
    if failures == 0:
        return EXIT_OK
    return EXIT_ALL_FAILED if failures == len(report.entries) else EXIT_PARTIAL


def _cmd_sync(args: argparse.Namespace, config: Config) -> int:
    report = sync.run(
        config,
        dry_run=args.dry_run,
        force=args.force,
        only=args.recommendation,
    )
    report.finish(_exit_code(report))
    print(report.render_json() if args.json else report.render_text())
    return report.exit_code


def _cmd_login(args: argparse.Namespace, config: Config) -> int:
    tidal.login(config.tidal.session_file, force=args.force)
    print("Logged in. Session stored at", config.tidal.session_file)
    return EXIT_OK


def _cmd_status(config: Config) -> int:
    lb = config.listenbrainz
    print(f"listenbrainz.user     {lb.user}")
    print(f"listenbrainz.token    {'set' if lb.token else 'not set'}")
    print(f"recommendations       {', '.join(lb.recommendations)}")
    print(f"tidal.prefix          {config.tidal.prefix!r}")
    print(f"tidal.session_file    {config.tidal.session_file}")
    print(f"state_file            {config.state_file}")
    print(
        f"matching              threshold={config.matching.threshold} "
        f"artist_weight={config.matching.artist_weight} "
        f"search_limit={config.matching.search_limit}"
    )

    state = State(config.state_file)
    print("\nlast successful sync")
    for name in lb.recommendations:
        when = state.synced_at(name)
        print(f"  {name:24} {when or 'never'}")

    print()
    try:
        tidal.load_session(config.tidal.session_file)
    except AuthError as exc:
        print(f"tidal session         INVALID — {exc}")
        return EXIT_AUTH
    print("tidal session         valid")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # `sync` is the default command, so a bare `lb2tidal` (or `lb2tidal --dry-run`)
    # is rewritten to the explicit form before parsing. Top-level flags that must
    # reach the root parser are left alone.
    passthrough = {"--help", "-h", "--version"}
    if not any(token in COMMANDS or token in passthrough for token in raw):
        raw.insert(0, "sync")

    parser = _build_parser()
    args = parser.parse_args(raw)
    command = args.command or "sync"

    try:
        config, warnings = load(Path(args.config) if args.config else None)
        _setup_logging(args.log_level or config.run.log_level, args.timestamps)
        for message in warnings:
            logging.warning(message)

        if command == "login":
            return _cmd_login(args, config)
        if command == "status":
            return _cmd_status(config)
        return _cmd_sync(args, config)

    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except AuthError as exc:
        print(f"authentication error: {exc}", file=sys.stderr)
        return EXIT_AUTH
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
