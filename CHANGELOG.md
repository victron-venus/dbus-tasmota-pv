# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.1] - 2026-03-29

### Added
- `commit.sh` and `release.sh` helper scripts
- Additional badges in README

## [1.2.0] - 2026-03-28

### Added
- HTTP session pooling with connection reuse
- Graceful shutdown handling (SIGTERM, SIGINT)
- Periodic garbage collection
- Connection health monitoring
- Consecutive failure tracking

### Changed
- Command-line arguments for device configuration
- Improved error handling and logging
- Better 24/7 reliability

## [1.1.0] - 2026-03-26

### Added
- Support for multiple Tasmota devices
- Device instance configuration

### Changed
- Improved polling reliability

## [1.0.0] - 2026-03-25

### Added
- Initial release
- Tasmota HTTP polling
- D-Bus PV inverter registration
- Power, voltage, current reporting
- Energy total tracking

[1.2.1]: https://github.com/victron-venus/dbus-tasmota-pv/releases/tag/v1.2.1
[1.2.0]: https://github.com/victron-venus/dbus-tasmota-pv/releases/tag/v1.2.0
[1.1.0]: https://github.com/victron-venus/dbus-tasmota-pv/releases/tag/v1.1.0
[1.0.0]: https://github.com/victron-venus/dbus-tasmota-pv/releases/tag/v1.0.0
