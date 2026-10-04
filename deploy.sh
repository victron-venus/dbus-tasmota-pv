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

readonly SEPARATOR='=============================================='

SSH_HOST="${1:-Cerbo}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="/data/dbus-tasmota-pv"

echo "$SEPARATOR"
echo "  Deploying dbus-tasmota-pv to Venus OS"
echo "$SEPARATOR"
echo "SSH Host: $SSH_HOST"
echo ""

# Verify SSH host is reachable
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_HOST" "echo ok" >/dev/null 2>&1; then
    echo "Error: Cannot connect to $SSH_HOST" >&2
    exit 1
fi

# Stage the complete payload so a missing companion or interrupted transfer
# cannot overwrite the running driver. The installer validates it before stop.
REMOTE_STAGE=$(ssh "$SSH_HOST" 'mktemp -d /data/dbus-tasmota-pv-deploy.XXXXXX')
case "$REMOTE_STAGE" in
    /data/dbus-tasmota-pv-deploy.*) ;;
    *) echo 'Unexpected staging path' >&2; exit 1 ;;
esac
trap 'ssh "$SSH_HOST" "rm -rf -- $REMOTE_STAGE"' EXIT
echo ">>> Staging complete runtime..."
scp "$SCRIPT_DIR/dbus-tasmota-pv.py" "$SCRIPT_DIR/tasmota_settings.py" \
    "$SCRIPT_DIR/install.sh" "$SCRIPT_DIR/version" "$SCRIPT_DIR/gitHubInfo" \
    "$SCRIPT_DIR/setup" "$SCRIPT_DIR/README.md" "$SCRIPT_DIR/LICENSE" \
    "$SCRIPT_DIR/pyproject.toml" "$SCRIPT_DIR/uv.lock" "$SCRIPT_DIR/.python-version" \
    "$SSH_HOST:$REMOTE_STAGE/"

# Run install script
echo ""
echo ">>> Running install script on Venus OS..."
if ! ssh "$SSH_HOST" "sh $REMOTE_STAGE/install.sh"; then
    echo "Error: install script failed" >&2
    exit 1
fi

# Show status (wait for supervise to create its status file, svscan polls /service every ~5s)
echo ""
echo ">>> Service status:"
ssh "$SSH_HOST" "
    for i in \$(seq 1 20); do
        if [ -p /service/dbus-tasmota-pv/supervise/ok ]; then
            break
        fi
        sleep 1
    done
    svstat /service/dbus-tasmota-pv
"

echo ""
echo "$SEPARATOR"
echo "  Deployment Complete!"
echo "$SEPARATOR"
echo ""
echo "The service is now running and will auto-start on reboot."
echo ""
echo "To view error log:"
echo "  ssh $SSH_HOST 'tail -f /var/log/dbus-tasmota-pv/current'"
echo ""
