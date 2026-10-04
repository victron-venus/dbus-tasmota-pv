"""Tests for dbus-tasmota-pv service.

Covers:
- topic_from_mqtt_topic()/stable_instance(): MQTT discovery helpers
- parse_energy_payload(): Tasmota tele/<topic>/SENSOR JSON parsing
- MqttEnergyListener: dynamic device discovery from tele/+/SENSOR messages
- TasmotaPVInverter.apply()/check_stale(): freshness tracking and degradation
"""

# pylint: disable=protected-access  # tests intentionally access internals

import importlib.util
import json
import sys
from pathlib import Path
from time import monotonic as time
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
sys.path.insert(0, str(_src.parent))
_spec = importlib.util.spec_from_file_location("dbus_tasmota_pv", _src)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["dbus_tasmota_pv"] = _mod
_spec.loader.exec_module(_mod)

# Patch Venus OS symbols that were set to None during module load
_mod.dbus = MagicMock()
_mod.VeDbusService = MagicMock()
_mod.GLib = MagicMock()
_mod.GLib.idle_add.side_effect = lambda callback, *args: callback(*args)


class MemorySettings:
    """Runtime fixture; persistent settings have separate contract tests."""

    def __init__(self, bus, topic, instance, *, on_change):
        self.instance = instance
        self.custom_name = f"Solar Tasmota {topic}"
        self.position = 0
        self.phase = 1
        self.on_change = on_change

    def _set(self, field, value):
        old = getattr(self, field)
        setattr(self, field, value)
        self.on_change(field, old, value)
        return True

    def set_custom_name(self, value):
        return self._set("custom_name", value)

    def set_position(self, value):
        return self._set("position", value)

    def set_phase(self, value):
        return self._set("phase", value)


@pytest.fixture(autouse=True)
def runtime_dependencies(monkeypatch):
    monkeypatch.setattr(_mod, "TasmotaSettings", MemorySettings)

    def service(*_args, **_kwargs):
        result = MagicMock()
        result.__enter__.return_value = result
        return result

    monkeypatch.setattr(_mod, "VeDbusService", service)


TasmotaPVInverter = _mod.TasmotaPVInverter
MqttEnergyListener = _mod.MqttEnergyListener
parse_energy_payload = _mod.parse_energy_payload
topic_from_mqtt_topic = _mod.topic_from_mqtt_topic
stable_instance = _mod.stable_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inverter(topic: str = "tasmota_120", instance: int = 120) -> TasmotaPVInverter:
    """Create a TasmotaPVInverter with all D-Bus interactions mocked."""
    inv = TasmotaPVInverter(topic, instance)
    inv.apply(10.0, 230.0, 0.1, 1.0, 0.1, 0.0)
    return inv


def _sensor_msg(topic: str, energy: dict | None) -> MagicMock:
    """Build a mock paho message on tele/<topic>/SENSOR."""
    msg = MagicMock()
    msg.topic = f"tele/{topic}/SENSOR"
    msg.retain = False
    if energy is None:
        msg.payload = b"not json at all"
    else:
        msg.payload = json.dumps({"ENERGY": energy}).encode("utf-8")
    return msg


# ===================================================================
# discovery helper tests
# ===================================================================


class TestDiscoveryHelpers:
    """topic_from_mqtt_topic()/stable_instance()."""

    def test_extracts_topic_from_sensor_message(self) -> None:
        assert topic_from_mqtt_topic("tele/tasmota_120/SENSOR") == "tasmota_120"

    def test_topic_with_slashes_rejected(self) -> None:
        # Nested topics would break the 3-part pattern
        assert topic_from_mqtt_topic("tele/a/b/SENSOR") is None

    def test_stat_and_result_topics_rejected(self) -> None:
        assert topic_from_mqtt_topic("stat/tasmota_120/RESULT") is None

    def test_empty_topic_rejected(self) -> None:
        assert topic_from_mqtt_topic("tele//SENSOR") is None

    def test_stable_instance_deterministic(self) -> None:
        assert stable_instance("tasmota_120", set()) == stable_instance("tasmota_120", set())

    def test_stable_instance_avoids_collision(self) -> None:
        base = stable_instance("tasmota_120", set())
        assert stable_instance("tasmota_120", {base}) != base
        assert stable_instance("tasmota_120", {base}) == base + 1


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
        power, voltage, current, total, today, yesterday = parse_energy_payload(payload)
        assert power == pytest.approx(123.4)
        assert voltage == pytest.approx(230.1)
        assert current == pytest.approx(0.556)
        assert total == pytest.approx(5678.9)
        assert today == pytest.approx(12.5)
        assert yesterday == pytest.approx(100.0)

    def test_bytes_payload_accepted(self) -> None:
        payload = json.dumps({"ENERGY": {"Power": 50, "Voltage": 230, "Total": 10, "Today": 1}})
        parsed = parse_energy_payload(payload.encode("utf-8"))
        assert parsed is not None
        power, voltage, _current, total, today, yesterday = parsed
        assert power == pytest.approx(50.0)
        assert voltage == pytest.approx(230.0)
        assert total == pytest.approx(10.0)
        assert today == pytest.approx(1.0)
        assert yesterday == pytest.approx(0.0)

    def test_missing_power_is_not_a_fresh_measurement(self) -> None:
        payload = json.dumps({"ENERGY": {"Voltage": 230, "Total": 100, "Today": 5.0}})
        assert parse_energy_payload(payload) is None

    def test_missing_voltage_defaults_115(self) -> None:
        payload = json.dumps({"ENERGY": {"Power": 100, "Total": 50, "Today": 2.5}})
        power, voltage, current, _total, _today, _yesterday = parse_energy_payload(payload)
        assert power == pytest.approx(100.0)
        assert voltage == pytest.approx(115.0)
        assert current is None

    def test_zero_voltage_no_division_error(self) -> None:
        payload = json.dumps({"ENERGY": {"Power": 100, "Voltage": 0, "Total": 50, "Today": 1.0}})
        power, voltage, current, total, today, _yesterday = parse_energy_payload(payload)
        assert power == pytest.approx(100.0)
        assert voltage == pytest.approx(0.0)
        assert current is None
        assert total == pytest.approx(50.0)
        assert today == pytest.approx(1.0)

    def test_negative_voltage_is_not_a_fresh_measurement(self) -> None:
        payload = json.dumps({"ENERGY": {"Power": 100, "Voltage": -115, "Total": 50, "Today": 1.0}})
        assert parse_energy_payload(payload) is None

    def test_null_voltage_key_is_not_a_fresh_measurement(self) -> None:
        payload = json.dumps({"ENERGY": {"Power": 100, "Voltage": None, "Total": 50, "Today": 1.0}})
        assert parse_energy_payload(payload) is None

    def test_empty_energy_dict(self) -> None:
        assert parse_energy_payload('{"ENERGY": {}}') is None

    @pytest.mark.parametrize("energy", [None, [], "oops", {"Power": "nan"}, {"Power": "inf"}])
    def test_invalid_energy_is_ignored(self, energy) -> None:
        assert parse_energy_payload(json.dumps({"ENERGY": energy})) is None

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
        inv.apply(power=42.0, voltage=230.0, current=0.18, total=7.5, today=0.3, yesterday=0.9)
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
        inv.apply(power=10.0, voltage=230.0, current=0.04, total=1.0, today=0.1, yesterday=0.5)
        assert inv._connected is True


def mock_glib_idle_add_calls(inv: TasmotaPVInverter) -> int:
    """Count GLib.idle_add invocations recorded on the shared mock."""
    return mock_glib.GLib.idle_add.call_count


# ===================================================================
# MqttEnergyListener tests (auto-discovery via tele/+/SENSOR)
# ===================================================================


class TestMqttDiscovery:
    """MqttEnergyListener() — dynamic device discovery."""

    def _listener(self) -> MqttEnergyListener:
        pytest.importorskip("paho.mqtt")
        return MqttEnergyListener("127.0.0.1", 1883)

    def test_new_device_discovered_on_first_message(self) -> None:
        listener = self._listener()
        assert listener.inverters() == []
        listener._on_message(MagicMock(), None, _sensor_msg("tasmota_120", {"Power": 50}))
        discovered = listener.inverters()
        assert len(discovered) == 1
        assert discovered[0].topic == "tasmota_120"

    def test_second_message_reuses_same_inverter(self) -> None:
        listener = self._listener()
        listener._on_message(MagicMock(), None, _sensor_msg("tasmota_120", {"Power": 10}))
        first = listener.inverters()[0]
        listener._on_message(MagicMock(), None, _sensor_msg("tasmota_120", {"Power": 20}))
        assert listener.inverters() == [first]

    def test_distinct_devices_get_distinct_instances(self) -> None:
        listener = self._listener()
        for topic in ("tasmota_a", "tasmota_b", "tasmota_c"):
            listener._on_message(MagicMock(), None, _sensor_msg(topic, {"Power": 5}))
        instances = [inv.instance for inv in listener.inverters()]
        assert len(set(instances)) == 3

    def test_unparseable_payload_does_not_register_device(self) -> None:
        listener = self._listener()
        listener._on_message(MagicMock(), None, _sensor_msg("not_a_meter", None))
        assert listener.inverters() == []

    def test_off_pattern_topic_ignored(self) -> None:
        listener = self._listener()
        msg = MagicMock()
        msg.topic = "stat/tasmota_120/RESULT"
        msg.payload = json.dumps({"ENERGY": {"Power": 5}}).encode("utf-8")
        listener._on_message(MagicMock(), None, msg)
        assert listener.inverters() == []

    def test_on_connect_subscribes_wildcard(self) -> None:
        listener = self._listener()
        client = MagicMock()
        client.subscribe.return_value = (0, 1)
        listener._on_connect(client, None, {}, MagicMock(is_failure=False), None)
        client.subscribe.assert_called_once_with(
            [(listener.DISCOVERY_FILTER, 0), (listener.LWT_FILTER, 0)]
        )

    def test_failed_connect_does_not_subscribe(self) -> None:
        listener = self._listener()
        client = MagicMock()
        reason = MagicMock()
        reason.is_failure = True
        listener._on_connect(client, None, {}, reason, None)
        client.subscribe.assert_not_called()

    def test_telemetry_applied_to_discovered_inverter(self) -> None:
        listener = self._listener()
        listener._on_message(
            MagicMock(), None, _sensor_msg("tasmota_120", {"Power": 88, "Voltage": 230})
        )
        inv = listener.inverters()[0]
        assert inv._connected is True
        assert time() - inv._last_update < 5


def test_discovery_and_writes_wait_for_glib(monkeypatch):
    monkeypatch.setattr(_mod, "MqttClient", MagicMock())
    monkeypatch.setattr(_mod, "CallbackAPIVersion", MagicMock())
    pending = []
    monkeypatch.setattr(_mod.GLib, "idle_add", pending.append)
    listener = MqttEnergyListener("127.0.0.1", 1883)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 20}))
    assert listener.inverters() == []
    assert len(pending) == 1
    dispatch_result = pending.pop()()
    assert dispatch_result is False
    inverter = listener.inverters()[0]
    inverter._dbusservice.__setitem__.assert_any_call("/Ac/Power", 20.0)


def test_stale_reading_invalidates_current_and_voltage():
    inv = _make_inverter()
    inv._last_update = time() - 100
    inv.check_stale()
    for path in ("/Ac/Power", "/Ac/L1/Current", "/Ac/L1/Voltage"):
        inv._dbusservice.__setitem__.assert_any_call(path, None)


@pytest.mark.parametrize(
    "energy",
    [
        {"Power": 10**400},
        {"Power": 1, "Voltage": 10**400},
        {"Power": 1, "Total": 10**400},
        {"Power": 1, "Today": 10**400},
        {"Power": 1, "Yesterday": 10**400},
        {"Power": 1, "Current": 10**400},
    ],
)
def test_nonrepresentable_energy_rejected(energy):
    assert parse_energy_payload(json.dumps({"ENERGY": energy})) is None


@pytest.mark.parametrize("delay", [90.001, 300.0])
def test_expired_queued_telemetry_does_not_discover_device(monkeypatch, delay):
    now = [100.0]
    monkeypatch.setattr(_mod, "monotonic", lambda: now[0])
    pending = []
    monkeypatch.setattr(_mod.GLib, "idle_add", pending.append)
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    now[0] += delay
    dispatch_result = pending.pop()()
    assert dispatch_result is False
    assert listener.inverters() == []


def test_expired_queued_telemetry_cannot_revive_existing_device(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(_mod, "monotonic", lambda: now[0])
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    inverter = listener.inverters()[0]
    pending = []
    monkeypatch.setattr(_mod.GLib, "idle_add", pending.append)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 20}))
    now[0] = 191.0
    inverter.check_stale()
    inverter._dbusservice.__setitem__.reset_mock()
    dispatch_result = pending.pop()()
    assert dispatch_result is False
    assert not inverter._connected
    inverter._dbusservice.__setitem__.assert_not_called()

    listener._on_message(None, None, _sensor_msg("plug", {"Power": 30}))
    dispatch_result = pending.pop()()
    assert dispatch_result is False
    assert inverter._connected
    inverter._dbusservice.__setitem__.assert_any_call("/Ac/Power", 30.0)


def test_coalesced_power_expires_from_latest_receipt(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(_mod, "monotonic", lambda: now[0])
    pending = []
    monkeypatch.setattr(_mod.GLib, "idle_add", pending.append)
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    now[0] = 150.0
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 20}))
    assert len(pending) == 1
    now[0] = 200.0
    dispatch_result = pending.pop()()
    assert dispatch_result is False
    inverter = listener.inverters()[0]
    assert inverter._connected
    inverter._dbusservice.__setitem__.assert_any_call("/Ac/Power", 20.0)
    now[0] = 240.0
    inverter.check_stale()
    assert inverter._connected
    now[0] += 0.001
    inverter.check_stale()
    assert not inverter._connected


def test_power_that_expires_during_registration_is_never_published(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(_mod, "monotonic", lambda: now[0])
    pending = []
    monkeypatch.setattr(_mod.GLib, "idle_add", pending.append)
    listener = MqttEnergyListener("localhost", 1883)
    original = listener._get_or_create

    def create(topic):
        inverter = original(topic)
        inverter._dbusservice.__setitem__.reset_mock()
        now[0] += 2
        return inverter

    monkeypatch.setattr(listener, "_get_or_create", create)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    now[0] = 189.0
    dispatch_result = pending.pop()()
    assert dispatch_result is False
    inverter = listener.inverters()[0]
    assert not inverter._connected
    power_writes = [
        value
        for (path, value), _ in inverter._dbusservice.__setitem__.call_args_list
        if path == "/Ac/Power"
    ]
    assert power_writes == []  # Registered paths already contain unknown values.


@pytest.mark.parametrize("invalid_energy", [{"Power": 10**400}, {"Power": 1, "Current": "inf"}])
def test_invalid_numeric_message_preserves_state_and_next_sample(monkeypatch, invalid_energy):
    now = [100.0]
    monkeypatch.setattr(_mod, "monotonic", lambda: now[0])
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    inverter = listener.inverters()[0]
    inverter._dbusservice.__setitem__.reset_mock()
    now[0] = 150.0
    listener._on_message(None, None, _sensor_msg("plug", invalid_energy))
    assert inverter._last_update == 100.0
    inverter._dbusservice.__setitem__.assert_not_called()
    listener._on_message(
        None, None, _sensor_msg("plug", {"Power": 20, "Voltage": 250, "Current": 0.16})
    )
    assert listener.inverters() == [inverter]
    assert inverter._last_update == 150.0
    inverter._dbusservice.__setitem__.assert_any_call("/Ac/Power", 20.0)
    inverter._dbusservice.__setitem__.assert_any_call("/Ac/L1/Current", 0.16)


@pytest.mark.parametrize("energy", [None, [], "invalid", 42, True])
def test_non_object_energy_does_not_interrupt_following_telemetry(energy, monkeypatch) -> None:
    """Malformed ENERGY blocks must not escape the MQTT callback."""
    monkeypatch.setattr(_mod, "MqttClient", MagicMock())
    monkeypatch.setattr(_mod, "CallbackAPIVersion", MagicMock())
    monkeypatch.setattr(_mod, "monotonic", lambda: 100.0)
    listener = MqttEnergyListener("localhost", 1883)
    listener._get_or_create = MagicMock()
    invalid = MagicMock(topic="tele/plug/SENSOR")
    invalid.retain = False
    invalid.payload = json.dumps({"ENERGY": energy}).encode()
    listener._on_message(None, None, invalid)
    listener._get_or_create.assert_not_called()

    listener._on_message(None, None, _sensor_msg("plug", {"Power": 125, "Voltage": 250}))
    listener._get_or_create.assert_called_once_with("plug")
    listener._get_or_create.return_value.apply.assert_called_once_with(
        125.0, 250.0, None, 0.0, 0.0, 0.0, received_at=100.0
    )


def test_registration_failure_requires_restart_but_existing_devices_still_update(
    monkeypatch, runtime_service, tmp_path
):
    """Never recreate partial SettingsDevice trackers in the same process."""
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _sensor_msg("existing", {"Power": 10}))
    existing = listener.inverters()[0]
    settings_factory = MagicMock(wraps=MemorySettings)
    monkeypatch.setattr(_mod, "TasmotaSettings", settings_factory)

    def failing_service(*args, **kwargs):
        service = RuntimeService(*args, **kwargs)
        service.register = MagicMock(side_effect=RuntimeError("registration failure"))
        return service

    monkeypatch.setattr(_mod, "VeDbusService", failing_service)
    queued = []
    monkeypatch.setattr(_mod.GLib, "idle_add", queued.append)
    listener._on_message(None, None, _sensor_msg("new", {"Power": 20}))
    listener._on_message(None, None, _sensor_msg("existing", {"Power": 30}))
    keep_scheduled = queued.pop()()
    assert keep_scheduled is False
    assert listener.inverters() == [existing]
    assert existing._dbusservice["/Ac/Power"] == 30
    assert not listener.healthy()
    listener._on_message(None, None, _sensor_msg("new", {"Power": 40}))
    queued.pop()()
    assert settings_factory.call_count == 1
    quit_loop = MagicMock()
    heartbeat = tmp_path / "alive"
    assert not _mod._make_tick(listener, str(heartbeat), quit_loop)()
    quit_loop.assert_called_once()
    assert not heartbeat.exists()

    monkeypatch.setattr(_mod, "VeDbusService", RuntimeService)
    restarted = MqttEnergyListener("localhost", 1883)
    restarted._on_message(None, None, _sensor_msg("new", {"Power": 50}))
    queued.pop()()
    assert restarted.inverters()[0]._dbusservice["/Ac/Power"] == 50


class RuntimeService:
    """In-memory D-Bus service with explicit batches and injectable write faults."""

    def __init__(self, *_args, **_kwargs):
        self.values = {}
        self.callbacks = {}
        self.batches = []
        self.current_batch = None
        self.fail_path = None

    def add_path(self, path, value, **kwargs):
        self.values[path] = value
        if "onchangecallback" in kwargs:
            self.callbacks[path] = kwargs["onchangecallback"]

    def register(self):
        pass

    def __getitem__(self, path):
        return self.values[path]

    def __contains__(self, path):
        return path in self.values

    def __enter__(self):
        assert self.current_batch is None
        self.current_batch = {}
        return self

    def __exit__(self, *_args):
        self.batches.append(self.current_batch)
        self.current_batch = None

    def __setitem__(self, path, value):
        assert self.current_batch is not None, "measurement writes must be batched"
        if self.fail_path == path:
            self.fail_path = None
            raise RuntimeError("synthetic D-Bus failure")
        self.current_batch[path] = value
        self.values[path] = value


@pytest.fixture
def runtime_service(monkeypatch):
    monkeypatch.setattr(_mod, "VeDbusService", RuntimeService)


def _lwt_msg(topic, payload=b"Offline", retain=False):
    msg = MagicMock(topic=f"tele/{topic}/LWT", payload=payload, retain=retain)
    return msg


def test_retained_power_never_discovers_or_revives(runtime_service):
    listener = MqttEnergyListener("localhost", 1883)
    cached = _sensor_msg("plug", {"Power": 777})
    cached.retain = True
    listener._on_message(None, None, cached)
    assert listener.inverters() == []
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    inverter = listener.inverters()[0]
    inverter.mark_offline()
    listener._on_message(None, None, cached)
    listener._on_message(None, None, _lwt_msg("plug", b"Online", retain=True))
    assert inverter._dbusservice["/Connected"] == 0
    assert inverter._dbusservice["/Ac/Power"] is None


def test_lwt_offline_wins_over_queued_sensor_and_online_waits_for_measurement(
    runtime_service, monkeypatch
):
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    inverter = listener.inverters()[0]
    queued = []
    monkeypatch.setattr(_mod.GLib, "idle_add", queued.append)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 20}))
    listener._on_message(None, None, _lwt_msg("plug", retain=True))
    listener._on_message(None, None, _lwt_msg("plug", b"Online"))
    assert len(queued) == 1
    queued.pop()()
    assert inverter._dbusservice["/Connected"] == 0
    assert inverter._dbusservice["/Ac/Power"] is None
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 30}))
    queued.pop()()
    assert inverter._dbusservice["/Ac/Power"] == 30


def test_offline_for_unknown_device_does_not_create_service():
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _lwt_msg("plug", retain=True))
    assert listener.inverters() == []


@pytest.mark.parametrize("current", [-0.1, "nan", "inf", True, [], 10**400])
def test_invalid_measured_current_rejects_reading(current):
    assert parse_energy_payload(json.dumps({"ENERGY": {"Power": 9, "Current": current}})) is None


def test_measured_rms_current_preserved_at_low_power_factor():
    reading = parse_energy_payload(
        json.dumps({"ENERGY": {"Power": 9, "Voltage": 123, "Current": 0.289, "Factor": 0.25}})
    )
    assert reading[2] == 0.289
    assert parse_energy_payload('{"ENERGY":{"Power":9,"Current":null}}')[2] is None


@pytest.mark.parametrize("payload", [b"[" * 20000 + b"0" + b"]" * 20000, b" " * 65537, b"\xff"])
def test_malformed_payload_does_not_escape_real_paho_callback(payload, runtime_service):
    from paho.mqtt.client import MQTTMessage

    listener = MqttEnergyListener("localhost", 1883)
    message = MQTTMessage(topic=b"tele/plug/SENSOR")
    message.payload = payload
    listener._client._handle_on_message(message)
    assert listener.inverters() == []
    message.payload = b'{"ENERGY":{"Power":10}}'
    listener._client._handle_on_message(message)
    assert listener.inverters()[0]._dbusservice["/Ac/Power"] == 10


def test_failed_offline_write_is_retried_on_next_tick(runtime_service, tmp_path):
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    inverter = listener.inverters()[0]
    inverter._dbusservice.fail_path = "/Connected"
    listener._on_message(None, None, _lwt_msg("plug"))
    assert inverter._connected
    assert inverter._offline_requested
    assert inverter._dbusservice["/Connected"] == 1
    assert _mod._make_tick(listener, str(tmp_path / "alive"))()
    assert not inverter._connected
    assert inverter._dbusservice["/Connected"] == 0
    assert inverter._dbusservice["/Ac/Power"] is None


def test_one_failed_apply_preserves_other_device_and_invalidates_partial_update(
    runtime_service, monkeypatch, tmp_path
):
    listener = MqttEnergyListener("localhost", 1883)
    for topic in ("first", "second"):
        listener._on_message(None, None, _sensor_msg(topic, {"Power": 10}))
    first, second = listener.inverters()
    first._dbusservice.fail_path = "/Ac/Power"
    queued = []
    monkeypatch.setattr(_mod.GLib, "idle_add", queued.append)
    listener._on_message(None, None, _sensor_msg("first", {"Power": 20}))
    listener._on_message(None, None, _sensor_msg("second", {"Power": 30}))
    keep_scheduled = queued.pop()()
    assert keep_scheduled is False
    assert second._dbusservice["/Ac/Power"] == 30
    assert first._offline_requested
    _mod._make_tick(listener, str(tmp_path / "alive"))()
    assert first._dbusservice["/Ac/Power"] is None


def test_failed_idle_schedule_recovers_on_following_sample(runtime_service, monkeypatch):
    listener = MqttEnergyListener("localhost", 1883)
    monkeypatch.setattr(_mod.GLib, "idle_add", MagicMock(side_effect=RuntimeError("GLib fault")))
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    assert not listener._pending_scheduled
    monkeypatch.setattr(_mod.GLib, "idle_add", lambda callback: callback())
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 20}))
    assert listener.inverters()[0]._dbusservice["/Ac/Power"] == 20


def test_worker_death_quits_without_writing_a_healthy_heartbeat(tmp_path):
    listener = MqttEnergyListener("localhost", 1883)
    listener._started = True
    listener._client._thread = None
    quit_loop = MagicMock()
    heartbeat = tmp_path / "alive"
    assert _mod._make_tick(listener, str(heartbeat), quit_loop)() is False
    quit_loop.assert_called_once()
    assert not heartbeat.exists()
    assert "worker stopped" in listener.failure_reason


def test_living_worker_is_healthy_during_broker_reconnect():
    listener = MqttEnergyListener("localhost", 1883)
    listener._started = True
    listener._client._thread = MagicMock()
    listener._client._thread.is_alive.return_value = True
    assert not listener._client.is_connected()
    assert listener.healthy()


def test_invalid_diagnostics_name_field_and_are_rate_limited(monkeypatch, caplog):
    clock = [100.0]
    monkeypatch.setattr(_mod, "monotonic", lambda: clock[0])
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    invalid = _sensor_msg("plug", {"Power": 10, "Voltage": None})
    for _ in range(10):
        listener._on_message(None, None, invalid)
    warnings = [record.message for record in caplog.records if "invalid SENSOR" in record.message]
    assert len(warnings) == 1
    assert "ENERGY.Voltage" in warnings[0]
    clock[0] += 60
    listener._on_message(None, None, invalid)
    assert "9 invalid messages suppressed" in caplog.records[-1].message


def test_phase_change_moves_fresh_sample_in_one_batch_and_preserves_total(runtime_service):
    inverter = _make_inverter()
    service = inverter._dbusservice
    assert service["/Role"] == "pvinverter"
    assert service["/AllowedRoles"] == ["pvinverter"]
    assert "/NrOfPhases" not in service  # Classic GUI otherwise assumes L1.
    assert "/Ac/Phase" not in service  # Classic and GUI-v2 use different numbering.
    assert service.callbacks["/PhaseSetting"]("/PhaseSetting", 3)
    assert service["/PhaseSetting"] == 3
    assert service["/Ac/L1/Power"] is None
    assert service["/Ac/L3/Power"] == service["/Ac/Power"] == 10
    assert service["/Ac/L3/Current"] == 0.1
    assert service.batches[-1]["/Ac/L1/Power"] is None
    assert service.batches[-1]["/Ac/L3/Power"] == 10
    assert service["/Ac/L3/Energy/Forward"] == service["/Ac/Energy/Forward"] == 1
    assert service["/Ac/L1/Energy/Forward"] is None
    inverter.mark_offline()
    assert service["/Ac/L3/Energy/Forward"] == 1
    service.callbacks["/PhaseSetting"]("/PhaseSetting", 2)
    assert all(service[f"/Ac/L{phase}/Power"] is None for phase in (1, 2, 3))
    assert service["/Connected"] == 0
    assert service["/Ac/L2/Energy/Forward"] == 1
    assert service["/Ac/L3/Energy/Forward"] is None


def test_name_and_position_writes_use_settings_and_instance_change_requests_restart(
    runtime_service,
):
    listener = MqttEnergyListener("localhost", 1883)
    listener._on_message(None, None, _sensor_msg("plug", {"Power": 10}))
    inverter = listener.inverters()[0]
    service = inverter._dbusservice
    service.callbacks["/CustomName"]("/CustomName", "Roof solar")
    service.callbacks["/Position"]("/Position", 1)
    assert inverter.settings.custom_name == service["/CustomName"] == "Roof solar"
    assert inverter.settings.position == service["/Position"] == 1
    inverter.settings._set("instance", 900)
    assert not listener.healthy()
    assert "instance changed" in listener.failure_reason


def test_real_network_worker_survives_nested_json_and_delivers_next_sample(
    runtime_service, monkeypatch
):
    """Exercise paho's actual socket loop against a local minimal MQTT broker."""
    import socket
    import threading

    def read_exact(connection, count):
        data = b""
        while len(data) < count:
            chunk = connection.recv(count - len(data))
            if not chunk:
                raise EOFError("MQTT connection closed")
            data += chunk
        return data

    def read_packet(connection):
        header = read_exact(connection, 1)
        remaining = 0
        for shift in range(0, 28, 7):
            byte = read_exact(connection, 1)[0]
            remaining += (byte & 127) << shift
            if byte < 128:
                return header, read_exact(connection, remaining)
        raise ValueError("Malformed MQTT packet length")

    def publish(payload):
        topic = b"tele/network-test/SENSOR"
        body = len(topic).to_bytes(2, "big") + topic + payload
        remaining = len(body)
        encoded = b""
        while True:
            byte = remaining % 128
            remaining //= 128
            encoded += bytes([byte | (128 if remaining else 0)])
            if not remaining:
                return b"\x30" + encoded + body

    queued = []
    sample_received = threading.Event()
    broker_errors = []

    def idle_add(callback):
        queued.append(callback)
        sample_received.set()

    monkeypatch.setattr(_mod.GLib, "idle_add", idle_add)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(5)

        def broker():
            try:
                connection, _address = server.accept()
                with connection:
                    connection.settimeout(5)
                    assert read_packet(connection)[0] == b"\x10"  # CONNECT
                    connection.sendall(b"\x20\x02\x00\x00")  # CONNACK
                    header, subscribe = read_packet(connection)
                    assert header == b"\x82"
                    # Both SENSOR and LWT filters are in a single SUBSCRIBE.
                    connection.sendall(b"\x90\x04" + subscribe[:2] + b"\x00\x00")
                    connection.sendall(publish(b"[" * 20000 + b"0" + b"]" * 20000))
                    connection.sendall(publish(b'{"ENERGY":{"Power":42,"Current":0.29}}'))
                    assert read_packet(connection)[0] == b"\xe0"  # graceful DISCONNECT
            except (AssertionError, OSError, EOFError, ValueError) as error:
                broker_errors.append(error)
                sample_received.set()

        broker_thread = threading.Thread(target=broker, daemon=True)
        broker_thread.start()
        listener = MqttEnergyListener("127.0.0.1", server.getsockname()[1])
        try:
            listener.start()
            assert sample_received.wait(5), "live telemetry did not reach the GLib queue"
            assert broker_errors == []
            assert listener.healthy()
            assert listener._client._thread.is_alive()
            assert listener.inverters() == []
            keep_scheduled = queued.pop()()
            assert keep_scheduled is False
            assert listener.inverters()[0]._dbusservice["/Ac/Power"] == 42
        finally:
            listener.stop()
            broker_thread.join(timeout=5)
        assert not broker_thread.is_alive()
        assert broker_errors == []
