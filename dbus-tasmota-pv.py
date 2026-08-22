#!/usr/bin/env python3
"""
dbus-tasmota-pv - Tasmota Energy Meter to D-Bus PV Inverter Bridge
===================================================================

Reads power data that Tasmota smart plugs (with energy monitoring) push to
MQTT (``tele/<topic>/SENSOR``) and publishes it to Victron D-Bus as PV
Inverter devices.

The plugs publish to the broker built into Venus OS (FlashMQ on
127.0.0.1:1883); no HTTP polling is involved. Uses paho-mqtt, which ships
preinstalled on recent Venus OS images (no pip needed).

Usage:
    ./dbus-tasmota-pv.py --config /etc/dbus-tasmota-pv.json
    ./dbus-tasmota-pv.py --devices tasmota_120:120 tasmota_121:121
    ./dbus-tasmota-pv.py --mqtt-host 192.168.160.150 --devices tasmota_120:120

Where each device is TOPIC:INSTANCE and the plug publishes tele/TOPIC/SENSOR.
"""

import argparse
import gc
import json
import logging
import signal
import sys
from pathlib import Path
from time import time
from typing import Any

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

VERSION = "2.0.0"
STALE_AFTER_SECONDS = 90  # no telemetry for this long -> report offline
TICK_SECONDS = 5  # staleness sweep / heartbeat / GC cadence
GC_INTERVAL_TICKS = 30  # run GC every 30 ticks (~2.5 minutes)
HEARTBEAT_FILE = "/run/dbus-tasmota-pv.alive"

# D-Bus path constants (avoid magic strings)
_PATH_CONNECTED = "/Connected"
_PATH_ERROR_CODE = "/ErrorCode"
_PATH_AC_POWER = "/Ac/Power"
_PATH_AC_L1_POWER = "/Ac/L1/Power"
_PATH_AC_L1_VOLTAGE = "/Ac/L1/Voltage"
_PATH_AC_L1_CURRENT = "/Ac/L1/Current"
_PATH_AC_ENERGY_FORWARD = "/Ac/Energy/Forward"
_PATH_AC_ENERGY_DAILY = "/Ac/Energy/Daily"

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("TasmotaPV")


def parse_energy_payload(payload: bytes | str) -> tuple[float, float, float, float, float] | None:
    """Parse a Tasmota ``tele/<topic>/SENSOR`` JSON payload.

    Returns ``(power, voltage, current, total, today)`` or ``None`` when the
    payload is not JSON or carries no ENERGY block. ``Current`` is derived
    from power/voltage (Tasmota's own reading is ignored for consistency).
    """
    try:
        energy = json.loads(payload)["ENERGY"]
        power = float(energy.get("Power", 0.0))
        voltage = float(energy.get("Voltage", 115.0))
        total = float(energy.get("Total", 0.0))
        today = float(energy.get("Today", 0.0))
        current = round(power / voltage, 2) if voltage > 0 else 0.0
        return power, voltage, current, total, today
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


class TasmotaPVInverter:
    """Single Tasmota plug as a PV Inverter on D-Bus, fed by MQTT telemetry."""

    def __init__(self, topic: str, instance: int):
        self.topic = topic
        self.instance = instance
        self._last_update = time()
        self._connected = True

        # Create a private bus connection for each instance to avoid path conflicts
        self.bus = dbus.SystemBus(private=True)

        service_name = f"com.victronenergy.pvinverter.tasmota_{instance}"
        self._dbusservice = VeDbusService(service_name, bus=self.bus, register=False)

        # Mandatory management paths
        self._dbusservice.add_path("/Mgmt/ProcessName", "dbus-tasmota-pv.py")
        self._dbusservice.add_path("/Mgmt/ProcessVersion", VERSION)
        self._dbusservice.add_path("/ProductName", f"Solar Tasmota {topic}")
        self._dbusservice.add_path("/CustomName", f"Solar Tasmota {topic}")
        self._dbusservice.add_path("/Serial", f"TASMOTA-{instance}")
        self._dbusservice.add_path(_PATH_CONNECTED, 1)
        self._dbusservice.add_path("/DeviceInstance", instance)
        self._dbusservice.add_path("/ProductId", 0xA144)  # Standard PV Inverter ID
        self._dbusservice.add_path(_PATH_ERROR_CODE, 0)
        self._dbusservice.add_path("/FirmwareVersion", VERSION)

        # Position: 0 = AC Input (Grid side), 1 = AC Output (Load side)
        self._dbusservice.add_path("/Position", 0)

        # AC Power Paths
        self._dbusservice.add_path(_PATH_AC_POWER, 0.0)
        self._dbusservice.add_path(_PATH_AC_L1_POWER, 0.0)
        self._dbusservice.add_path(_PATH_AC_L1_VOLTAGE, 115.0)
        self._dbusservice.add_path(_PATH_AC_L1_CURRENT, 0.0)
        self._dbusservice.add_path(_PATH_AC_ENERGY_FORWARD, 0.0)
        self._dbusservice.add_path(_PATH_AC_ENERGY_DAILY, 0.0)

        self._dbusservice.register()
        logger.info(f"Registered PV Inverter: {service_name} (MQTT topic: {topic})")

    def _set_paths(self, values: dict[str, Any]) -> None:
        """Update D-Bus paths safely from any thread.

        The D-Bus service is serviced by the GLib main loop in the main
        thread, while ``apply()`` runs on the paho-mqtt network thread.
        Marshal the writes onto the GLib thread via `GLib.idle_add` to avoid
        concurrent access to the underlying D-Bus connection.
        """

        def _apply():
            for path, value in values.items():
                self._dbusservice[path] = value
            return False

        GLib.idle_add(_apply)

    def apply(self, power: float, voltage: float, current: float, total: float, today: float):
        """Push a fresh ENERGY reading onto D-Bus."""
        self._last_update = time()
        if not self._connected:
            self._connected = True
            logger.info(f"Tasmota {self.topic} back online")

        self._set_paths(
            {
                _PATH_CONNECTED: 1,
                _PATH_ERROR_CODE: 0,
                _PATH_AC_POWER: power,
                _PATH_AC_L1_POWER: power,
                _PATH_AC_L1_VOLTAGE: voltage,
                _PATH_AC_L1_CURRENT: current,
                _PATH_AC_ENERGY_FORWARD: total,
                _PATH_AC_ENERGY_DAILY: today,
            }
        )

    def check_stale(self) -> None:
        """Mark the device offline when no telemetry arrived recently."""
        if not self._connected:
            return
        if time() - self._last_update > STALE_AFTER_SECONDS:
            self._connected = False
            logger.warning(
                f"Tasmota {self.topic}: no telemetry for {STALE_AFTER_SECONDS}s, marking offline"
            )
            self._set_paths(
                {
                    _PATH_ERROR_CODE: 1,  # Offline/comm error
                    _PATH_CONNECTED: 0,
                    _PATH_AC_POWER: 0.0,
                    _PATH_AC_L1_POWER: 0.0,
                }
            )


class MqttEnergyListener:
    """Subscribe to ``tele/<topic>/SENSOR`` for every inverter and route payloads."""

    def __init__(self, inverters: list[TasmotaPVInverter], host: str, port: int):
        self._host = host
        self._port = port
        self._subscriptions = {f"tele/{inv.topic}/SENSOR": inv for inv in inverters}
        self._client = MqttClient(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id="dbus-tasmota-pv",
        )
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def start(self) -> None:
        """Connect asynchronously and start the network thread (auto-reconnect)."""
        self._client.connect_async(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        """Stop the network thread and disconnect."""
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        # paho v2 hands us a ReasonCode object; guard is_failure for robustness
        if getattr(reason_code, "is_failure", False):
            logger.error(f"MQTT connect to {self._host}:{self._port} failed: {reason_code}")
            return
        logger.info(
            f"Connected to MQTT broker {self._host}:{self._port}, "
            f"subscribing: {', '.join(sorted(self._subscriptions))}"
        )
        client.subscribe([(topic, 0) for topic in self._subscriptions])

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        logger.warning(f"MQTT disconnected ({reason_code}); auto-reconnect in progress")

    def _on_message(self, client, userdata, msg):
        inverter = self._subscriptions.get(msg.topic)
        if inverter is None:
            logger.debug(f"Ignoring message on unconfigured topic: {msg.topic}")
            return
        parsed = parse_energy_payload(msg.payload)
        if parsed is None:
            logger.warning(f"Tasmota {inverter.topic}: unparseable SENSOR payload")
            return
        inverter.apply(*parsed)


def load_config(config_path: Path) -> list[tuple[str, int]]:
    """Load devices from a JSON config file."""
    # Validate path before opening (prevent path traversal via ..)
    try:
        config_path = config_path.resolve()
    except (OSError, ValueError) as e:
        raise ValueError(f"Invalid config path: {config_path}") from e
    if not config_path.is_file():
        raise ValueError(f"Config path is not a file: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    devices = []
    for device in config.get("devices", []):
        topic = device.get("topic")
        instance = device.get("instance")
        if topic and instance is not None:
            devices.append((str(topic), int(instance)))
    return devices


def _parse_device_spec(spec: str) -> tuple[str, int]:
    """Parse TOPIC:INSTANCE string into (topic, instance) tuple."""
    topic, instance_str = spec.rsplit(":", 1)
    return topic, int(instance_str)


def _load_devices(args: argparse.Namespace) -> list[tuple[str, int]]:
    """Load devices from CLI args or config file."""
    if args.devices:
        devices = []
        for spec in args.devices:
            try:
                topic, instance = _parse_device_spec(spec)
                devices.append((topic, instance))
                logger.info(f"CLI device: {topic} (instance {instance})")
            except ValueError:
                logger.error(f"Invalid device specification: {spec} (expected TOPIC:INSTANCE)")
                sys.exit(1)
        return devices

    if args.config.exists():
        devices = load_config(args.config)
        logger.info(f"Loaded {len(devices)} device(s) from {args.config}")
        return devices

    logger.error(f"No devices specified and config file not found: {args.config}")
    logger.info("Use --devices TOPIC:INSTANCE or create config file at /etc/dbus-tasmota-pv.json")
    sys.exit(1)


def _create_inverters(devices: list[tuple[str, int]]) -> list[TasmotaPVInverter]:
    """Create TasmotaPVInverter instances for each configured device."""
    inverters = []
    for topic, instance in devices:
        try:
            inverters.append(TasmotaPVInverter(topic, instance))
        except Exception:
            logger.exception(f"Failed to create inverter for {topic}")
    return inverters


def _write_heartbeat(heartbeat_file: str) -> None:
    """Write the current timestamp to the heartbeat file (blocking I/O)."""
    try:
        with open(heartbeat_file, "w", encoding="utf-8") as f:
            f.write(str(int(time())))
    except OSError:
        # Intentionally ignored: failed heartbeat write should not crash the service
        pass


def _make_tick(inverters: list[TasmotaPVInverter], heartbeat_file: str):
    """Build the periodic tick callback (staleness, GC, heartbeat)."""
    state = {"gc_counter": 0}

    def tick() -> bool:
        """Periodic housekeeping; returning True keeps the GLib timer alive."""
        for inv in inverters:
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
        description="Tasmota Energy Meter (MQTT) to D-Bus PV Inverter Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    ./dbus-tasmota-pv.py --config /etc/dbus-tasmota-pv.json
    ./dbus-tasmota-pv.py -d tasmota_120:120 -d tasmota_121:121
    ./dbus-tasmota-pv.py -d tasmota_120:120 --mqtt-host 192.168.160.150
        """,
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("/etc/dbus-tasmota-pv.json"),
        help="Path to JSON config file",
    )
    parser.add_argument(
        "-d",
        "--devices",
        nargs="+",
        help="Device specifications as TOPIC:INSTANCE (overrides config file)",
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

    devices = _load_devices(args)

    # Setup D-Bus main loop
    DBusGMainLoop(set_as_default=True)
    mainloop = GLib.MainLoop()

    inverters = _create_inverters(devices)
    if not inverters:
        logger.error("No inverters could be created")
        sys.exit(1)

    _register_signal_handlers(mainloop)

    listener = MqttEnergyListener(inverters, args.mqtt_host, args.mqtt_port)
    GLib.timeout_add_seconds(TICK_SECONDS, _make_tick(inverters, HEARTBEAT_FILE))

    logger.info(
        f"=== dbus-tasmota-pv v{VERSION}: {len(inverters)} inverter(s), "
        f"MQTT {args.mqtt_host}:{args.mqtt_port} ==="
    )
    listener.start()
    try:
        mainloop.run()
    finally:
        logger.info("Cleaning up...")
        listener.stop()
        gc.collect()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
