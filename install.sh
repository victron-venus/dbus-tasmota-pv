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
LOG_DIR="/var/log/dbus-tasmota-pv"

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

# Install default config if not present
if [[ -f "config.example.json" ]] && [[ ! -f "$INSTALL_DIR/config.json" ]]; then
    cp config.example.json "$INSTALL_DIR/config.json"
    echo "Created default config at $INSTALL_DIR/config.json"
    echo ">>> Edit $INSTALL_DIR/config.json to set your Tasmota device IPs!"
elif [[ -f "$INSTALL_DIR/config.json" ]]; then
    echo "Using existing $INSTALL_DIR/config.json"
fi

# Remove old symlink if exists and create proper directory
if [[ -L "$SERVICE_DIR" ]]; then
    echo "Removing old symlink..."
    rm -f "$SERVICE_DIR"
fi

# Create service directory structure
echo ">>> Setting up daemontools service..."
mkdir -p "$SERVICE_DIR"
mkdir -p "$LOG_DIR"

# Verify log directory is writable
if [[ ! -w "$LOG_DIR" ]]; then
    echo "Warning: Log directory $LOG_DIR is not writable" >&2
fi

# Clear stale error log from previous runs
: > /var/log/dbus-tasmota-pv.log 2>/dev/null || true

# Create run script (stderr to log file, stdout to /dev/null)
cat > "$SERVICE_DIR/run" << 'EOF'
#!/bin/sh
cd /data/dbus-tasmota-pv
exec python3 dbus-tasmota-pv.py --config /data/dbus-tasmota-pv/config.json 2>> /var/log/dbus-tasmota-pv.log > /dev/null
EOF
chmod +x "$SERVICE_DIR/run"

echo "Created service at $SERVICE_DIR"
echo ""
echo "Note: daemontools will automatically start this service on boot."
echo "No rc.local modification needed."

echo ""
echo "$SEPARATOR"
echo "  Installation Complete!"
echo "$SEPARATOR"
echo ""
echo "Service will start automatically now and on reboot."
echo "(daemontools handles auto-start, no rc.local needed)"
echo ""
echo "Commands:"
echo "  Status:   svstat /service/dbus-tasmota-pv"
echo "  Restart:  svc -t /service/dbus-tasmota-pv"
echo "  Stop:     svc -d /service/dbus-tasmota-pv"
echo "  Errors:   tail -f /var/log/dbus-tasmota-pv.log"
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
svstat "$SERVICE_DIR" 2>/dev/null || echo "Service starting..."
