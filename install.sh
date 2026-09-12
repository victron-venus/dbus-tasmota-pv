#!/bin/sh
# Persistent Venus OS daemontools installation, using bundled Python libraries.
set -eu
INSTALL_DIR=/data/dbus-tasmota-pv
SERVICE_DATA_DIR=$INSTALL_DIR/service/dbus-tasmota-pv
SERVICE_DIR=/service/dbus-tasmota-pv
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo 'Run as root.' >&2; exit 1; }
command -v svc >/dev/null
command -v multilog >/dev/null
python3 - <<'PY'
import sys
sys.path.insert(0, '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService
from gi.repository import GLib
from paho.mqtt.client import CallbackAPIVersion
PY
mkdir -p "$INSTALL_DIR/service"
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    cp "$SCRIPT_DIR/dbus-tasmota-pv.py" "$INSTALL_DIR/"
fi
python3 -m py_compile "$INSTALL_DIR/dbus-tasmota-pv.py"
# Keep a fresh directory inode without copying supervise locks and FIFOs.
staging=$(mktemp -d "$INSTALL_DIR/service-stage.XXXXXX")
mkdir -p "$staging/log"
cat > "$staging/run" <<'EOF'
#!/bin/sh
exec 2>&1
cd /data/dbus-tasmota-pv || exit 1
exec python3 -u dbus-tasmota-pv.py
EOF
cat > "$staging/log/run" <<'EOF'
#!/bin/sh
exec 2>&1
mkdir -p /var/log/dbus-tasmota-pv
exec multilog t s25000 n4 /var/log/dbus-tasmota-pv
EOF
chmod +x "$staging/run" "$staging/log/run"
svc -dx "$SERVICE_DIR" "$SERVICE_DIR/log" 2>/dev/null || true
sleep 1
# Backups must be outside /service: svscan treats *.old as another service.
if [ -e "$SERVICE_DIR" ] && [ ! -L "$SERVICE_DIR" ]; then
    mv "$SERVICE_DIR" "$INSTALL_DIR/legacy-service.$(date +%s)"
fi
if [ -d "$SERVICE_DATA_DIR" ]; then
    mv "$SERVICE_DATA_DIR" "$INSTALL_DIR/previous-service.$(date +%s)"
fi
mv "$staging" "$SERVICE_DATA_DIR"
ln -sfn "$SERVICE_DATA_DIR" "$SERVICE_DIR"
cat > "$INSTALL_DIR/boot.sh" <<'EOF'
#!/bin/sh
[ -x /data/dbus-tasmota-pv/service/dbus-tasmota-pv/run ] || exit 0
ln -sfn /data/dbus-tasmota-pv/service/dbus-tasmota-pv /service/dbus-tasmota-pv
EOF
chmod +x "$INSTALL_DIR/boot.sh"
python3 - <<'PY'
from pathlib import Path
path = Path('/data/rc.local')
text = path.read_text() if path.exists() else '#!/bin/sh\n'
command = '/data/dbus-tasmota-pv/boot.sh'
if command not in text.splitlines():
    lines = text.splitlines()
    index = next((i for i, line in enumerate(lines) if line.strip() == 'exit 0'), len(lines))
    lines.insert(index, command)
    path.write_text('\n'.join(lines) + '\n')
path.chmod(path.stat().st_mode | 0o111)
PY
count=0
until [ -p "$SERVICE_DIR/supervise/ok" ] || [ "$count" -ge 15 ]; do
    sleep 1
    count=$((count + 1))
done
svc -u "$SERVICE_DIR"
svstat "$SERVICE_DIR" "$SERVICE_DIR/log"
echo 'Installed. Logs: /var/log/dbus-tasmota-pv/current (25 KB x 5 files).'
