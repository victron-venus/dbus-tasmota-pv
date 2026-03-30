#!/usr/bin/env python

import os
import sys
import requests
import dbus
from gi.repository import GLib

# Add Victron energy libraries to path
sys.path.append('/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService

class TasmotaPVInverter:
    def __init__(self, ip_address, instance):
        self.ip = ip_address
        
        # Create a private bus connection for each instance to avoid path conflicts
        self.bus = dbus.SystemBus(private=True)
        
        service_name = f'com.victronenergy.pvinverter.tasmota_{instance}'
        self._dbusservice = VeDbusService(service_name, bus=self.bus, register=False)
        
        # Mandatory management paths
        self._dbusservice.add_path('/Mgmt/ProcessName', 'dbus-tasmota-pv.py')
        self._dbusservice.add_path('/Mgmt/ProcessVersion', '1.1')
        #self._dbusservice.add_path('/ProductId', 0xFFFF)
        self._dbusservice.add_path('/ProductName', f'Solar Tasmota {ip_address}')
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/DeviceInstance', instance)
        # Add these to make the "No product set" error go away in VRM
        self._dbusservice.add_path('/ProductId', 0xA144) # 0xA144 is a standard PV Inverter ID
        self._dbusservice.add_path('/ErrorCode', 0)
        self._dbusservice.add_path('/FirmwareVersion', '1.1')
        
        # Position: 0 = AC Input (Grid side), 1 = AC Output (Load side)
        self._dbusservice.add_path('/Position', 0)
        
        # AC Power Paths - initialized with 0
        self._dbusservice.add_path('/Ac/Power', 0.0)
        self._dbusservice.add_path('/Ac/L1/Power', 0.0)
        self._dbusservice.add_path('/Ac/L1/Voltage', 115.0) # Default to 115V for split-phase
        self._dbusservice.add_path('/Ac/L1/Current', 0.0)
        self._dbusservice.add_path('/Ac/Energy/Forward', 0.0)

        # Register service
        self._dbusservice.register()

        # Update loop: 2000ms
        GLib.timeout_add(2000, self._update)

    def _get_tasmota_data(self):
        try:
            response = requests.get(f'http://{self.ip}/cm?cmnd=Status%208', timeout=1.5)
            data = response.json()
            # Dynamic data from Status 8 / ENERGY
            energy = data['StatusSNS']['ENERGY']
            
            power = float(energy.get('Power', 0.0))
            voltage = float(energy.get('Voltage', 115.0)) # Pulling real voltage from Tasmota
            total = float(energy.get('Total', 0.0))
            
            # Calculate current based on real voltage
            current = round(power / voltage, 2) if voltage > 0 else 0.0
            
            return power, voltage, current, total
        except Exception:
            return 0.0, 115.0, 0.0, 0.0

    def _update(self):
        power, voltage, current, total = self._get_tasmota_data()
        
        # Update D-Bus values with real-time Tasmota data
        self._dbusservice['/Ac/Power'] = power
        self._dbusservice['/Ac/L1/Power'] = power
        self._dbusservice['/Ac/L1/Voltage'] = voltage
        self._dbusservice['/Ac/L1/Current'] = current
        self._dbusservice['/Ac/Energy/Forward'] = total
        
        return True 

if __name__ == "__main__":
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)

    # Instantiate your plugs with unique instances
    inv1 = TasmotaPVInverter('192.168.164.73', 120)
    inv2 = TasmotaPVInverter('192.168.164.74', 121)

    print("Dynamic PV Inverter emulation started (115V split-phase optimized).")
    
    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass

