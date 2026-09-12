"""Validate the published installer layout without contacting a Venus OS device."""

import ast
import hashlib
import os
import subprocess
import sys
import tarfile
from pathlib import Path


def test_release_archive_contains_working_service_contract(tmp_path: Path) -> None:
    """Build and unpack the actual release archive, including its launcher."""
    root = Path(__file__).resolve().parents[1]
    tag = (root / "version").read_text().strip()
    subprocess.run(["bash", str(root / "scripts/build-package.sh"), tag, str(tmp_path)], check=True)
    archive = tmp_path / f"dbus-tasmota-pv-{tag}.tar.gz"
    digest, filename = (tmp_path / "SHA256SUMS").read_text().split()
    assert filename == archive.name
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    with tarfile.open(archive) as package:
        package.extractall(tmp_path / "unpacked", filter="data")
    installed = tmp_path / "unpacked/dbus-tasmota-pv"
    for name in ("setup", "version", "gitHubInfo", "install.sh", "README.md", "LICENSE"):
        assert (installed / name).is_file()
    assert (installed / "version").read_text().strip() == tag
    module = ast.parse((installed / "dbus-tasmota-pv.py").read_text())
    versions = [
        node.value.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets)
    ]
    assert versions == [tag.removeprefix("v")]
    run = installed / "services/dbus-tasmota-pv/run"
    assert os.access(run, os.X_OK)
    assert "exec python3 dbus-tasmota-pv.py\n" in run.read_text()
    assert (installed / "services/dbus-tasmota-pv/log/run").is_file()
    subprocess.run(["bash", "-n", str(installed / "setup")], check=True)
    subprocess.run(["sh", "-n", str(run)], check=True)
    result = subprocess.run(
        [sys.executable, str(installed / "dbus-tasmota-pv.py"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--mqtt-host" in result.stdout
    assert "--config" not in result.stdout
