# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Initial package: `login`, `sync` and `status` commands.
- TOML configuration with environment-variable and CLI overrides (§5.1).
- Run state so unchanged recommendations are skipped without Tidal calls (§5.3).
- Bounded retries and a per-recommendation circuit breaker (§5.5).
- Text and JSON run reports (§5.7).
- systemd user service and timer.

- `docs/DEPLOYMENT.md`: operating and troubleshooting reference for the VPS.

### Changed

- Replaced the single-file prototype with a `src/` package.
- Matching: artist similarity now treats a contained word set as identical, so
  a dropped collaborator no longer scores like an unrelated artist. Threshold
  raised from 0.62 to 0.80.
- Service sandbox allows `AF_UNIX`, without which DNS fails under systemd.
