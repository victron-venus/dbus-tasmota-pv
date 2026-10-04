#!/usr/bin/env python3
"""
dbus-tasmota-pv - Tasmota Energy Meter to D-Bus PV Inverter Bridge
===================================================================

Reads power data that Tasmota smart plugs (with energy monitoring) push to
MQTT and publishes it to Victron D-Bus as PV Inverter devices.

Devices are DISCOVERED automatically: the script subscribes to the
wildcard topic ``tele/+/SENSOR`` on the broker built into Venus OS
(FlashMQ on 127.0.0.1:1883) and registers a D-Bus PV Inverter for every
plug whose first telemetry arrives. No device list is configured anywhere;
a newly added Tasmota plug appears on the D-Bus as soon as it publishes.

Uses paho-mqtt, which ships preinstalled on recent Venus OS images
(no pip needed).

Usage:
    ./dbus-tasmota-pv.py
    ./dbus-tasmota-pv.py --mqtt-host 192.168.160.150
"""

import argparse
import gc
import json
import logging
import math
import signal
import sys
import threading
import zlib
from pathlib import Path
from time import monotonic, time
from typing import Any

from tasmota_settings import TasmotaSettings

# paho-mqtt ships preinstalled on Venus OS 3.x (used by dbus-mqtt-* services).
# Imported lazily-guarded so the module stays importable for tests on hosts
# without paho.
try:
    from paho.mqtt.client import CallbackAPIVersion
    from paho.mqtt.client import Client as MqttClient

    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False
    MqttClient = None  # type: ignore[assignment,misc]
    CallbackAPIVersion = None  # type: ignore[assignment,misc]

# Venus OS path (optional - needed on Venus OS only)
VELIB_PATH = Path("/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")
if VELIB_PATH.exists():
    sys.path.insert(0, str(VELIB_PATH))
    import dbus  # type: ignore[attr-defined]
    from dbus.mainloop.glib import DBusGMainLoop  # type: ignore[attr-defined]
    from gi.repository import GLib  # type: ignore[attr-defined]
    from vedbus import VeDbusService  # type: ignore[attr-defined]
else:
    VeDbusService = None
    dbus = None
    DBusGMainLoop = None
    GLib = None

VERSION = "3.1.0"
STALE_AFTER_SECONDS = 90  # no telemetry for this long -> report offline
TICK_SECONDS = 5  # staleness sweep / heartbeat / GC cadence
GC_INTERVAL_TICKS = 30  # run GC every 30 ticks (~2.5 minutes)
HEARTBEAT_FILE = "/run/dbus-tasmota-pv.alive"
MAX_SENSOR_PAYLOAD_BYTES = 65536
INVALID_LOG_INTERVAL_SECONDS = 60
EnergyReading = tuple[float, float, float | None, float, float, float]

# D-Bus path constants (avoid magic strings)
_PATH_CONNECTED = "/Connected"
_PATH_ERROR_CODE = "/ErrorCode"
_PATH_AC_POWER = "/Ac/Power"
_PATH_AC_L1_POWER = "/Ac/L1/Power"
_PATH_AC_L1_VOLTAGE = "/Ac/L1/Voltage"
_PATH_AC_L1_CURRENT = "/Ac/L1/Current"
_PATH_AC_ENERGY_FORWARD = "/Ac/Energy/Forward"
_PATH_AC_ENERGY_DAILY = "/Ac/Energy/Daily"
# Non-standard extension: yesterday's yield as reported by the Tasmota plug
# (ENERGY.Yesterday). Mirrored to MQTT by mqtt-gateway as N/..._Energy/_Daily/_Yesterday.
_PATH_ENERGY_YESTERDAY = "/Energy/Daily/Yesterday"

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("TasmotaPV")


def parse_energy_payload(
    payload: bytes | str,
) -> EnergyReading | None:
    """Parse a Tasmota ``tele/<topic>/SENSOR`` JSON payload.

    Returns ``(power, voltage, current, total, today, yesterday)`` or ``None``
    when the payload is invalid. Current is the measured RMS current; when
    absent it is unknown, since active power / voltage ignores power factor.
    """
    return _parse_energy_payload(payload)[0]


def _parse_energy_payload(payload: bytes | str) -> tuple[EnergyReading | None, str | None]:
    """Return a reading and a bounded diagnostic without logging raw payloads."""
    if not isinstance(payload, (bytes, str)) or len(payload) > MAX_SENSOR_PAYLOAD_BYTES:
        return None, "invalid payload type or payload exceeds 64 KiB"
    try:
        document = json.loads(payload)
        if not isinstance(document, dict):
            return None, "JSON root is not an object"
        energy = document.get("ENERGY")
        if not isinstance(energy, dict) or "Power" not in energy:
            return None, "missing ENERGY object or Power"
        values = {}
        for field, default in (
            ("Power", None),
            ("Voltage", 115.0),
            ("Total", 0.0),
            ("Today", 0.0),
            ("Yesterday", 0.0),
            ("Current", None),
        ):
            value = energy.get(field, default)
            if field == "Current" and value is None:
                values[field] = None
                continue
            try:
                if isinstance(value, bool):
                    raise TypeError("boolean measurement")
                value = float(value)
                if not math.isfinite(value) or (field in ("Voltage", "Current") and value < 0):
                    raise ValueError("non-finite or negative measurement")
            except (TypeError, ValueError, OverflowError):
                return None, f"invalid ENERGY.{field}"
            values[field] = value
        return (
            values["Power"],
            values["Voltage"],
            values["Current"],
            values["Total"],
            values["Today"],
            values["Yesterday"],
        ), None
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None, "invalid JSON or excessive nesting"


class TasmotaPVInverter:
    """Single Tasmota plug as a PV Inverter on D-Bus, fed by MQTT telemetry."""

    def __init__(self, topic: str, instance: int, *, settings_bus=None, on_instance_change=None):
        self.topic = topic
        self._last_update = monotonic()
        self._connected = False
        self._offline_requested = False
        self._last_reading: EnergyReading | None = None
        self._on_instance_change = on_instance_change
        self._dbusservice = None
        self._settings_bus = settings_bus if settings_bus is not None else dbus.SystemBus()
        self.settings = TasmotaSettings(
            self._settings_bus, topic, instance, on_change=self._setting_changed
        )
        self.instance = self.settings.instance

        # Create a private bus connection for each instance to avoid path conflicts
        self.bus = dbus.SystemBus(private=True)

        service_name = f"com.victronenergy.pvinverter.tasmota_{self.instance}"
        self._dbusservice = VeDbusService(service_name, bus=self.bus, register=False)

        # Mandatory management paths
        self._dbusservice.add_path("/Mgmt/ProcessName", "dbus-tasmota-pv.py")
        self._dbusservice.add_path("/Mgmt/ProcessVersion", VERSION)
        self._dbusservice.add_path("/Mgmt/Connection", f"MQTT tele/{topic}/SENSOR")
        self._dbusservice.add_path("/ProductName", f"Solar Tasmota {topic}")
        self._dbusservice.add_path(
            "/CustomName",
            self.settings.custom_name,
            writeable=True,
            onchangecallback=lambda _path, value: self.settings.set_custom_name(value),
        )
        self._dbusservice.add_path("/Serial", f"TASMOTA-{topic}")
        self._dbusservice.add_path(_PATH_CONNECTED, 0)
        self._dbusservice.add_path("/DeviceInstance", self.instance)
        self._dbusservice.add_path("/ProductId", 0xA144)  # Standard PV Inverter ID
        self._dbusservice.add_path(_PATH_ERROR_CODE, 0)
        self._dbusservice.add_path("/FirmwareVersion", VERSION)

        # Position: 0 = AC Input (Grid side), 1 = AC Output (Load side)
        self._dbusservice.add_path(
            "/Position",
            self.settings.position,
            writeable=True,
            onchangecallback=lambda _path, value: self.settings.set_position(value),
        )
        self._dbusservice.add_path(
            "/PhaseSetting",
            self.settings.phase,
            writeable=True,
            onchangecallback=lambda _path, value: self.settings.set_phase(value),
        )
        self._dbusservice.add_path("/Role", "pvinverter")
        self._dbusservice.add_path("/AllowedRoles", ["pvinverter"])
        self._dbusservice.add_path("/IsGenericEnergyMeter", 1)
        self._dbusservice.add_path("/PositionIsAdjustable", 1)

        # AC Power Paths
        self._dbusservice.add_path(_PATH_AC_POWER, None)
        for phase in (1, 2, 3):
            for measurement in ("Power", "Voltage", "Current"):
                self._dbusservice.add_path(f"/Ac/L{phase}/{measurement}", None)
            self._dbusservice.add_path(f"/Ac/L{phase}/Energy/Forward", None)
        self._dbusservice.add_path(_PATH_AC_ENERGY_FORWARD, 0.0)
        self._dbusservice.add_path(_PATH_AC_ENERGY_DAILY, 0.0)
        self._dbusservice.add_path(_PATH_ENERGY_YESTERDAY, 0.0)

        self._dbusservice.register()
        logger.info(f"Registered PV Inverter: {service_name} (MQTT topic: {topic})")

    def _set_paths(self, values: dict[str, Any]) -> None:
        """Publish one ItemsChanged batch on the GLib thread."""
        with self._dbusservice as service:
            for path, value in values.items():
                service[path] = value

    def _phase_paths(self, power=None, voltage=None, current=None) -> dict[str, Any]:
        values = {}
        for phase in (1, 2, 3):
            for measurement, value in (
                ("Power", power),
                ("Voltage", voltage),
                ("Current", current),
            ):
                values[f"/Ac/L{phase}/{measurement}"] = (
                    value if phase == self.settings.phase else None
                )
        return values

    def _phase_energy_paths(self, total) -> dict[str, Any]:
        return {
            f"/Ac/L{phase}/Energy/Forward": total if phase == self.settings.phase else None
            for phase in (1, 2, 3)
        }

    def _setting_changed(self, field: str, _old, value) -> None:
        if field == "instance":
            if self._on_instance_change is not None:
                self._on_instance_change()
            return
        if self._dbusservice is None:
            return
        path = {"custom_name": "/CustomName", "position": "/Position", "phase": "/PhaseSetting"}[
            field
        ]
        values = {path: value}
        if field == "phase":
            fresh = (
                self._connected
                and not self._offline_requested
                and monotonic() - self._last_update <= STALE_AFTER_SECONDS
            )
            values.update(self._phase_paths(*(self._last_reading[:3] if fresh else ())))
            values.update(
                self._phase_energy_paths(self._last_reading[3] if self._last_reading else None)
            )
        self._set_paths(values)

    def apply(
        self,
        power: float,
        voltage: float,
        current: float | None,
        total: float,
        today: float,
        yesterday: float,
        *,
        received_at: float | None = None,
    ):
        """Push a fresh ENERGY reading onto D-Bus."""
        received_at = monotonic() if received_at is None else received_at
        if monotonic() - received_at > STALE_AFTER_SECONDS:
            self.check_stale()
            return

        # A partially published update must be invalidated by the next tick if
        # writing the remaining paths fails, including the very first update.
        self._offline_requested = True
        self._set_paths(
            {
                _PATH_CONNECTED: 1,
                _PATH_ERROR_CODE: 0,
                _PATH_AC_POWER: power,
                **self._phase_paths(power, voltage, current),
                **self._phase_energy_paths(total),
                _PATH_AC_ENERGY_FORWARD: total,
                _PATH_AC_ENERGY_DAILY: today,
                _PATH_ENERGY_YESTERDAY: yesterday,
            }
        )
        self._last_update = received_at
        self._last_reading = (power, voltage, current, total, today, yesterday)
        self._offline_requested = False
        if not self._connected:
            self._connected = True
            logger.info(f"Tasmota {self.topic} back online")

    def mark_offline(self) -> None:
        """Honor LWT Offline; keep retrying invalidation if a D-Bus write fails."""
        self._offline_requested = True
        self.check_stale()

    def check_stale(self) -> None:
        """Mark the device offline when no telemetry arrived recently."""
        if not self._connected and not self._offline_requested:
            return
        if self._offline_requested or monotonic() - self._last_update > STALE_AFTER_SECONDS:
            self._set_paths(
                {
                    _PATH_ERROR_CODE: 1,  # Offline/comm error
                    _PATH_CONNECTED: 0,
                    _PATH_AC_POWER: None,
                    **self._phase_paths(),
                }
            )
            self._connected = False
            self._offline_requested = False
            logger.warning(
                "Tasmota %s: telemetry stale or LWT Offline, marking offline", self.topic
            )


def topic_from_mqtt_topic(mqtt_topic: str, suffix: str = "SENSOR") -> str | None:
    """Extract the Tasmota topic from a ``tele/<topic>/SENSOR`` MQTT topic.

    Returns ``None`` for anything that does not match the pattern.
    """
    parts = mqtt_topic.split("/")
    if len(parts) == 3 and parts[0] == "tele" and parts[2] == suffix and parts[1]:
        return parts[1]
    return None


def stable_instance(topic: str, used: set[int]) -> int:
    """Choose a legacy-compatible preferred instance for first registration.

    Localsettings persists the final allocation and resolves collisions with
    devices outside this process. Existing persisted allocations take priority.
    """
    instance = zlib.crc32(topic.encode("utf-8")) % 10000
    while instance in used:
        instance = (instance + 1) % 10000
    return instance


class MqttEnergyListener:
    """Discover inverters via the wildcard subscription ``tele/+/SENSOR``.

    Every Tasmota plug that publishes an ENERGY telemetry payload is picked
    up on its first message and registered as a D-Bus PV Inverter — no
    configuration needed.
    """

    DISCOVERY_FILTER = "tele/+/SENSOR"
    LWT_FILTER = "tele/+/LWT"

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._inverters: dict[str, TasmotaPVInverter] = {}
        # _on_message runs on the paho network thread while tick() iterates
        # the registry on the GLib thread; guard both sides.
        self._lock = threading.Lock()
        self._pending = {}
        self._pending_scheduled = False
        self._invalid_logs = {}
        self._started = False
        self.failure_reason = None
        self._settings_bus = None
        self._client = MqttClient(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id="dbus-tasmota-pv",
        )
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.enable_logger(logger)
        # A callback fault must not silently kill paho's only network worker.
        self._client.suppress_exceptions = True
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def inverters(self) -> list[TasmotaPVInverter]:
        """Snapshot of currently discovered inverters (thread-safe)."""
        with self._lock:
            return list(self._inverters.values())

    def start(self) -> None:
        """Connect asynchronously and start the network thread (auto-reconnect)."""
        self._client.connect_async(self._host, self._port, keepalive=60)
        result = self._client.loop_start()
        if result != 0:
            raise RuntimeError(f"Could not start MQTT worker: {result}")
        self._started = True

    def stop(self) -> None:
        """Stop the network thread and disconnect."""
        self._started = False
        self._client.disconnect()
        self._client.loop_stop()

    def healthy(self) -> bool:
        """Check the worker itself; an absent broker is handled by reconnect."""
        if self._started:
            worker = self._client._thread  # paho exposes no public worker health method
            if worker is None or not worker.is_alive():
                self.failure_reason = "MQTT network worker stopped unexpectedly"
        return self.failure_reason is None

    def _instance_changed(self) -> None:
        self.failure_reason = "Device instance changed; restarting D-Bus services"

    def _get_or_create(self, topic: str) -> TasmotaPVInverter | None:
        """Return the inverter for ``topic``, registering it on first sight."""
        with self._lock:
            existing = self._inverters.get(topic)
        if existing is not None:
            return existing
        if self.failure_reason is not None:
            return None
        try:
            with self._lock:
                # Re-check under the lock: another message may have created it.
                existing = self._inverters.get(topic)
                if existing is not None:
                    return existing
                used = {inv.instance for inv in self._inverters.values()}
                if self._settings_bus is None:
                    self._settings_bus = dbus.SystemBus()
                inverter = TasmotaPVInverter(
                    topic,
                    stable_instance(topic, used),
                    settings_bus=self._settings_bus,
                    on_instance_change=self._instance_changed,
                )
                self._inverters[topic] = inverter
                return inverter
        except Exception:
            logger.exception(f"Failed to register discovered device '{topic}'")
            # SettingsDevice has process-global signal trackers. Recreating
            # the same paths after partial construction can lose watchers when
            # the old object is collected. Let the supervisor start cleanly.
            self.failure_reason = f"Failed to register Tasmota {topic}; restarting safely"
            return None

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        # paho v2 hands us a ReasonCode object; guard is_failure for robustness
        if getattr(reason_code, "is_failure", False):
            logger.error(f"MQTT connect to {self._host}:{self._port} failed: {reason_code}")
            return
        logger.info(
            f"Connected to MQTT broker {self._host}:{self._port}, "
            f"discovering devices via '{self.DISCOVERY_FILTER}'"
        )
        result, _mid = client.subscribe([(self.DISCOVERY_FILTER, 0), (self.LWT_FILTER, 0)])
        if result != 0:
            self.failure_reason = f"Could not subscribe to MQTT telemetry: {result}"

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        logger.warning(f"MQTT disconnected ({reason_code}); auto-reconnect in progress")

    def _on_message(self, client, userdata, msg):
        try:
            self._process_message(msg)
        except Exception:
            logger.exception("Failed to process MQTT message; continuing with the next message")

    def _process_message(self, msg):
        received_at = monotonic()
        lwt_topic = topic_from_mqtt_topic(msg.topic, "LWT")
        if lwt_topic is not None:
            # Online (including retained Online) never makes a reading fresh.
            if msg.payload == b"Offline":
                self._queue(lwt_topic, None, received_at)
            return
        topic = topic_from_mqtt_topic(msg.topic)
        if topic is None:
            logger.debug(f"Ignoring message on unexpected topic: {msg.topic}")
            return
        # A broker's cache may be hours old and has no trustworthy monotonic
        # age. Only a live publish can register/revive an inverter.
        if msg.retain:
            return
        parsed, reason = _parse_energy_payload(msg.payload)
        if parsed is None:
            # Non-energy plugs also publish tele/+/SENSOR; only complain for
            # devices we already know should carry ENERGY data.
            with self._lock:
                known = topic in self._inverters
            if not known:
                logger.debug("Tasmota %s: ignored SENSOR (%s)", topic, reason)
                return
            last_log, suppressed = self._invalid_logs.get(topic, (-math.inf, 0))
            if received_at - last_log >= INVALID_LOG_INTERVAL_SECONDS:
                logger.warning(
                    "Tasmota %s: invalid SENSOR (%s); %d invalid messages suppressed",
                    topic,
                    reason,
                    suppressed,
                )
                self._invalid_logs[topic] = (received_at, 0)
            else:
                self._invalid_logs[topic] = (last_log, suppressed + 1)
            return
        self._queue(topic, parsed, received_at)

    def _queue(self, topic: str, parsed: EnergyReading | None, received_at: float) -> None:
        # Registration and path writes both belong to GLib, not paho's
        # network thread. Coalesce bursts to one latest reading per device.
        with self._lock:
            self._pending[topic] = (parsed, received_at)
            if self._pending_scheduled:
                return
            self._pending_scheduled = True
        try:
            GLib.idle_add(self._apply_pending)
        except Exception:
            with self._lock:
                self._pending_scheduled = False
            raise

    def _apply_pending(self) -> bool:
        with self._lock:
            pending = self._pending
            self._pending = {}
            self._pending_scheduled = False
        for topic, (parsed, received_at) in pending.items():
            try:
                with self._lock:
                    # A newer event (notably LWT Offline) supersedes this batch.
                    if topic in self._pending:
                        continue
                    inverter = self._inverters.get(topic)
                if parsed is None:
                    if inverter is not None:
                        inverter.mark_offline()
                    continue
                if monotonic() - received_at > STALE_AFTER_SECONDS:
                    continue
                inverter = self._get_or_create(topic)
                if inverter is not None:
                    inverter.apply(*parsed, received_at=received_at)
            except Exception:
                logger.exception("Failed to update Tasmota %s; other devices will continue", topic)
        return False


def _write_heartbeat(heartbeat_file: str) -> None:
    """Write the current timestamp to the heartbeat file (blocking I/O)."""
    try:
        with open(heartbeat_file, "w", encoding="utf-8") as f:
            f.write(str(int(time())))
    except OSError:
        # Intentionally ignored: failed heartbeat write should not crash the service
        pass


def _make_tick(listener: MqttEnergyListener, heartbeat_file: str, on_fatal=None):
    """Build the periodic tick callback (staleness, GC, heartbeat)."""
    state = {"gc_counter": 0}

    def tick() -> bool:
        """Periodic housekeeping; returning True keeps the GLib timer alive."""
        if not listener.healthy():
            logger.critical("%s", listener.failure_reason)
            if on_fatal is not None:
                on_fatal()
            return False
        for inv in listener.inverters():
            try:
                inv.check_stale()
            except Exception:
                logger.exception("Error checking staleness of %s", inv.topic)

        # Periodic garbage collection
        state["gc_counter"] += 1
        if state["gc_counter"] >= GC_INTERVAL_TICKS:
            state["gc_counter"] = 0
            gc.collect()

        _write_heartbeat(heartbeat_file)
        return True

    return tick


def _register_signal_handlers(mainloop) -> None:
    """Register SIGTERM/SIGINT handlers for graceful shutdown."""

    def graceful_shutdown(signum, frame):
        """Handle shutdown signals gracefully"""
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info(f"Received {sig_name}, shutting down gracefully...")
        mainloop.quit()

    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)


def _parse_args() -> argparse.Namespace:
    """Build the argument parser and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Tasmota Energy Meter (MQTT) to D-Bus PV Inverter Bridge — "
            "devices are auto-discovered via tele/+/SENSOR"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    ./dbus-tasmota-pv.py
    ./dbus-tasmota-pv.py --mqtt-host 192.168.160.150
        """,
    )
    parser.add_argument(
        "--mqtt-host",
        default="127.0.0.1",
        help="MQTT broker host (default: 127.0.0.1, the Venus OS broker)",
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=1883,
        help="MQTT broker port (default: 1883)",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    if not PAHO_AVAILABLE:
        logger.error("paho-mqtt is required (preinstalled on Venus OS 3.x); cannot continue")
        sys.exit(1)

    # Setup D-Bus main loop
    DBusGMainLoop(set_as_default=True)
    mainloop = GLib.MainLoop()

    _register_signal_handlers(mainloop)

    # Inverters register themselves as telemetry arrives; nothing pre-created.
    listener = MqttEnergyListener(args.mqtt_host, args.mqtt_port)
    GLib.timeout_add_seconds(TICK_SECONDS, _make_tick(listener, HEARTBEAT_FILE, mainloop.quit))

    logger.info(
        f"=== dbus-tasmota-pv v{VERSION}: MQTT discovery on "
        f"{args.mqtt_host}:{args.mqtt_port} ({listener.DISCOVERY_FILTER}) ==="
    )
    listener.start()
    try:
        mainloop.run()
    finally:
        logger.info("Cleaning up...")
        listener.stop()
        gc.collect()
        logger.info("Shutdown complete")
    if listener.failure_reason is not None:
        sys.exit(1)


if __name__ == "__main__":
    main()
