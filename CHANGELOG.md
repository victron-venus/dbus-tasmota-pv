# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.6] - Unreleased

### Changed

- Update the packaging toolchain to setuptools 84.2.1 and the development linter to Ruff 0.17.2, with matching locked dependencies.
- Refresh pinned shared CI workflows and keep the workflow, runtime, and policy references for RC evidence aligned.
- Preserve release publication across transient GitHub metadata delays and upload assets to the already verified release ID.

### Upgrade

Use the existing installation procedure, preserve local configuration, and keep
an accepted package available for rollback. This maintenance release changes
build and release tooling; the application logic, MQTT protocol, and paho-mqtt
runtime dependency remain unchanged. Device acceptance remains a separate step.

### Security

The packaging update raises the setuptools requirement to 84.2.1. This is a
build-tool dependency fix, not a change to runtime authentication or transport.
Keep broker access restricted to trusted producers. Required checks and
source-bound release validation remain enabled.

## [3.1.5] - Unreleased

### Changed

- Update Ruff to 0.17.1 with a matching dependency lock.
- Use native uv dependency updates and the committed lock for local validation.
- Refresh pinned shared CI workflows while retaining source-bound RC fuzzing.

### Upgrade

Use the existing upgrade procedure and preserve configuration and data. This
maintenance release does not change the MQTT protocol or require a migration.

### Security

Keep the MQTT broker access-controlled and restrict telemetry publication to
trusted producers. The development-tool and CI updates do not change network
authentication or transport protection. Existing security checks remain
required before publication.

## [3.1.4] - 2026-10-18

### Changed

- Route Dependabot metadata approval through the trusted default branch while preserving the existing author and review policy.
- Refresh pinned shared CI workflows and their source-bound release validation.

### Upgrade

Use the documented upgrade procedure and preserve local configuration and data. No configuration migration is required. Keep the previous immutable release available for rollback.

### Security

This maintenance release preserves the existing security and release-validation requirements. Publication does not deploy the service or establish physical-device acceptance.

## [3.1.3] - 2026-10-17

### Changed

- Link the maintained source-bound RC fuzzing process and verified results.

### Upgrade

Use the existing installation procedure and preserve local configuration. This documentation maintenance release leaves runtime behavior and configuration unchanged.

### Security

No new runtime vulnerability fix or target-device acceptance is claimed. Existing release, integration and device validation remain required.

## [3.1.2] - 2026-10-14

### Changed

- Validate each public release candidate with bounded, network-isolated fuzz campaigns against its exact source revision.
- Require positive engine execution counts, instrumented production code and validated seed corpora; retain source-bound reports and diagnostic evidence.
- Run deterministic seed and configuration checks in ordinary CI without starting mutation campaigns on betas.

### Upgrade

Use the existing installation procedure, preserve local configuration and keep the previous accepted package for rollback. This maintenance release updates release validation and does not change the application configuration format. Deployment and applicable device or integration acceptance remain separate from publication.

### Security

RC publication rejects absent or invalid source-bound fuzz reports. The fuzz runner bounds corpus paths, file types and size. No application vulnerability or new target-device acceptance is claimed by these tooling changes.

## [3.1.1] - Development line

### Release candidate validation

- Require bounded fuzzing on public release candidates, with source-bound reports and retained diagnostics; beta and ordinary CI do not run mutation campaigns.

### Maintenance

- Clarify telemetry validation, persistent device identity and installer cleanup while preserving the existing 3.1 metering behavior.
- Require complete security scans and publish release notes from the exact reviewed source commit.
- Interpret GitHub response status from authoritative HTTP headers during release publication and keep package, runtime and SetupHelper versions synchronized.

### Upgrade

No new configuration migration is introduced. Retain device-local settings and validate MQTT availability behavior before commissioning. Beta and RC artifacts use this new base version without reusing the existing 3.1.0 release tag; offline checks do not establish hardware acceptance.

### Security

Preserve broker authentication and access controls, and keep device credentials out of committed configuration and logs. The existing telemetry validation and offline invalidation remain in force; release verification requires complete security checks and source-bound notes.

## [3.1.0] - Development line

### Fixed
- Separate telemetry measurement validation from JSON decoding while preserving diagnostics, defaults and ASCII-only persistent identities.
- Require live MQTT telemetry instead of reviving offline power from retained messages; invalidate on LWT Offline.
- Publish measured AC current instead of assuming unity power factor with Power/Voltage.
- Contain malformed and deeply nested JSON and detect a stopped MQTT network worker.
- Retry failed offline invalidation and isolate one device's D-Bus errors from other updates.
- Preserve device identity across discovery-order changes using native localsettings allocation.
- Ship the settings module in every installer/archive, validate staged payloads before stopping the old runtime, and keep installed version metadata in sync.

### Added
- Persist writable custom name, AC position, and phase through Venus OS localsettings.
- Rate-limited parse diagnostics and regression coverage for MQTT, D-Bus, settings, and packaging failures.

### Changed
- Batch D-Bus measurements into ItemsChanged signals using the existing GLib/velib runtime.
- Synchronize candidate versions in the runtime, package metadata, lockfile, and SetupHelper tracking.
- Missing AC current is now unknown rather than a derived estimate. Existing phase L1 / AC input 1 defaults remain; first migration prefers the previous instance when it is free.

### Maintenance

- Record test and build dependencies in `uv.lock` for reproducible Python checks, preserving the existing locked runtime versions.
- Publish reviewed release notes from the exact source commit used to build each candidate, preserving build provenance.
- Document contribution checks, confidential security reporting and the project-specific trust boundaries.
- Require complete Bandit scans with no unresolved findings; reject malformed or incomplete scanner output. Document narrowly reviewed tooling and synthetic-fixture exceptions.

### Upgrade

Missing measured AC current now stays unknown rather than being estimated from Power/Voltage. Confirm the configured phase and AC position; instance migration prefers the previous free instance and preserves identity thereafter. Retain device-local settings and test MQTT availability behavior before commissioning.

### Security

Private vulnerability reporting and response policy are documented in SECURITY.md. This maintenance update strengthens release evidence and review instructions; it does not replace deployment authentication, network isolation or independent equipment safeguards. No new project CVE is announced by these changes.

## [3.0.2] - 2026-09-12

### Fixed
- Register discovered meters and update their D-Bus paths on the GLib thread, coalescing pending MQTT telemetry.
- Reject non-finite power values and invalidate stale current and voltage alongside power.
- Install with platform dependencies, persistent boot restoration and bounded multilog output.
- Preserve service, log and supervisor directory inodes across upgrades and legacy-directory migration.
- Route SetupHelper installation through the native installer instead of its unsupported singular service flag.

## [3.0.1] - 2026-09-12

### Fixed
- Ignore malformed non-object ENERGY telemetry without interrupting MQTT processing.
- Include the complete SetupHelper service tree and checksums in release archives.
- Remove the obsolete --config argument from the packaged MQTT service launcher.

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
