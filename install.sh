#!/bin/bash
#
# dbus-tasmota-pv installer for Venus OS
# Creates a proper daemontools service that survives reboot
#
# Usage: ./install.sh
#

set -e

readonly SEPARATOR='=============================================='

INSTALL_DIR="/data/dbus-tasmota-pv"
SERVICE_DIR="/service/dbus-tasmota-pv"

echo "$SEPARATOR"
echo "  dbus-tasmota-pv Installer for Venus OS"
echo "$SEPARATOR"
echo ""

# Check for required files
if [[ ! -f "dbus-tasmota-pv.py" ]] && [[ ! -f "$INSTALL_DIR/dbus-tasmota-pv.py" ]]; then
    echo "Error: dbus-tasmota-pv.py not found" >&2
    exit 1
fi

# Create install directory
mkdir -p "$INSTALL_DIR"

# Copy Python script (skip if already in target directory)
if [[ -f "dbus-tasmota-pv.py" ]] && [[ "$(pwd)" != "$INSTALL_DIR" ]]; then
    cp dbus-tasmota-pv.py "$INSTALL_DIR/"
    chmod +x "$INSTALL_DIR/dbus-tasmota-pv.py"
    echo "Copied dbus-tasmota-pv.py to $INSTALL_DIR"
elif [[ -f "$INSTALL_DIR/dbus-tasmota-pv.py" ]]; then
    chmod +x "$INSTALL_DIR/dbus-tasmota-pv.py"
    echo "Using existing $INSTALL_DIR/dbus-tasmota-pv.py"
fi

# Devices are auto-discovered via MQTT (tele/+/SENSOR); no config file needed.
# Clean up a config left behind by a previous (<3.0.0) install.
if [[ -f "$INSTALL_DIR/config.json" ]]; then
    rm "$INSTALL_DIR/config.json"
    echo "Removed obsolete $INSTALL_DIR/config.json (devices are now auto-discovered)"
fi

# Remove old symlink if exists and create proper directory
if [[ -L "$SERVICE_DIR" ]]; then
    echo "Removing old symlink..."
    rm -f "$SERVICE_DIR"
fi

# Create service directory structure in /data (persists across reboots)
SERVICE_DATA_DIR="/data/dbus-tasmota-pv/service/dbus-tasmota-pv"
echo ">>> Setting up daemontools service in $SERVICE_DATA_DIR..."
mkdir -p "$SERVICE_DATA_DIR/log"

# Run script: stdout/stderr are captured by the paired multilog (log/run
# below), matching the stock Venus OS service layout. A plain-file redirect
# here leaves the service without a usable log/run, which spams readproctitle
# with "unable to start log/run" on every supervise restart.
cat > "$SERVICE_DATA_DIR/run" << 'EOF'
#!/bin/sh
cd /data/dbus-tasmota-pv || exit 1
exec python3 dbus-tasmota-pv.py
EOF
chmod +x "$SERVICE_DATA_DIR/run"

cat > "$SERVICE_DATA_DIR/log/run" << 'EOF'
#!/bin/sh
exec multilog t s25000 n4 /var/log/dbus-tasmota-pv
EOF
chmod +x "$SERVICE_DATA_DIR/log/run"

# Create /service symlink (will be recreated by rc.local on boot).
# A pre-3.0 install left a real directory at $SERVICE_DIR; `ln -sf` cannot
# replace it, leaving the old run script crashlooping. Move it aside instead.
if [[ -d "$SERVICE_DIR" && ! -L "$SERVICE_DIR" ]]; then
    echo ">>> Replacing legacy service directory at $SERVICE_DIR..."
    mv "$SERVICE_DIR" "${SERVICE_DIR}.old.$(date +%s)"
fi
ln -sf "$SERVICE_DATA_DIR" "$SERVICE_DIR"

# svscan caches whether a service has a log pair when it first sees the
# directory; an entry created before log/run existed never gains one until
# its supervise process is restarted (svscan then respawns the full pair).
if [[ -f "$SERVICE_DIR/supervise/pid" && ! -p "$SERVICE_DIR/log/supervise/ok" ]]; then
    echo ">>> Restarting supervise so svscan picks up the log pair..."
    kill "$(cat "$SERVICE_DIR/supervise/pid")" 2>/dev/null || true
fi

echo "Created service at $SERVICE_DIR"
echo ""

# Add rc.local entry for boot persistence
RC_LOCAL="/data/rc.local"
if [ ! -f "$RC_LOCAL" ]; then
    echo "#!/bin/sh" > "$RC_LOCAL"
    chmod +x "$RC_LOCAL"
fi

if ! grep -q "dbus-tasmota-pv" "$RC_LOCAL" 2>/dev/null; then
    cat >> "$RC_LOCAL" << 'EOF'

# === dbus-tasmota-pv service persistence ===
# Recreate /service symlink on boot (lost since /service is tmpfs)
ln -sf /data/dbus-tasmota-pv/service/dbus-tasmota-pv /service/dbus-tasmota-pv
sleep 2
svc -u /service/dbus-tasmota-pv 2>/dev/null || true
# === end dbus-tasmota-pv ===

EOF
    echo "Added boot persistence to $RC_LOCAL"
else
    echo "Boot persistence already configured in $RC_LOCAL"
fi

echo "Note: Service will auto-start on boot via rc.local."

echo ""
echo "$SEPARATOR"
echo "  Installation Complete!"
echo "$SEPARATOR"
echo ""
echo "Service will start automatically now and on reboot."
echo "(rc.local recreates /service symlink on boot since /service is tmpfs)"
echo ""
echo "Commands:"
echo "  Status:   svstat /service/dbus-tasmota-pv"
echo "  Restart:  svc -t /service/dbus-tasmota-pv"
echo "  Stop:     svc -d /service/dbus-tasmota-pv"
echo "  Errors:   tail -f /var/log/dbus-tasmota-pv/current"
echo ""

# Wait for daemontools to pick up the new service.  svscan polls /service
# every ~5s, so svstat too early would fail with "unable to open
# supervise/ok".  Poll for the FIFO that supervise creates on startup.
for _ in $(seq 1 20); do
    if [[ -p "$SERVICE_DIR/supervise/ok" ]]; then
        break
    fi
    sleep 1
done

# Show service status
svstat "$SERVICE_DIR" "$SERVICE_DIR/log" 2>/dev/null || echo "Service starting..."
