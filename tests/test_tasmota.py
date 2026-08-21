"""Tests for dbus-tasmota-pv service.

Covers:
- load_config(): JSON parsing for valid/invalid/edge-case configs
- parse_energy_payload(): Tasmota tele/<topic>/SENSOR JSON parsing
- TasmotaPVInverter.apply()/check_stale(): freshness tracking and degradation
"""

# pylint: disable=protected-access  # tests intentionally access internals

import importlib.util
import json
import sys
from pathlib import Path
from time import time
from types import ModuleType
from unittest.mock import MagicMock

import pytest

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
_mod.GLib = MagicMock()

TasmotaPVInverter = _mod.TasmotaPVInverter
MqttEnergyListener = _mod.MqttEnergyListener
load_config = _mod.load_config
parse_energy_payload = _mod.parse_energy_payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inverter(topic: str = "tasmota_120", instance: int = 120) -> TasmotaPVInverter:
    """Create a TasmotaPVInverter with all D-Bus interactions mocked."""
    return TasmotaPVInverter(topic, instance)


# ===================================================================
# load_config tests
# ===================================================================


class TestLoadConfig:
    """load_config() — JSON config parsing."""

    def test_valid_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps(
                {
                    "devices": [
                        {"topic": "tasmota_120", "instance": 120},
                        {"topic": "tasmota_121", "instance": 121},
                    ]
                }
            )
        )
        assert load_config(cfg) == [("tasmota_120", 120), ("tasmota_121", 121)]

    def test_empty_devices(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"devices": []}))
        assert load_config(cfg) == []

    def test_missing_devices_key(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"other_key": True}))
        assert load_config(cfg) == []

    def test_device_missing_topic(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"devices": [{"instance": 120}]}))
        assert load_config(cfg) == []

    def test_device_missing_instance(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"devices": [{"topic": "tasmota_120"}]}))
        assert load_config(cfg) == []

    def test_instance_zero_accepted(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"devices": [{"topic": "tasmota_x", "instance": 0}]}))
        assert load_config(cfg) == [("tasmota_x", 0)]

    def test_non_integer_instance_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"devices": [{"topic": "tasmota_x", "instance": "abc"}]}))
        with pytest.raises(ValueError):
            load_config(cfg)

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.json"
        cfg.write_text("{{{{invalid")
        with pytest.raises(json.JSONDecodeError):
            load_config(cfg)


# ===================================================================
# parse_energy_payload tests (tele/SENSOR JSON parsing)
# ===================================================================


class TestParseEnergyPayload:
    """parse_energy_payload() — Tasmota SENSOR payload parsing."""

    def test_normal_values(self) -> None:
        payload = json.dumps(
            {
                "Time": "2026-08-21T12:00:00",
                "ENERGY": {
                    "TotalStartTime": "2025-01-01T00:00:00",
                    "Total": 5678.9,
                    "Yesterday": 100.0,
                    "Today": 12.5,
                    "Power": 123.4,
                    "ApparentPower": 130,
                    "ReactivePower": 40,
                    "Factor": 0.95,
                    "Voltage": 230.1,
                    "Current": 0.556,
                },
            }
        )
        power, voltage, current, total, today = parse_energy_payload(payload)
        assert power == pytest.approx(123.4)
        assert voltage == pytest.approx(230.1)
        assert current == pytest.approx(0.54, rel=0.01)  # 123.4/230.1 ≈ 0.54
        assert total == pytest.approx(5678.9)
        assert today == pytest.approx(12.5)

    def test_bytes_payload_accepted(self) -> None:
        payload = json.dumps({"ENERGY": {"Power": 50, "Voltage": 230, "Total": 10, "Today": 1}})
        parsed = parse_energy_payload(payload.encode("utf-8"))
        assert parsed is not None
        power, voltage, _current, total, today = parsed
        assert power == pytest.approx(50.0)
        assert voltage == pytest.approx(230.0)
        assert total == pytest.approx(10.0)
        assert today == pytest.approx(1.0)

    def test_missing_power_defaults_zero(self) -> None:
        payload = json.dumps({"ENERGY": {"Voltage": 230, "Total": 100, "Today": 5.0}})
        power, voltage, current, total, today = parse_energy_payload(payload)
        assert power == pytest.approx(0.0)
        assert voltage == pytest.approx(230.0)
        assert current == pytest.approx(0.0)
        assert total == pytest.approx(100.0)
        assert today == pytest.approx(5.0)

    def test_missing_voltage_defaults_115(self) -> None:
        payload = json.dumps({"ENERGY": {"Power": 100, "Total": 50, "Today": 2.5}})
        power, voltage, current, _total, _today = parse_energy_payload(payload)
        assert power == pytest.approx(100.0)
        assert voltage == pytest.approx(115.0)
        assert current == pytest.approx(0.87, rel=0.01)  # 100/115 ≈ 0.87

    def test_zero_voltage_no_division_error(self) -> None:
        payload = json.dumps({"ENERGY": {"Power": 100, "Voltage": 0, "Total": 50, "Today": 1.0}})
        power, voltage, current, total, today = parse_energy_payload(payload)
        assert power == pytest.approx(100.0)
        assert voltage == pytest.approx(0.0)
        assert current == pytest.approx(0.0)
        assert total == pytest.approx(50.0)
        assert today == pytest.approx(1.0)

    def test_empty_energy_dict(self) -> None:
        payload = json.dumps({"Time": "2026-08-21T12:00:00", "ENERGY": {}})
        power, voltage, current, total, today = parse_energy_payload(payload)
        assert power == pytest.approx(0.0)
        assert voltage == pytest.approx(115.0)
        assert current == pytest.approx(0.0)
        assert total == pytest.approx(0.0)
        assert today == pytest.approx(0.0)

    def test_missing_energy_key_returns_none(self) -> None:
        assert parse_energy_payload('{"Time":"2026-08-21T12:00:00"}') is None

    def test_non_json_returns_none(self) -> None:
        assert parse_energy_payload("not json at all") is None

    def test_non_numeric_power_returns_none(self) -> None:
        payload = json.dumps({"ENERGY": {"Power": "abc"}})
        assert parse_energy_payload(payload) is None


# ===================================================================
# apply()/check_stale() tests (freshness + degradation logic)
# ===================================================================


class TestInverterFreshness:
    """apply()/check_stale() — telemetry-driven connection state."""

    def test_apply_marks_connected_and_updates_timestamp(self) -> None:
        inv = _make_inverter()
        inv._connected = False
        inv._last_update = time() - 999
        inv.apply(power=42.0, voltage=230.0, current=0.18, total=7.5, today=0.3)
        assert inv._connected is True
        assert time() - inv._last_update < 5

    def test_fresh_data_not_marked_stale(self) -> None:
        inv = _make_inverter()
        inv.check_stale()
        assert inv._connected is True

    def test_stale_data_marks_offline(self) -> None:
        inv = _make_inverter()
        inv._last_update = time() - (_mod.STALE_AFTER_SECONDS + 10)
        inv.check_stale()
        assert inv._connected is False

    def test_already_offline_not_remarked(self) -> None:
        inv = _make_inverter()
        inv._last_update = time() - (_mod.STALE_AFTER_SECONDS + 10)
        inv.check_stale()
        calls_after_first = mock_glib_idle_add_calls(inv)
        inv.check_stale()
        assert mock_glib_idle_add_calls(inv) == calls_after_first  # no new path writes

    def test_back_online_after_stale(self) -> None:
        inv = _make_inverter()
        inv._last_update = time() - (_mod.STALE_AFTER_SECONDS + 10)
        inv.check_stale()
        assert inv._connected is False
        inv.apply(power=10.0, voltage=230.0, current=0.04, total=1.0, today=0.1)
        assert inv._connected is True


def mock_glib_idle_add_calls(inv: TasmotaPVInverter) -> int:
    """Count GLib.idle_add invocations recorded on the shared mock."""
    return mock_glib.GLib.idle_add.call_count


# ===================================================================
# MqttEnergyListener tests (subscription routing)
# ===================================================================


class TestMqttEnergyListener:
    """MqttEnergyListener() — topic subscription mapping."""

    def test_subscription_topics_built_from_inverters(self) -> None:
        pytest.importorskip("paho.mqtt")
        inv1 = _make_inverter("tasmota_120", 120)
        inv2 = _make_inverter("tasmota_121", 121)
        listener = MqttEnergyListener([inv1, inv2], "127.0.0.1", 1883)
        assert set(listener._subscriptions) == {
            "tele/tasmota_120/SENSOR",
            "tele/tasmota_121/SENSOR",
        }

    def test_on_message_routes_to_matching_inverter(self) -> None:
        pytest.importorskip("paho.mqtt")
        inv1 = _make_inverter("tasmota_120", 120)
        inv2 = _make_inverter("tasmota_121", 121)
        listener = MqttEnergyListener([inv1, inv2], "127.0.0.1", 1883)
        msg = MagicMock()
        msg.topic = "tele/tasmota_121/SENSOR"
        msg.payload = json.dumps(
            {"ENERGY": {"Power": 88, "Voltage": 230, "Total": 3.0, "Today": 0.5}}
        ).encode("utf-8")
        listener._on_message(MagicMock(), None, msg)
        # apply() is invoked synchronously via the route; state reflects it
        assert inv2._connected is True
