"""Exercise installer upgrades with real directory inodes and supervisor FIFOs."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("legacy", [False, True])
def test_installer_preserves_supervisor_inodes_and_boot_order(tmp_path, legacy):
    repo = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    source.mkdir()
    shutil.copy(repo / "dbus-tasmota-pv.py", source)
    installer = source / "install.sh"
    installer.write_text(
        re.sub(
            r"(?<![\w/}])(/data|/service|/var/log)",
            lambda match: str(tmp_path) + match.group(),
            (repo / "install.sh").read_text(),
        )
    )
    install_dir = tmp_path / "data/dbus-tasmota-pv"
    persistent = install_dir / "service/dbus-tasmota-pv"
    service = tmp_path / "service/dbus-tasmota-pv"
    service.parent.mkdir()
    initial = service if legacy else persistent
    for directory in (initial / "supervise", initial / "log/supervise"):
        directory.mkdir(parents=True)
        (directory / "lock").write_text("owned-by-supervisor")
        os.mkfifo(directory / "ok")
    if not legacy:
        service.symlink_to(persistent)
    directories = (initial, initial / "log", initial / "supervise", initial / "log/supervise")
    inodes = [path.stat().st_ino for path in directories]
    locks = [(path / "lock").stat().st_ino for path in directories[2:]]
    (tmp_path / "data").mkdir(exist_ok=True)
    rc = tmp_path / "data/rc.local"
    rc.write_text("#!/bin/sh\necho existing-task\nexit 0\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(sys.executable)
    for name, command in (
        ("id", "echo 0"),
        ("svc", "exit 0"),
        ("svstat", "exit 0"),
        ("multilog", "exit 0"),
        ("sleep", "exit 0"),
    ):
        executable = bin_dir / name
        executable.write_text("#!/bin/sh\n" + command + "\n")
        executable.chmod(0o755)
    stubs = tmp_path / "stubs"
    for directory in (stubs / "gi", stubs / "paho/mqtt"):
        directory.mkdir(parents=True)
    for name in ("gi/__init__.py", "paho/__init__.py", "paho/mqtt/__init__.py"):
        (stubs / name).write_text("")
    (stubs / "gi/repository.py").write_text("GLib = object()\n")
    (stubs / "vedbus.py").write_text("class VeDbusService: pass\n")
    (stubs / "paho/mqtt/client.py").write_text("CallbackAPIVersion = object()\n")
    environment = dict(
        os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], PYTHONPATH=str(stubs)
    )
    for _ in range(2):
        result = subprocess.run(
            ["sh", str(installer)], env=environment, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert service.is_symlink()
        preserved = (
            persistent,
            persistent / "log",
            persistent / "supervise",
            persistent / "log/supervise",
        )
        assert [path.stat().st_ino for path in preserved] == inodes
        assert [(path / "lock").stat().st_ino for path in preserved[2:]] == locks
        assert "exec 2>&1" in (service / "run").read_text()
        assert "s25000 n4" in (service / "log/run").read_text()
        assert not list(install_dir.glob("previous-service.*"))
        assert not list(install_dir.glob("service-stage.*"))
    boot = str(install_dir / "boot.sh")
    assert rc.read_text().splitlines().count(boot) == 1
    assert rc.read_text().index(boot) < rc.read_text().index("exit 0")
    assert "echo existing-task" in rc.read_text()


@pytest.mark.parametrize("installer_status", [0, 7])
def test_setuphelper_uses_native_installer_and_records_only_success(tmp_path, installer_status):
    repo = Path(__file__).resolve().parents[1]
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    (helpers / "IncludeHelpers").write_text(
        "scriptAction=INSTALL\npackageName=dbus-tasmota-pv\n"
        'scriptDir="$TEST_ROOT"\n'
        "logMessage() { :; }\n"
        'endScript() { touch "$TEST_ROOT/completed"; exit 0; }\n'
    )
    setup = tmp_path / "setup"
    setup.write_text(
        (repo / "setup")
        .read_text()
        .replace(
            "/data/SetupHelper/HelperResources/IncludeHelpers", str(helpers / "IncludeHelpers")
        )
    )
    (tmp_path / "install.sh").write_text(
        '#!/bin/sh\ntouch "$TEST_ROOT/installer-called"\n' + f"exit {installer_status}\n"
    )
    result = subprocess.run(
        ["bash", str(setup)],
        env=dict(os.environ, TEST_ROOT=str(tmp_path)),
        capture_output=True,
        check=False,
    )
    assert (tmp_path / "installer-called").exists()
    assert (result.returncode == 0) == (installer_status == 0)
    assert (tmp_path / "completed").exists() == (installer_status == 0)
