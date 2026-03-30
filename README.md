# dbus-tasmota-pv

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

Edit `dbus-tasmota-pv.py` to configure your Tasmota plug IP addresses:

```python
# Line ~86-87 in dbus-tasmota-pv.py
inv1 = TasmotaPVInverter('192.168.164.73', 120)  # First plug, instance 120
inv2 = TasmotaPVInverter('192.168.164.74', 121)  # Second plug, instance 121
```

Parameters:
- First argument: Tasmota plug IP address
- Second argument: D-Bus device instance (unique number, 120-199 recommended)

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

# Deploy to Venus OS (assumes SSH host 'r' in ~/.ssh/config)
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
```bash
# Check rc.local
cat /data/rc.local

# Re-run installer
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

## License

MIT License
