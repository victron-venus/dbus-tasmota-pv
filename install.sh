#!/bin/bash
#
# dbus-tasmota-pv installer for Venus OS
# Creates a proper daemontools service that survives reboot
#
# Usage: ./install.sh
#

set -e

INSTALL_DIR="/data/dbus-tasmota-pv"
SERVICE_DIR="/service/dbus-tasmota-pv"
LOG_DIR="/var/log/dbus-tasmota-pv"

echo "=============================================="
echo "  dbus-tasmota-pv Installer for Venus OS"
echo "=============================================="
echo ""

# Check for required files
if [ ! -f "dbus-tasmota-pv.py" ] && [ ! -f "$INSTALL_DIR/dbus-tasmota-pv.py" ]; then
    echo "Error: dbus-tasmota-pv.py not found" >&2
    exit 1
fi

# Create install directory
mkdir -p "$INSTALL_DIR"

# Copy Python script (skip if already in target directory)
if [ -f "dbus-tasmota-pv.py" ] && [ "$(pwd)" != "$INSTALL_DIR" ]; then
    cp dbus-tasmota-pv.py "$INSTALL_DIR/"
    chmod +x "$INSTALL_DIR/dbus-tasmota-pv.py"
    echo "Copied dbus-tasmota-pv.py to $INSTALL_DIR"
elif [ -f "$INSTALL_DIR/dbus-tasmota-pv.py" ]; then
    chmod +x "$INSTALL_DIR/dbus-tasmota-pv.py"
    echo "Using existing $INSTALL_DIR/dbus-tasmota-pv.py"
fi

# Remove old symlink if exists and create proper directory
if [ -L "$SERVICE_DIR" ]; then
    echo "Removing old symlink..."
    rm -f "$SERVICE_DIR"
fi

# Create service directory structure
echo ">>> Setting up daemontools service..."
mkdir -p "$SERVICE_DIR"
mkdir -p "$LOG_DIR"

# Verify log directory is writable
if [ ! -w "$LOG_DIR" ]; then
    echo "Warning: Log directory $LOG_DIR is not writable" >&2
fi

# Create run script (stderr to log file, stdout to /dev/null)
cat > "$SERVICE_DIR/run" << 'EOF'
#!/bin/sh
cd /data/dbus-tasmota-pv
exec python3 dbus-tasmota-pv.py 2>> /var/log/dbus-tasmota-pv.log > /dev/null
EOF
chmod +x "$SERVICE_DIR/run"

echo "Created service at $SERVICE_DIR"
echo ""
echo "Note: daemontools will automatically start this service on boot."
echo "No rc.local modification needed."

echo ""
echo "=============================================="
echo "  Installation Complete!"
echo "=============================================="
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

# Show service status
sleep 1
svstat "$SERVICE_DIR" 2>/dev/null || echo "Service starting..."
