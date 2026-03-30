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

# Create service directory structure
echo ">>> Setting up daemontools service..."
mkdir -p "$SERVICE_DIR/log"
mkdir -p "$LOG_DIR"

# Create run script
cat > "$SERVICE_DIR/run" << 'EOF'
#!/bin/sh
exec 2>&1
cd /data/dbus-tasmota-pv
exec python3 dbus-tasmota-pv.py
EOF
chmod +x "$SERVICE_DIR/run"

# Create log run script
cat > "$SERVICE_DIR/log/run" << 'EOF'
#!/bin/sh
exec svlogd -tt /var/log/dbus-tasmota-pv
EOF
chmod +x "$SERVICE_DIR/log/run"

echo "Created service at $SERVICE_DIR"

# Ensure service starts on boot by adding to rc.local
RC_LOCAL="/data/rc.local"
RC_MARKER="# dbus-tasmota-pv service"

if [ ! -f "$RC_LOCAL" ]; then
    echo "Creating $RC_LOCAL..."
    cat > "$RC_LOCAL" << 'EOF'
#!/bin/bash
# Venus OS rc.local - runs at boot

EOF
    chmod +x "$RC_LOCAL"
fi

# Add service recreation to rc.local if not already there
if ! grep -q "$RC_MARKER" "$RC_LOCAL" 2>/dev/null; then
    echo "Adding service auto-start to $RC_LOCAL..."
    cat >> "$RC_LOCAL" << 'EOF'

# dbus-tasmota-pv service
if [ ! -d /service/dbus-tasmota-pv ]; then
    mkdir -p /service/dbus-tasmota-pv/log
    mkdir -p /var/log/dbus-tasmota-pv
    cat > /service/dbus-tasmota-pv/run << 'RUNEOF'
#!/bin/sh
exec 2>&1
cd /data/dbus-tasmota-pv
exec python3 dbus-tasmota-pv.py
RUNEOF
    chmod +x /service/dbus-tasmota-pv/run
    cat > /service/dbus-tasmota-pv/log/run << 'LOGEOF'
#!/bin/sh
exec svlogd -tt /var/log/dbus-tasmota-pv
LOGEOF
    chmod +x /service/dbus-tasmota-pv/log/run
fi
EOF
    echo "Added to $RC_LOCAL"
else
    echo "Service already configured in $RC_LOCAL"
fi

echo ""
echo "=============================================="
echo "  Installation Complete!"
echo "=============================================="
echo ""
echo "Service will start automatically now and on reboot."
echo ""
echo "Commands:"
echo "  Status:   svstat /service/dbus-tasmota-pv"
echo "  Restart:  svc -t /service/dbus-tasmota-pv"
echo "  Stop:     svc -d /service/dbus-tasmota-pv"
echo "  Logs:     tail -f /var/log/dbus-tasmota-pv/current | tai64nlocal"
echo ""
echo "To modify Tasmota plug IPs, edit: $INSTALL_DIR/dbus-tasmota-pv.py"
echo ""

# Start the service
svstat "$SERVICE_DIR" 2>/dev/null || echo "Service starting..."
