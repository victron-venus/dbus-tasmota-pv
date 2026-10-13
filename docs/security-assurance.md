# Security assurance case

## Claim, architecture and operating assumptions

`dbus-tasmota-pv.py` subscribes to `tele/+/SENSOR` and availability messages through paho-mqtt, validates measurements, then schedules D-Bus changes on the GLib loop. Each discovered device exposes a PV inverter service. `tasmota_settings.py` retains device instance, display name, phase and position through Venus OS localsettings.

The intended guarantee is dependable telemetry projection within a trusted installation. This program does not operate relays, authenticate meter identity, provide billing-grade measurements or replace independent electrical protections. Assets are measurement integrity, persistent device identity, service availability and the host's local bus. Operators control MQTT publication ACLs, local users, network access and installation files.

## Boundaries and evidence

- Incoming JSON must have an ENERGY object with Power. The parser rejects malformed, excessively nested, oversized (over 64 KiB), boolean and nonfinite measurements; negative voltage/current are rejected. Missing current remains unknown rather than a power-factor assumption. [Parser/runtime tests](../tests/test_tasmota.py) cover these paths.
- Retained data does not revive stale devices. Offline messages, the 90-second stale budget, disconnects and a failed MQTT worker invalidate freshness. Failed D-Bus invalidation can be retried; one device failure must not prevent other updates. Tests exercise the software behavior with controlled substitutes for the device bus.
- Settings validate integer ranges, ASCII instance syntax and D-Bus-compatible names. UTF-8 identity bytes are hex-encoded to avoid path collisions. [Settings tests](../tests/test_settings.py) cover independent identities and persistence failures. Writable fields are display/configuration metadata, not physical control.
- Installers and packaging validate staged runtime files before replacing a service. [Installation](../tests/test_installation.py) and [package tests](../tests/test_package.py) run against temporary filesystem/supervisor fixtures. They do not establish a successful physical device upgrade.

## Transport and cryptography

The driver defaults to plaintext MQTT on loopback port 1883 and has no built-in TLS or username/password CLI. A remote `--mqtt-host` therefore requires a separately protected, trusted network or authenticated encrypted tunnel and broker-side publication restrictions. Do not expose this subscription or the D-Bus system bus to an untrusted network. The driver cannot distinguish forged measurements from authorized MQTT publishers. This limitation is explicit; the Silver encrypted-network criterion is not claimed.

The telemetry runtime implements no cryptographic protocol, key generation, password database or certificate verification. The CRC32 used to propose an initial device instance is an identity hint, not a security hash; localsettings arbitrates collisions. Delivery tooling uses Python's standard SHA-256 for integrity and GitHub HTTPS for transport. These checksums are not signatures. No custom cryptography or known-weak algorithm is used for a security decision in the reviewed runtime.

The Python runtime does not include first-party manually managed C/C++ memory. Venus OS D-Bus/GLib, Python and optional package dependencies include native code outside this repository's unit-test scope. Patch them through supported firmware/packages; Python coverage does not establish their memory safety.

## Review results and limits

The complete pinned Bandit gate checks source, tooling and tests and rejects every unresolved warning or scanner error. Its reviewed configuration retains rule-specific explanations for safe fixed-command subprocesses and test assertions. CodeQL and dependency scans complement this; they cannot prove the absence of vulnerabilities. See [dated quality evidence](quality-and-build.md) and [the public assessment receipt](evidence/assessment-2026-10-13.json).

No live meter, MQTT deployment or Venus OS D-Bus was used for these local checks. Reassess this case when external inputs, transport, settings, permissions or packaging change. Remaining release-signature, whole-project coverage and continuity work is tracked in [the roadmap](../ROADMAP.md).
