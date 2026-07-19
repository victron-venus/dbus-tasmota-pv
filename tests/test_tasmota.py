"""Tests for dbus-tasmota-pv service.

Covers:
- load_config(): YAML parsing for valid/invalid/edge-case configs
- _get_tasmota_data(): HTTP response parsing (power, voltage, current, total)
- _handle_failure(): degradation after N consecutive failures
"""
# pylint: disable=protected-access  # tests intentionally access internals

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
import requests
import yaml

# ---------------------------------------------------------------------------
# Mock Venus OS dependencies before importing the service module.
# On dev machines VELIB_PATH does not exist, so the module sets all Venus OS
# symbols to None.  We need working mocks for TasmotaPVInverter.__init__.
# ---------------------------------------------------------------------------
for mod_name in ("dbus", "dbus.mainloop", "dbus.mainloop.glib", "gi", "gi.repository"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = ModuleType(mod_name)

sys.modules["vedbus"] = ModuleType("vedbus")
sys.modules["vedbus"].VeDbusService = MagicMock  # type: ignore[attr-defined]

mock_glib = ModuleType("gi.repository")
mock_glib.GLib = MagicMock()
sys.modules["gi.repository"] = mock_glib

# The source file has hyphens in its name, so use importlib to load it.
_src = Path(__file__).resolve().parent.parent / "dbus-tasmota-pv.py"
_spec = importlib.util.spec_from_file_location("dbus_tasmota_pv", _src)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["dbus_tasmota_pv"] = _mod
_spec.loader.exec_module(_mod)

# Patch Venus OS symbols that were set to None during module load
_mod.dbus = MagicMock()
_mod.VeDbusService = MagicMock()
_mod.HTTPAdapter = MagicMock()

TasmotaPVInverter = _mod.TasmotaPVInverter
load_config = _mod.load_config

MAX_CONSECUTIVE_FAILURES = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inverter(ip: str = "192.168.1.100", instance: int = 120) -> TasmotaPVInverter:  # noqa: S104
    """Create a TasmotaPVInverter with all D-Bus interactions mocked."""
    session = MagicMock()
    inv = TasmotaPVInverter(ip, instance, session)
    inv._session = session
    return inv


# ===================================================================
# load_config tests
# ===================================================================


class TestLoadConfig:
    """load_config() — YAML config parsing."""

    def test_valid_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(
            yaml.dump(
                {
                    "devices": [
                        {"ip": "192.168.1.100", "instance": 120},
                        {"ip": "192.168.1.101", "instance": 121},
                    ]
                }
            )
        )
        assert load_config(cfg) == [("192.168.1.100", 120), ("192.168.1.101", 121)]

    def test_empty_devices(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(yaml.dump({"devices": []}))
        assert load_config(cfg) == []

    def test_missing_devices_key(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(yaml.dump({"other_key": True}))
        assert load_config(cfg) == []

    def test_device_missing_ip(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(yaml.dump({"devices": [{"instance": 120}]}))
        assert load_config(cfg) == []

    def test_device_missing_instance(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(yaml.dump({"devices": [{"ip": "1.2.3.4"}]}))
        assert load_config(cfg) == []

    def test_instance_zero_accepted(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(yaml.dump({"devices": [{"ip": "1.2.3.4", "instance": 0}]}))
        assert load_config(cfg) == [("1.2.3.4", 0)]

    def test_non_integer_instance_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(yaml.dump({"devices": [{"ip": "1.2.3.4", "instance": "abc"}]}))
        with pytest.raises(ValueError):
            load_config(cfg)

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("{{{{invalid yaml")
        with pytest.raises(yaml.YAMLError):
            load_config(cfg)


# ===================================================================
# _get_tasmota_data tests (HTTP response parsing)
# ===================================================================


class TestParseTasmotaResponse:
    """_get_tasmota_data() — Tasmota HTTP response parsing."""

    def test_normal_values(self) -> None:
        inv = _make_inverter()
        inv._session.get.return_value.json.return_value = {
            "StatusSNS": {"ENERGY": {"Power": 123.4, "Voltage": 230.1, "Total": 5678.9}}
        }
        inv._session.get.return_value.raise_for_status = MagicMock()
        result = inv._get_tasmota_data()
        assert result is not None
        power, voltage, current, total = result
        assert power == pytest.approx(123.4)
        assert voltage == pytest.approx(230.1)
        assert current == pytest.approx(0.54, rel=0.01)  # 123.4/230.1 ≈ 0.54
        assert total == pytest.approx(5678.9)

    def test_missing_power_defaults_zero(self) -> None:
        inv = _make_inverter()
        inv._session.get.return_value.json.return_value = {
            "StatusSNS": {"ENERGY": {"Voltage": 230, "Total": 100}}
        }
        inv._session.get.return_value.raise_for_status = MagicMock()
        power, voltage, current, total = inv._get_tasmota_data()
        assert power == pytest.approx(0.0)
        assert voltage == pytest.approx(230.0)
        assert current == pytest.approx(0.0)
        assert total == pytest.approx(100.0)

    def test_missing_voltage_defaults_115(self) -> None:
        inv = _make_inverter()
        inv._session.get.return_value.json.return_value = {
            "StatusSNS": {"ENERGY": {"Power": 100, "Total": 50}}
        }
        inv._session.get.return_value.raise_for_status = MagicMock()
        power, voltage, current, _total = inv._get_tasmota_data()
        assert power == pytest.approx(100.0)
        assert voltage == pytest.approx(115.0)
        assert current == pytest.approx(0.87, rel=0.01)  # 100/115 ≈ 0.87

    def test_zero_voltage_no_division_error(self) -> None:
        inv = _make_inverter()
        inv._session.get.return_value.json.return_value = {
            "StatusSNS": {"ENERGY": {"Power": 100, "Voltage": 0, "Total": 50}}
        }
        inv._session.get.return_value.raise_for_status = MagicMock()
        power, voltage, current, total = inv._get_tasmota_data()
        assert power == pytest.approx(100.0)
        assert voltage == pytest.approx(0.0)
        assert current == pytest.approx(0.0)
        assert total == pytest.approx(50.0)

    def test_empty_energy_dict(self) -> None:
        inv = _make_inverter()
        inv._session.get.return_value.json.return_value = {"StatusSNS": {"ENERGY": {}}}
        inv._session.get.return_value.raise_for_status = MagicMock()
        power, voltage, current, total = inv._get_tasmota_data()
        assert power == pytest.approx(0.0)
        assert voltage == pytest.approx(115.0)
        assert current == pytest.approx(0.0)
        assert total == pytest.approx(0.0)

    def test_missing_statussns_returns_none(self) -> None:
        inv = _make_inverter()
        inv._session.get.return_value.json.return_value = {}
        inv._session.get.return_value.raise_for_status = MagicMock()
        assert inv._get_tasmota_data() is None

    def test_timeout_returns_none(self) -> None:
        inv = _make_inverter()
        inv._session.get.side_effect = requests.exceptions.Timeout
        assert inv._get_tasmota_data() is None

    def test_connection_error_returns_none(self) -> None:
        inv = _make_inverter()
        inv._session.get.side_effect = requests.exceptions.ConnectionError
        assert inv._get_tasmota_data() is None

    def test_http_error_returns_none(self) -> None:
        inv = _make_inverter()
        inv._session.get.return_value.raise_for_status.side_effect = Exception("500")
        assert inv._get_tasmota_data() is None

    def test_non_json_returns_none(self) -> None:
        inv = _make_inverter()
        inv._session.get.return_value.json.side_effect = ValueError("No JSON")
        assert inv._get_tasmota_data() is None


# ===================================================================
# _handle_failure tests (degradation logic)
# ===================================================================


class TestHandleFailure:
    """_handle_failure() — consecutive failure tracking and degradation."""

    def test_first_failure_increments(self) -> None:
        inv = _make_inverter()
        assert inv._consecutive_failures == 0
        inv._handle_failure("timeout")
        assert inv._consecutive_failures == 1
        assert inv._connected is True  # still connected after 1 failure

    def test_five_failures_mark_offline(self) -> None:
        inv = _make_inverter()
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            inv._handle_failure("timeout")
        assert inv._consecutive_failures == MAX_CONSECUTIVE_FAILURES
        assert inv._connected is False

    def test_success_resets_count(self) -> None:
        inv = _make_inverter()
        for _ in range(3):
            inv._handle_failure("timeout")
        assert inv._consecutive_failures == 3
        # Simulate successful fetch
        inv._session.get.return_value.json.return_value = {
            "StatusSNS": {"ENERGY": {"Power": 100, "Voltage": 230, "Total": 50}}
        }
        inv._session.get.return_value.raise_for_status = MagicMock()
        inv._get_tasmota_data()
        assert inv._consecutive_failures == 0
        assert inv._connected is True

    def test_failure_count_grows_unbounded(self) -> None:
        inv = _make_inverter()
        for _ in range(31):
            inv._handle_failure("timeout")
        assert inv._consecutive_failures == 31
        assert inv._connected is False

    def test_mixed_failures_then_success(self) -> None:
        inv = _make_inverter()
        for _ in range(10):
            inv._handle_failure("timeout")
        # Reset via success
        inv._session.get.return_value.json.return_value = {
            "StatusSNS": {"ENERGY": {"Power": 50, "Voltage": 230, "Total": 20}}
        }
        inv._session.get.return_value.raise_for_status = MagicMock()
        inv._get_tasmota_data()
        assert inv._consecutive_failures == 0
        # Fail again
        for _ in range(2):
            inv._handle_failure("error")
        assert inv._consecutive_failures == 2
        assert inv._connected is True  # 2 < 5
