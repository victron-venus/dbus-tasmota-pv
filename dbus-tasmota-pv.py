#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dbus-tasmota-pv - Tasmota Energy Meter to D-Bus PV Inverter Bridge
===================================================================

Reads power data from Tasmota smart plugs (with energy monitoring)
and publishes to Victron D-Bus as PV Inverter devices.

Supports multiple Tasmota devices with individual polling.

Usage:
    ./dbus-tasmota-pv.py --devices 192.168.164.73:120 192.168.164.74:121

Where each device is specified as IP:INSTANCE
"""

import os
import sys
import argparse
import logging
import signal
import gc
from time import time

import requests
from requests.adapters import HTTPAdapter
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

# Add Victron energy libraries to path
sys.path.append('/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService

VERSION = "1.2.0"
POLL_INTERVAL_MS = 2000
HTTP_TIMEOUT = (2, 3)  # (connect_timeout, read_timeout)
MAX_CONSECUTIVE_FAILURES = 5

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger("TasmotaPV")


class TasmotaPVInverter:
    """Single Tasmota device as PV Inverter on D-Bus"""
    
    def __init__(self, ip_address: str, instance: int, session: requests.Session):
        self.ip = ip_address
        self.instance = instance
        self._session = session
        self._consecutive_failures = 0
        self._last_success = time()
        self._connected = True
        
        # Create a private bus connection for each instance to avoid path conflicts
        self.bus = dbus.SystemBus(private=True)
        
        service_name = f'com.victronenergy.pvinverter.tasmota_{instance}'
        self._dbusservice = VeDbusService(service_name, bus=self.bus, register=False)
        
        # Mandatory management paths
        self._dbusservice.add_path('/Mgmt/ProcessName', 'dbus-tasmota-pv.py')
        self._dbusservice.add_path('/Mgmt/ProcessVersion', VERSION)
        self._dbusservice.add_path('/ProductName', f'Solar Tasmota {ip_address}')
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/DeviceInstance', instance)
        self._dbusservice.add_path('/ProductId', 0xA144)  # Standard PV Inverter ID
        self._dbusservice.add_path('/ErrorCode', 0)
        self._dbusservice.add_path('/FirmwareVersion', VERSION)
        
        # Position: 0 = AC Input (Grid side), 1 = AC Output (Load side)
        self._dbusservice.add_path('/Position', 0)
        
        # AC Power Paths
        self._dbusservice.add_path('/Ac/Power', 0.0)
        self._dbusservice.add_path('/Ac/L1/Power', 0.0)
        self._dbusservice.add_path('/Ac/L1/Voltage', 115.0)
        self._dbusservice.add_path('/Ac/L1/Current', 0.0)
        self._dbusservice.add_path('/Ac/Energy/Forward', 0.0)

        self._dbusservice.register()
        logger.info(f"Registered PV Inverter: {service_name} (IP: {ip_address})")

    def _get_tasmota_data(self):
        """Fetch energy data from Tasmota device"""
        try:
            response = self._session.get(
                f'http://{self.ip}/cm?cmnd=Status%208',
                timeout=HTTP_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            
            energy = data['StatusSNS']['ENERGY']
            power = float(energy.get('Power', 0.0))
            voltage = float(energy.get('Voltage', 115.0))
            total = float(energy.get('Total', 0.0))
            current = round(power / voltage, 2) if voltage > 0 else 0.0
            
            # Reset failure counter on success
            self._consecutive_failures = 0
            self._last_success = time()
            
            if not self._connected:
                self._connected = True
                logger.info(f"Tasmota {self.ip} reconnected")
            
            return power, voltage, current, total
            
        except requests.exceptions.Timeout:
            self._handle_failure("timeout")
            return None
        except requests.exceptions.ConnectionError:
            self._handle_failure("connection error")
            return None
        except Exception as e:
            self._handle_failure(str(e))
            return None
    
    def _handle_failure(self, reason: str):
        """Handle connection failure with backoff"""
        self._consecutive_failures += 1
        
        if self._consecutive_failures == 1:
            logger.warning(f"Tasmota {self.ip}: {reason}")
        elif self._consecutive_failures == MAX_CONSECUTIVE_FAILURES:
            logger.error(f"Tasmota {self.ip}: {MAX_CONSECUTIVE_FAILURES} consecutive failures, marking offline")
            self._connected = False
        elif self._consecutive_failures % 30 == 0:
            # Log every 30 failures (~1 minute)
            logger.warning(f"Tasmota {self.ip}: still offline ({self._consecutive_failures} failures)")

    def update(self):
        """Update D-Bus values from Tasmota data"""
        result = self._get_tasmota_data()
        
        if result is None:
            # Keep last values but update connected status
            self._dbusservice['/Connected'] = 1 if self._connected else 0
            self._dbusservice['/ErrorCode'] = 0 if self._connected else 1
            return
        
        power, voltage, current, total = result
        
        self._dbusservice['/Connected'] = 1
        self._dbusservice['/ErrorCode'] = 0
        self._dbusservice['/Ac/Power'] = power
        self._dbusservice['/Ac/L1/Power'] = power
        self._dbusservice['/Ac/L1/Voltage'] = voltage
        self._dbusservice['/Ac/L1/Current'] = current
        self._dbusservice['/Ac/Energy/Forward'] = total


def main():
    parser = argparse.ArgumentParser(
        description='Tasmota Energy Meter to D-Bus PV Inverter Bridge',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    ./dbus-tasmota-pv.py --devices 192.168.1.100:120 192.168.1.101:121
    ./dbus-tasmota-pv.py -d 192.168.164.73:120 -d 192.168.164.74:121
        """
    )
    parser.add_argument(
        '-d', '--devices',
        nargs='+',
        default=['192.168.164.73:120', '192.168.164.74:121'],
        help='Device specifications as IP:INSTANCE (e.g., 192.168.1.100:120)'
    )
    args = parser.parse_args()
    
    logger.info(f"=== dbus-tasmota-pv v{VERSION} ===")
    
    # Parse device specifications
    devices = []
    for spec in args.devices:
        try:
            ip, instance = spec.rsplit(':', 1)
            instance = int(instance)
            devices.append((ip, instance))
            logger.info(f"Configured device: {ip} (instance {instance})")
        except ValueError:
            logger.error(f"Invalid device specification: {spec} (expected IP:INSTANCE)")
            sys.exit(1)
    
    if not devices:
        logger.error("No devices configured")
        sys.exit(1)
    
    # Setup D-Bus main loop
    DBusGMainLoop(set_as_default=True)
    mainloop = GLib.MainLoop()
    
    def graceful_shutdown(signum, frame):
        """Handle shutdown signals gracefully"""
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.info(f"Received {sig_name}, shutting down gracefully...")
        mainloop.quit()
    
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)
    
    # Create shared HTTP session with connection pooling
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=len(devices),
        pool_maxsize=len(devices) * 2,
        max_retries=0  # We handle retries ourselves
    )
    session.mount('http://', adapter)
    
    # Create inverter instances
    inverters = []
    for ip, instance in devices:
        try:
            inv = TasmotaPVInverter(ip, instance, session)
            inverters.append(inv)
        except Exception as e:
            logger.error(f"Failed to create inverter for {ip}: {e}")
    
    if not inverters:
        logger.error("No inverters could be created")
        session.close()
        sys.exit(1)
    
    # Periodic garbage collection counter
    gc_counter = 0
    GC_INTERVAL = 150  # Run GC every 150 polls (~5 minutes)
    
    def poll():
        """Periodic update with memory management"""
        nonlocal gc_counter
        
        for inv in inverters:
            try:
                inv.update()
            except Exception as e:
                logger.error(f"Error updating {inv.ip}: {e}")
        
        # Periodic garbage collection
        gc_counter += 1
        if gc_counter >= GC_INTERVAL:
            gc_counter = 0
            gc.collect()
        
        return True
    
    # Start polling
    GLib.timeout_add(POLL_INTERVAL_MS, poll)
    
    logger.info(f"Service started with {len(inverters)} inverter(s), entering main loop")
    
    try:
        mainloop.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
    finally:
        logger.info("Cleaning up...")
        session.close()
        gc.collect()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
