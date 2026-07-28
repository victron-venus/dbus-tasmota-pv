#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dbus-tasmota-pv - Tasmota Energy Meter to D-Bus PV Inverter Bridge
===================================================================

Reads power data from Tasmota smart plugs (with energy monitoring)
and publishes to Victron D-Bus as PV Inverter devices.

Supports multiple Tasmota devices with individual polling.
Features:
- Async HTTP polling with httpx for non-blocking I/O
- mDNS/SSDP auto-discovery of Tasmota devices
- Connection pooling and graceful error handling

Usage:
    ./dbus-tasmota-pv.py --devices 192.168.164.73:120 192.168.164.74:121
    ./dbus-tasmota-pv.py --discover  # Auto-discover Tasmota devices via mDNS
    ./dbus-tasmota-pv.py --config /etc/dbus-tasmota-pv.yaml

Where each device is specified as IP:INSTANCE
"""

import argparse
import asyncio
import gc
import logging
import signal
import sys
from pathlib import Path
from time import time
from typing import Any

import httpx
import yaml

# Optional mDNS discovery
try:
    from zeroconf import IPVersion, ServiceBrowser, ServiceStateChange, Zeroconf

    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False
    ServiceBrowser = ServiceStateChange = Zeroconf = IPVersion = None

# Venus OS path (optional - needed on Venus OS only)
VELIB_PATH = Path("/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")
if VELIB_PATH.exists():
    sys.path.insert(0, str(VELIB_PATH))
    from vedbus import VeDbusService  # type: ignore[attr-defined]
    import dbus  # type: ignore[attr-defined]
    from dbus.mainloop.glib import DBusGMainLoop  # type: ignore[attr-defined]
    from gi.repository import GLib  # type: ignore[attr-defined]
else:
    VeDbusService = None
    dbus = None
    DBusGMainLoop = None
    GLib = None

VERSION = "1.4.0"
POLL_INTERVAL_MS = 2000
HTTP_TIMEOUT = 5.0  # seconds
MAX_CONSECUTIVE_FAILURES = 5

# D-Bus path constants (avoid magic strings)
_PATH_CONNECTED = "/Connected"
_PATH_ERROR_CODE = "/ErrorCode"
_PATH_AC_POWER = "/Ac/Power"
_PATH_AC_L1_POWER = "/Ac/L1/Power"
_PATH_AC_L1_VOLTAGE = "/Ac/L1/Voltage"
_PATH_AC_L1_CURRENT = "/Ac/L1/Current"
_PATH_AC_ENERGY_FORWARD = "/Ac/Energy/Forward"

# mDNS service type for Tasmota
TASSOTA_MDNS_TYPE = "_tasmota._tcp.local."

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("TasmotaPV")


class AsyncHTTPClient:
    """Async HTTP client wrapper with connection pooling."""

    def __init__(self, max_connections: int):
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(HTTP_TIMEOUT),
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_connections * 2,
            ),
        )

    async def get(self, url: str) -> httpx.Response:
        """Async GET request."""
        return await self._client.get(url)

    async def close(self):
        """Close the client."""
        await self._client.aclose()


class TasmotaMDNSDiscovery:
    """mDNS discovery for Tasmota devices."""

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self._found_devices: dict[str, str] = {}  # ip -> hostname
        self._browser = None
        self._zeroconf = None
        self._event = asyncio.Event()
        self._resolving = set()
        self._tasks: set[asyncio.Task] = set()

    def _on_service_state_change(
        self,
        zeroconf: Any,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Handle service state changes."""
        if state_change is ServiceStateChange.Added:
            task = asyncio.create_task(self._resolve_service(zeroconf, service_type, name))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _resolve_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        """Resolve service to get IP address."""
        if name in self._resolving:
            return
        self._resolving.add(name)
        try:
            info = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, zeroconf.get_service_info, service_type, name
                ),
                timeout=2.0,
            )
            if info:
                ip = ".".join(str(b) for b in info.addresses[0])
                self._found_devices[ip] = name
                logger.debug("Discovered Tasmota: %s at %s", name, ip)
            self._event.set()
        except Exception as e:
            logger.debug("Failed to resolve service %s: %s", name, e)
        finally:
            self._resolving.discard(name)

    async def discover(self) -> dict[str, str]:
        """Discover Tasmota devices via mDNS."""
        if not ZEROCONF_AVAILABLE:
            logger.warning("zeroconf not installed, mDNS discovery disabled")
            return {}

        self._found_devices = {}
        self._event.clear()

        self._zeroconf = Zeroconf(ip_version=IPVersion.All)
        self._browser = ServiceBrowser(
            self._zeroconf,
            TASSOTA_MDNS_TYPE,
            handlers=[self._on_service_state_change],
        )

        # Wait for discovery to complete
        try:
            await asyncio.wait_for(self._event.wait(), timeout=self.timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            if self._zeroconf:
                self._zeroconf.close()

        return self._found_devices


class TasmotaPVInverter:
    """Single Tasmota device as PV Inverter on D-Bus"""

    def __init__(
        self,
        ip_address: str,
        instance: int,
        client: AsyncHTTPClient,
    ):
        self.ip = ip_address
        self.instance = instance
        self._client = client
        self._consecutive_failures = 0
        self._last_success = time()
        self._connected = True

        # Create a private bus connection for each instance to avoid path conflicts
        self.bus = dbus.SystemBus(private=True)

        service_name = f"com.victronenergy.pvinverter.tasmota_{instance}"
        self._dbusservice = VeDbusService(service_name, bus=self.bus, register=False)

        # Mandatory management paths
        self._dbusservice.add_path("/Mgmt/ProcessName", "dbus-tasmota-pv.py")
        self._dbusservice.add_path("/Mgmt/ProcessVersion", VERSION)
        self._dbusservice.add_path("/ProductName", f"Solar Tasmota {ip_address}")
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

        self._dbusservice.register()
        logger.info(f"Registered PV Inverter: {service_name} (IP: {ip_address})")

    async def _get_tasmota_data(self) -> tuple[float, float, float, float] | None:
        """Fetch energy data from Tasmota device"""
        try:
            response = await self._client.get(f"http://{self.ip}/cm?cmnd=Status%208")
            response.raise_for_status()
            data = response.json()

            energy = data["StatusSNS"]["ENERGY"]
            power = float(energy.get("Power", 0.0))
            voltage = float(energy.get("Voltage", 115.0))
            total = float(energy.get("Total", 0.0))
            current = round(power / voltage, 2) if voltage > 0 else 0.0

            # Reset failure counter on success
            self._consecutive_failures = 0
            self._last_success = time()

            if not self._connected:
                self._connected = True
                logger.info(f"Tasmota {self.ip} reconnected")

            return power, voltage, current, total

        except Exception as e:
            # Check exception type by name since httpx may be mocked in tests
            error_type = type(e).__name__
            if error_type == "TimeoutException":
                self._handle_failure("timeout")
            elif error_type == "ConnectError":
                self._handle_failure("connection error")
            else:
                self._handle_failure(str(e))
            return None

    def _handle_failure(self, reason: str):
        """Handle connection failure with backoff"""
        self._consecutive_failures += 1

        if self._consecutive_failures == 1:
            logger.warning(f"Tasmota {self.ip}: {reason}")
        elif self._consecutive_failures == MAX_CONSECUTIVE_FAILURES:
            logger.error(
                f"Tasmota {self.ip}: {MAX_CONSECUTIVE_FAILURES} consecutive failures, marking offline"
            )
            self._connected = False
        elif self._consecutive_failures % 30 == 0:
            # Log every 30 failures (~1 minute)
            logger.warning(
                f"Tasmota {self.ip}: still offline ({self._consecutive_failures} failures)"
            )

    async def update(self):
        """Update D-Bus values from Tasmota data"""
        result = await self._get_tasmota_data()

        if result is None:
            # Stale data: report via ErrorCode, fallback to zero power
            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                self._dbusservice[_PATH_ERROR_CODE] = 1  # Offline/comm error
                self._dbusservice[_PATH_CONNECTED] = 0
                self._dbusservice[_PATH_AC_POWER] = 0.0
                self._dbusservice[_PATH_AC_L1_POWER] = 0.0
            else:
                self._dbusservice[_PATH_ERROR_CODE] = 0
                self._dbusservice[_PATH_CONNECTED] = 1
            return

        power, voltage, current, total = result

        self._dbusservice[_PATH_CONNECTED] = 1
        self._dbusservice[_PATH_ERROR_CODE] = 0
        self._dbusservice[_PATH_AC_POWER] = power
        self._dbusservice[_PATH_AC_L1_POWER] = power
        self._dbusservice[_PATH_AC_L1_VOLTAGE] = voltage
        self._dbusservice[_PATH_AC_L1_CURRENT] = current
        self._dbusservice[_PATH_AC_ENERGY_FORWARD] = total


def load_config(config_path: Path) -> list[tuple[str, int]]:
    """Load devices from YAML config file"""
    # Validate path before opening (prevent path traversal via ..)
    try:
        config_path = config_path.resolve()
    except (OSError, ValueError) as e:
        raise ValueError(f"Invalid config path: {config_path}") from e
    if not config_path.is_file():
        raise ValueError(f"Config path is not a file: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    devices = []
    for device in config.get("devices", []):
        ip = device.get("ip")
        instance = device.get("instance")
        if ip and instance is not None:
            devices.append((ip, int(instance)))
    return devices


def _parse_device_spec(spec: str) -> tuple[str, int]:
    """Parse IP:INSTANCE string into (ip, instance) tuple."""
    ip, instance_str = spec.rsplit(":", 1)
    return ip, int(instance_str)


def _load_devices(args: argparse.Namespace) -> list[tuple[str, int]]:
    """Load devices from CLI args, mDNS discovery, or config file."""
    if args.devices:
        devices = []
        for spec in args.devices:
            try:
                ip, instance = _parse_device_spec(spec)
                devices.append((ip, instance))
                logger.info(f"CLI device: {ip} (instance {instance})")
            except ValueError:
                logger.error(f"Invalid device specification: {spec} (expected IP:INSTANCE)")
                sys.exit(1)
        return devices

    if args.discover:
        logger.info("Auto-discovering Tasmota devices via mDNS...")
        try:
            discovery = TasmotaMDNSDiscovery(timeout=args.discover_timeout)
            discovered = asyncio.run(discovery.discover())
            if discovered:
                # Auto-assign instances starting from 120
                devices = [(ip, 120 + i) for i, ip in enumerate(discovered.keys())]
                logger.info(f"Discovered {len(devices)} Tasmota device(s): {devices}")
                return devices
            logger.warning("No Tasmota devices discovered via mDNS")
        except Exception:
            logger.exception("mDNS discovery failed")

    if args.config.exists():
        devices = load_config(args.config)
        logger.info(f"Loaded {len(devices)} device(s) from {args.config}")
        return devices

    logger.error(f"No devices specified and config file not found: {args.config}")
    logger.info(
        "Use --devices IP:INSTANCE, --discover, or create config file at /etc/dbus-tasmota-pv.yaml"
    )
    sys.exit(1)


def _create_inverters(
    devices: list[tuple[str, int]], client: AsyncHTTPClient
) -> list[TasmotaPVInverter]:
    """Create TasmotaPVInverter instances for each configured device."""
    inverters = []
    for ip, instance in devices:
        try:
            inv = TasmotaPVInverter(ip, instance, client)
            inverters.append(inv)
        except Exception:
            logger.exception(f"Failed to create inverter for {ip}")
    return inverters


def _write_heartbeat(heartbeat_file: str) -> None:
    """Write the current timestamp to the heartbeat file (blocking I/O)."""
    try:
        with open(heartbeat_file, "w", encoding="utf-8") as f:
            f.write(str(int(time())))
    except OSError:
        # Intentionally ignored: failed heartbeat write should not crash polling
        pass


def _make_poll_fn(inverters: list[TasmotaPVInverter], heartbeat_file: str):
    """Build the periodic poll callback with memory management."""
    state = {"gc_counter": 0}
    gc_interval = 150  # Run GC every 150 polls (~5 minutes)

    async def poll() -> bool:
        """Periodic update with memory management"""
        for inv in inverters:
            try:
                await inv.update()
            except Exception:
                logger.exception("Error updating %s", inv.ip)

        # Periodic garbage collection
        state["gc_counter"] += 1
        if state["gc_counter"] >= gc_interval:
            state["gc_counter"] = 0
            gc.collect()

        # Heartbeat for watchdog (run blocking I/O off the event loop)
        await asyncio.to_thread(_write_heartbeat, heartbeat_file)

        return True

    return poll


async def _async_main(devices: list[tuple[str, int]], heartbeat_file: str):
    """Async main function."""
    logger.info(f"=== dbus-tasmota-pv v{VERSION} ===")

    # Setup D-Bus main loop
    DBusGMainLoop(set_as_default=True)
    mainloop = GLib.MainLoop()

    # Create shared HTTP client with connection pooling
    client = AsyncHTTPClient(len(devices))

    # Create inverter instances
    inverters = _create_inverters(devices, client)

    if not inverters:
        logger.error("No inverters could be created")
        await client.close()
        sys.exit(1)

    # Start polling
    poll = _make_poll_fn(inverters, heartbeat_file)
    GLib.timeout_add(POLL_INTERVAL_MS, lambda: asyncio.ensure_future(poll()))

    logger.info(f"Service started with {len(inverters)} inverter(s), entering main loop")

    try:
        mainloop.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception:
        logger.exception("Unexpected error in main loop")
    finally:
        logger.info("Cleaning up...")
        await client.close()
        gc.collect()
        logger.info("Shutdown complete")


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
        description="Tasmota Energy Meter to D-Bus PV Inverter Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    ./dbus-tasmota-pv.py --config /etc/dbus-tasmota-pv.yaml
    ./dbus-tasmota-pv.py -d 192.168.1.100:120 -d 192.168.1.101:121
    ./dbus-tasmota-pv.py --discover
    ./dbus-tasmota-pv.py --discover --discover-timeout 10
        """,
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("/etc/dbus-tasmota-pv.yaml"),
        help="Path to YAML config file",
    )
    parser.add_argument(
        "-d",
        "--devices",
        nargs="+",
        help="Device specifications as IP:INSTANCE (overrides config file)",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Auto-discover Tasmota devices via mDNS/SSDP",
    )
    parser.add_argument(
        "--discover-timeout",
        type=float,
        default=5.0,
        help="mDNS discovery timeout in seconds (default: 5.0)",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    devices = _load_devices(args)

    # Setup D-Bus main loop
    DBusGMainLoop(set_as_default=True)
    mainloop = GLib.MainLoop()

    _register_signal_handlers(mainloop)

    # Heartbeat file for watchdog
    heartbeat_file = "/run/dbus-tasmota-pv.alive"

    # Run async main
    asyncio.run(_async_main(devices, heartbeat_file))


if __name__ == "__main__":
    main()
