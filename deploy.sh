#!/bin/bash
#
# Deploy dbus-tasmota-pv to Venus OS
#
# Prerequisites:
#   - SSH config with host 'r' pointing to Venus OS device
#   - SSH key authentication configured
#
# Usage: ./deploy.sh [SSH_HOST]
#

set -e

SSH_HOST="${1:-r}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="/data/dbus-tasmota-pv"

echo "=============================================="
echo "  Deploying dbus-tasmota-pv to Venus OS"
echo "=============================================="
echo "SSH Host: $SSH_HOST"
echo ""

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
ssh "$SSH_HOST" "cd $REMOTE_DIR && ./install.sh"

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
echo "To view logs:"
echo "  ssh $SSH_HOST 'tail -f /var/log/dbus-tasmota-pv/current | tai64nlocal'"
echo ""
