#!/bin/bash
#
# Deploy dbus-tasmota-pv to Venus OS
#
# Prerequisites:
#   - SSH config with host 'Cerbo' pointing to Venus OS device
#   - SSH key authentication configured
#
# Usage: ./deploy.sh [SSH_HOST]
#

set -e

SSH_HOST="${1:-Cerbo}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="/data/dbus-tasmota-pv"

echo "=============================================="
echo "  Deploying dbus-tasmota-pv to Venus OS"
echo "=============================================="
echo "SSH Host: $SSH_HOST"
echo ""

# Verify SSH host is reachable
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_HOST" "echo ok" >/dev/null 2>&1; then
    echo "Error: Cannot connect to $SSH_HOST" >&2
    exit 1
fi

# Create directory on remote
echo ">>> Creating directory..."
ssh "$SSH_HOST" "mkdir -p $REMOTE_DIR"

# Copy files
echo ">>> Copying files..."
scp "$SCRIPT_DIR/dbus-tasmota-pv.py" "$SSH_HOST:$REMOTE_DIR/"
scp "$SCRIPT_DIR/install.sh" "$SSH_HOST:$REMOTE_DIR/"

# Make executable
ssh "$SSH_HOST" "chmod +x $REMOTE_DIR/*.py $REMOTE_DIR/install.sh"

# Run install script
echo ""
echo ">>> Running install script on Venus OS..."
if ! ssh "$SSH_HOST" "cd $REMOTE_DIR && ./install.sh"; then
    echo "Error: install script failed" >&2
    exit 1
fi

# Show status
echo ""
echo ">>> Service status:"
ssh "$SSH_HOST" "sleep 2 && svstat /service/dbus-tasmota-pv"

echo ""
echo "=============================================="
echo "  Deployment Complete!"
echo "=============================================="
echo ""
echo "The service is now running and will auto-start on reboot."
echo ""
echo "To view error log:"
echo "  ssh $SSH_HOST 'tail -f /var/log/dbus-tasmota-pv.log'"
echo ""
