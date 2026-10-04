#!/bin/sh
# Persistent Venus OS daemontools installation, using bundled Python libraries.
set -eu
INSTALL_DIR=/data/dbus-tasmota-pv
SERVICE_DATA_DIR=$INSTALL_DIR/service/dbus-tasmota-pv
SERVICE_DIR=/service/dbus-tasmota-pv
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo 'Run as root.' >&2; exit 1; }
command -v svc >/dev/null
command -v svstat >/dev/null
command -v multilog >/dev/null
python3 - <<'PY'
import sys
sys.path.insert(0, '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService
from settingsdevice import SettingsDevice
from gi.repository import GLib
from paho.mqtt.client import CallbackAPIVersion
PY
mkdir -p "$INSTALL_DIR/service"
# Validate the complete runtime before stopping the existing service. Keep
# supervisor directories in place; only owned payload and launcher files move.
staging=$(mktemp -d "$INSTALL_DIR/service-stage.XXXXXX")
trap 'rm -rf "$staging"' EXIT HUP INT TERM
cp "$SCRIPT_DIR/dbus-tasmota-pv.py" "$SCRIPT_DIR/tasmota_settings.py" "$staging/"
python3 -m py_compile "$staging/dbus-tasmota-pv.py" "$staging/tasmota_settings.py"
for name in version gitHubInfo setup install.sh README.md LICENSE pyproject.toml uv.lock .python-version; do
    if [ -f "$SCRIPT_DIR/$name" ]; then
        cp "$SCRIPT_DIR/$name" "$staging/$name"
    fi
done
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
stop_service() {
    svc -d "$1" 2>/dev/null || true
    count=0
    while svstat "$1" 2>/dev/null | grep -q ': up '; do
        if [ "$count" -ge 15 ]; then
            echo 'Existing service did not stop; runtime files were not replaced.' >&2
            return 1
        fi
        sleep 1
        count=$((count + 1))
    done
}
if [ -d "$SERVICE_DIR" ] && [ ! -L "$SERVICE_DIR" ]; then
    [ ! -e "$SERVICE_DATA_DIR" ] || {
        echo 'Conflicting legacy and persistent service directories; preserve both for review.' >&2
        exit 1
    }
    # Rename the legacy directory itself so its supervisor state survives.
    stop_service "$SERVICE_DIR"
    mv "$SERVICE_DIR" "$SERVICE_DATA_DIR"
fi
mkdir -p "$SERVICE_DATA_DIR/log"
stop_service "$SERVICE_DIR"
mv "$staging/dbus-tasmota-pv.py" "$staging/tasmota_settings.py" "$INSTALL_DIR/"
for name in version gitHubInfo setup install.sh README.md LICENSE pyproject.toml uv.lock .python-version; do
    if [ -f "$staging/$name" ]; then
        mv "$staging/$name" "$INSTALL_DIR/$name"
    fi
done
mv "$staging/run" "$SERVICE_DATA_DIR/run"
mv "$staging/log/run" "$SERVICE_DATA_DIR/log/run"
rm -f "$SERVICE_DATA_DIR/down"
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
svc -t "$SERVICE_DIR/log" 2>/dev/null || true
svc -u "$SERVICE_DIR/log" "$SERVICE_DIR"
svstat "$SERVICE_DIR" "$SERVICE_DIR/log"
echo 'Installed. Logs: /var/log/dbus-tasmota-pv/current (25 KB x 5 files).'
