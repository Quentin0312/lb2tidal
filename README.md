# lb2tidal

Mirror your [ListenBrainz](https://listenbrainz.org) recommendation playlists
into [Tidal](https://tidal.com), so the playlists ListenBrainz generates for you
— *Weekly Jams*, *Weekly Exploration*, *Daily Jams* — become playable in any
Tidal client.

One-way and idempotent: ListenBrainz is the source of truth, Tidal is a
rendering target. Running it twice with nothing new upstream changes nothing.

## How it works

For each configured recommendation, `lb2tidal` fetches the latest playlist from
ListenBrainz, resolves every `(artist, title)` pair to a Tidal track by search
and fuzzy matching, and mirrors the result into a playlist named
`LB · Weekly Jams` (prefix configurable).

Tracks Tidal does not have are reported as misses rather than silently dropped.

## Requirements

- Python 3.11 or newer
- A ListenBrainz account with recommendations enabled
- A Tidal account

## Install

```sh
pipx install git+https://github.com/Quentin0312/lb2tidal
```

On Debian 13 and other PEP 668 systems, `pipx` avoids the externally-managed
environment error you would hit with a bare `pip install`. A plain virtualenv
works just as well.

## Configure

Create `~/.config/lb2tidal/config.toml`:

```toml
[listenbrainz]
user            = "your-listenbrainz-username"   # required
recommendations = ["weekly-jams", "weekly-exploration"]

[tidal]
prefix = "LB · "
```

Every value has a default except `listenbrainz.user`. See
[`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) §5.1 for the full set,
including `matching.threshold` if you want to tune how strict track matching is.

ListenBrainz only generates the recommendations it has enough listening history
for. A configured recommendation your account does not have is reported as
`not-available`, not as an error.

## First run

```sh
lb2tidal login          # prints a link.tidal.com URL — open it on any device
lb2tidal status         # confirm the session is valid
lb2tidal sync --dry-run # see what would be matched, without writing anything
lb2tidal sync
```

`login` uses the OAuth device flow, so it works over SSH with no browser on the
machine. The session is saved to `~/.local/state/lb2tidal/tidal.json` with mode
`0600` — it holds a refresh token granting full account access, so keep it that
way.

## Run it on a schedule

```sh
mkdir -p ~/.config/systemd/user
cp systemd/lb2tidal.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now lb2tidal.timer

sudo loginctl enable-linger "$USER"   # so the timer runs without an active login
journalctl --user -u lb2tidal -f
```

The timer runs daily at 05:30 with a random delay of up to 30 minutes.

## Usage

```
lb2tidal login    [--force]
lb2tidal sync     [--dry-run] [--recommendation NAME] [--force] [--json]
lb2tidal status
```

| Flag | Effect |
|---|---|
| `--dry-run` | Resolve and report, write nothing to Tidal |
| `--recommendation NAME` | Sync only this one; repeatable |
| `--force` | Re-sync even if the source playlist has not changed |
| `--json` | Emit the run report as JSON on stdout (logs go to stderr) |

Exit codes: `0` success, `1` partial failure, `2` configuration error,
`3` authentication problem, `4` everything failed.

## Known limitations

- **The playlist is briefly empty during an update.** Tidal offers no atomic
  replace, so contents are cleared before being rewritten.
- **Editing a mirrored playlist by hand does not stick.** The next sync that
  sees a new upstream playlist overwrites it. Use `--force` to repair a playlist
  you deleted or edited.
- **Matching is fuzzy.** Defaults are inherited from a prototype and not yet
  calibrated; check `--dry-run` output before trusting it blindly.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest
```

[`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) is the reference for intended
behaviour and carries the rationale behind the design decisions.

## License

MIT — see [LICENSE](LICENSE).
