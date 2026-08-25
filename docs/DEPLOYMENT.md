# Operating lb2tidal on the VPS

Reference card for the Debian 13 host. For *why* things work this way, see
[SPECIFICATION.md](SPECIFICATION.md).

## Where everything lives

| Path | Contents | Secret? |
|---|---|---|
| `~/.config/lb2tidal/config.toml` | configuration | no |
| `~/.local/state/lb2tidal/tidal.json` | OAuth session | **yes — 0600, full account access** |
| `~/.local/state/lb2tidal/state.json` | last synced MBID per recommendation | no |
| `~/.config/systemd/user/lb2tidal.{service,timer}` | schedule | no |
| `~/.local/bin/lb2tidal` | the executable (pipx) | no |

Logs go to journald, not to a file.

## Routine checks

```sh
lb2tidal status                              # config, session validity, last sync
systemctl --user list-timers lb2tidal.timer  # next run
journalctl --user -u lb2tidal -n 50 --no-pager
journalctl --user -u lb2tidal --since '1 week ago' | grep -E 'ERROR|WARNING|failed'
```

A healthy day looks like `skipped — source playlist unchanged`. Real work only
happens when ListenBrainz issues a new playlist — weekly on Mondays, plus daily
if the account ever gets `daily-jams`.

## Diagnosing

| Symptom | Cause | Fix |
|---|---|---|
| Timer never fires | lingering off — the user session dies on logout | `sudo loginctl enable-linger $USER` |
| `command not found` | `~/.local/bin` off `PATH` | `pipx ensurepath` then a new shell. The unit uses an absolute path and is unaffected |
| Exit 3, "session expired" | refresh token no longer valid | `lb2tidal login` again on the host |
| Exit 2 | config error — the message names the key | fix `config.toml` |
| Exit 1 or 4 | one or all recommendations failed | read journald; usually a Tidal outage, retried next day |
| `not-available` | ListenBrainz has not generated that recommendation for the account | not an error. Remove it from `recommendations` to silence it |
| Many misses appear | Tidal catalogue changed, or matching regressed | run `lb2tidal sync --dry-run` by hand and inspect |
| Playlist looks empty | a run died between `clear()` and `add()` | `lb2tidal sync --force` |

Exit codes in full: §6.4 of the specification.

## Common operations

**Force a run now**
```sh
systemctl --user start lb2tidal.service
```

**Re-sync even if nothing changed upstream** — needed after editing or deleting
a mirrored playlist by hand, since the state only tracks the ListenBrainz side.
```sh
lb2tidal sync --force
```

**Update to a new version**
```sh
pipx upgrade lb2tidal            # or: pipx install --force git+https://github.com/Quentin0312/lb2tidal
lb2tidal --version
systemctl --user start lb2tidal.service   # smoke test inside the sandbox
```
Unit files are not shipped by pipx. If they changed upstream, rewrite them by
hand (see the README) and `systemctl --user daemon-reload`.

**Change the schedule**
```sh
systemctl --user edit lb2tidal.timer   # override OnCalendar
systemctl --user daemon-reload && systemctl --user restart lb2tidal.timer
```
The host runs on UTC: `05:30` is 07:30 Paris time in summer.

**Reset the state** — costs one redundant sync, nothing more.
```sh
rm ~/.local/state/lb2tidal/state.json
```

**Uninstall**
```sh
systemctl --user disable --now lb2tidal.timer
rm ~/.config/systemd/user/lb2tidal.{service,timer}
systemctl --user daemon-reload
pipx uninstall lb2tidal
rm -rf ~/.config/lb2tidal ~/.local/state/lb2tidal   # includes the OAuth session
```

## Do not

- **Copy `tidal.json` between machines.** Run `lb2tidal login` on each host.
  Copying `state.json` is fine — it holds only public MBIDs.
- **Loosen `RestrictAddressFamilies`** below `AF_UNIX AF_INET AF_INET6`. `AF_UNIX`
  is what lets NSS reach `systemd-resolved`; without it DNS fails inside the
  sandbox.
- **Edit a mirrored playlist in Tidal** and expect it to stick. The next upstream
  change overwrites it.
