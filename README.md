# dbus-tasmota-pv

[![CI](https://github.com/victron-venus/dbus-tasmota-pv/actions/workflows/ci.yml/badge.svg)](https://github.com/victron-venus/dbus-tasmota-pv/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Release](https://img.shields.io/github/v/release/victron-venus/dbus-tasmota-pv)](https://github.com/victron-venus/dbus-tasmota-pv/releases)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![Venus OS](https://img.shields.io/badge/Venus%20OS-3.x-blue)](https://github.com/victronenergy/venus)
[![GitHub stars](https://img.shields.io/github/stars/victron-venus/dbus-tasmota-pv)](https://github.com/victron-venus/dbus-tasmota-pv/stargazers)
[![GitHub last commit](https://img.shields.io/github/last-commit/victron-venus/dbus-tasmota-pv)](https://github.com/victron-venus/dbus-tasmota-pv/commits/main)

Venus OS driver for Tasmota smart plugs monitoring inline PV inverters.

## Overview

This script polls Tasmota smart plugs via HTTP and publishes power data to D-Bus as PV inverters. This allows Victron GX devices to see and display solar production from simple inline MPPT inverters that don't have native Victron integration.

```
[Solar Panel] → [Inline MPPT Inverter] → [Tasmota Smart Plug] → AC Grid
                                               ↓ HTTP polling
                                        [This Script on Cerbo GX]
                                               ↓ D-Bus
                                        [Victron GUI / VRM]
```

## Features

- Polls Tasmota smart plugs every 2 seconds
- Reports power, voltage, current, and total energy
- Each plug appears as a separate PV inverter in Victron GUI
- Shows in VRM portal as PV production
- Minimal resource usage

## Configuration

Configure devices via command line arguments:

```bash
# Format: IP:INSTANCE
./dbus-tasmota-pv.py --devices 192.168.1.100:120 192.168.1.101:121
```

Or edit the service run script `/service/dbus-tasmota-pv/run`:

```bash
#!/bin/sh
cd /data/dbus-tasmota-pv
exec python3 dbus-tasmota-pv.py --devices 192.168.164.73:120 192.168.164.74:121
```

Parameters:
- IP address: Tasmota plug IP
- Instance: D-Bus device instance (unique number, 120-199 recommended)

## Requirements

- Venus OS (Cerbo GX, Venus GX, Raspberry Pi with Venus OS)
- Tasmota smart plugs with energy monitoring (e.g., Sonoff S31, Athom)
- Network access from GX device to Tasmota plugs

## Installation

### From local machine (recommended)

```bash
# Clone repository
cd dbus-tasmota-pv

# Edit dbus-tasmota-pv.py with your Tasmota IPs

# Deploy to Venus OS (assumes SSH host 'Cerbo' in ~/.ssh/config)
./deploy.sh
```

### Manual installation on Venus OS

```bash
# Copy files to Venus OS
scp -r dbus-tasmota-pv root@venus-ip:/data/

# SSH to Venus OS
ssh root@venus-ip

# Run installer
cd /data/dbus-tasmota-pv
./install.sh
```

## Service Management

```bash
# Check status
svstat /service/dbus-tasmota-pv

# Restart service
svc -t /service/dbus-tasmota-pv

# Stop service
svc -d /service/dbus-tasmota-pv

# Start service
svc -u /service/dbus-tasmota-pv

# View logs
tail -f /var/log/dbus-tasmota-pv/current | tai64nlocal
```

## Tasmota Setup

1. Flash your smart plug with Tasmota
2. Configure WiFi and connect to your network
3. Enable energy monitoring if not already enabled
4. Note the IP address (Settings → Information)
5. Test by accessing: `http://PLUG_IP/cm?cmnd=Status%208`

You should see JSON with ENERGY data including Power, Voltage, Current, Total.

## Troubleshooting

### Service not starting
```bash
# Check if service exists
ls -la /service/dbus-tasmota-pv/

# Check run script
cat /service/dbus-tasmota-pv/run

# Check for errors
cat /var/log/dbus-tasmota-pv/current | tai64nlocal | tail -20
```

### No data from Tasmota
```bash
# Test HTTP connection from Venus OS
curl 'http://192.168.164.73/cm?cmnd=Status%208'
```

### Service doesn't survive reboot

Venus OS uses daemontools for service management. Services in `/service/` start automatically on boot.

```bash
# Verify service symlink exists
ls -la /service/dbus-tasmota-pv

# Should point to /opt/victronenergy/service/dbus-tasmota-pv
# If missing, re-run installer:
cd /data/dbus-tasmota-pv
./install.sh
```

## D-Bus Paths

The script publishes these D-Bus paths for each inverter:

| Path | Description |
|------|-------------|
| `/Ac/Power` | Total AC power (W) |
| `/Ac/L1/Power` | L1 power (W) |
| `/Ac/L1/Voltage` | L1 voltage (V) |
| `/Ac/L1/Current` | L1 current (A) |
| `/Ac/Energy/Forward` | Total energy produced (kWh) |
| `/Position` | 0 = AC Input (grid side) |

## Related Projects

This project is part of a Victron Venus OS integration suite:

| Project | Description |
|---------|-------------|
| [inverter-control](https://github.com/victron-venus/inverter-control) | ESS external control with web dashboard |
| [dbus-mqtt-battery](https://github.com/victron-venus/dbus-mqtt-battery) | MQTT to D-Bus bridge for BMS integration |
| **dbus-tasmota-pv** (this) | Tasmota smart plug as PV inverter on D-Bus |
| [esphome-jbd-bms-mqtt](https://github.com/victron-venus/esphome-jbd-bms-mqtt) | ESP32 Bluetooth monitor for JBD BMS |

## License

MIT License
