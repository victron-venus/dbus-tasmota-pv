# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-08-21

### Added
- Yesterday's yield (`ENERGY.Yesterday`) is now published on the custom
  D-Bus path `/Energy/Daily/Yesterday` (mirrored to MQTT as
  `N/..._Energy/_Daily/_Yesterday` by mqtt-gateway)

### Changed
- **BREAKING**: devices are auto-discovered via the wildcard MQTT subscription
  `tele/+/SENSOR` — no config file or CLI device list anymore. Any Tasmota
  plug publishing ENERGY telemetry appears as a D-Bus PV inverter on its own.
- `/Serial` is now `TASMOTA-<topic>` (was `TASMOTA-<instance>`); D-Bus
  DeviceInstance is derived deterministically from the topic, so service
  names stay stable across restarts
- `install.sh` removes an obsolete `/data/dbus-tasmota-pv/config.json`

### Removed
- `config.example.json`, `--config` / `--devices` CLI options, and the
  JSON device list (superseded by discovery)

## [2.0.0] - 2026-08-21

### Changed
- **BREAKING**: data acquisition switched from HTTP polling to MQTT subscription
- Devices are now configured as MQTT `TOPIC:INSTANCE` instead of `IP:INSTANCE`
- Plugs publish `tele/<topic>/SENSOR` to the Venus OS broker (FlashMQ, 127.0.0.1:1883)
- Uses preinstalled paho-mqtt (no pip needed on Venus OS)
- Telemetry staleness marks device offline after 90s without messages

### Removed
- HTTP polling client and mDNS/SSDP auto-discovery (`--discover`)

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
