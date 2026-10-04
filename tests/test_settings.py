"""Persistent settings contracts without a Venus OS D-Bus dependency."""

import re
import zlib
from typing import Any

import pytest

from tasmota_settings import TasmotaSettings, settings_path


class LocalSettings:
    """In-memory service implementing native instance reservation semantics."""

    def __init__(self):
        self.values: dict[str, Any] = {}
        self.fail_add = False
        self.fail_write = False
        self.omit_field = None
        self.clients = []

    def factory(self, *, bus, supportedSettings, eventCallback, timeout):
        if self.fail_add:
            raise RuntimeError("localsettings unavailable")
        paths = {}
        for field, (path, default, _minimum, _maximum) in supportedSettings.items():
            if field == self.omit_field:
                continue
            paths[field] = path
            if path not in self.values:
                if field == "instance":
                    role, preferred = default.split(":")
                    candidate = int(preferred)
                    reserved = {
                        value
                        for key, value in self.values.items()
                        if key.endswith("/ClassAndVrmInstance")
                    }
                    while f"{role}:{candidate}" in reserved:
                        candidate += 1
                    default = f"{role}:{candidate}"
                self.values[path] = default
        client = SettingsClient(self, paths, eventCallback)
        self.clients.append(client)
        return client

    def device(self, topic, default_instance=None, **kwargs):
        if default_instance is None:
            default_instance = zlib.crc32(topic.encode()) % 10000
        return TasmotaSettings(
            object(), topic, default_instance, settings_factory=self.factory, **kwargs
        )


class SettingsClient:
    def __init__(self, service, paths, callback):
        self.service = service
        self.paths = paths
        self.callback = callback

    def __getitem__(self, field):
        return self.service.values[self.paths[field]]

    def __setitem__(self, field, value):
        if self.service.fail_write:
            raise RuntimeError("D-Bus write failed")
        self.service.values[self.paths[field]] = value

    def notify(self, field, value):
        old = self[field]
        self.service.values[self.paths[field]] = value
        self.callback(field, old, value)


def test_preserves_legacy_ids_and_persistent_user_settings():
    service = LocalSettings()
    first = service.device("tasmota_120")
    second = service.device("tasmota_121")
    assert (first.instance, second.instance) == (369, 9895)
    assert first.set_position(2)
    assert first.set_phase(3)
    assert first.set_custom_name("Roof west")
    restarted = service.device("tasmota_120", 500)
    assert (restarted.instance, restarted.position, restarted.phase, restarted.custom_name) == (
        369,
        2,
        3,
        "Roof west",
    )


def test_collision_allocation_survives_reversed_discovery_order():
    service = LocalSettings()
    first = service.device("tasmota_67")
    second = service.device("tasmota_158")
    assert (first.instance, second.instance) == (3508, 3509)
    restarted_second = service.device("tasmota_158")
    restarted_first = service.device("tasmota_67")
    assert (restarted_first.instance, restarted_second.instance) == (3508, 3509)


def test_native_allocation_respects_other_pv_drivers():
    service = LocalSettings()
    service.values["/Settings/Devices/shelly_other/ClassAndVrmInstance"] = "pvinverter:369"
    service.values["/Settings/Devices/grid_other/ClassAndVrmInstance"] = "grid:370"
    assert service.device("tasmota_120").instance == 370


@pytest.mark.parametrize("topic", ["plug", "with spaces", "hyphen-name", "é屋顶", "a/b", "a_b"])
def test_topic_encoding_produces_stable_unambiguous_valid_dbus_path(topic):
    path = settings_path(topic)
    assert re.fullmatch(r"/Settings/Devices/tasmota_[a-z0-9]+", path)
    assert bytes.fromhex(path.rsplit("_", 1)[-1]).decode() == topic
    assert settings_path(topic) == path


@pytest.mark.parametrize("topic", ["", None, 1])
def test_invalid_topic_rejected(topic):
    with pytest.raises(ValueError):
        settings_path(topic)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("position", -1),
        ("position", 3),
        ("position", True),
        ("position", 1.0),
        ("phase", 0),
        ("phase", 4),
        ("phase", "2"),
        ("custom_name", None),
        ("custom_name", "invalid\0name"),
        ("custom_name", "\ud800"),
    ],
)
def test_invalid_writes_do_not_change_persistent_or_published_settings(field, invalid):
    service = LocalSettings()
    settings = service.device("plug")
    before = dict(service.values)
    assert getattr(settings, "set_" + field)(invalid) is False
    assert service.values == before


def test_local_write_callback_is_immediate_and_signal_is_deduplicated():
    service = LocalSettings()
    changes = []
    settings = service.device("plug", on_change=lambda *args: changes.append(args))
    assert settings.set_phase(2)
    assert settings.phase == 2
    assert changes == [("phase", 1, 2)]
    service.clients[-1].notify("phase", 2)
    assert changes == [("phase", 1, 2)]


def test_external_changes_include_reallocated_instance():
    service = LocalSettings()
    changes = []
    settings = service.device("plug", 20, on_change=lambda *args: changes.append(args))
    client = service.clients[-1]
    client.notify("instance", "pvinverter:25")
    client.notify("position", 1)
    client.notify("custom_name", "Garage")
    assert (settings.instance, settings.position, settings.custom_name) == (25, 1, "Garage")
    assert changes == [
        ("instance", 20, 25),
        ("position", 0, 1),
        ("custom_name", "Solar Tasmota plug", "Garage"),
    ]


@pytest.mark.parametrize(
    "invalid", ["grid:1", "pvinverter:-1", "pvinverter:abc", "pvinverter:32768", None]
)
def test_invalid_external_identity_is_not_published(invalid):
    service = LocalSettings()
    changes = []
    settings = service.device("plug", 20, on_change=lambda *args: changes.append(args))
    service.clients[-1].notify("instance", invalid)
    assert settings.instance == 20
    assert changes == []


def test_failed_write_keeps_current_state_and_can_be_retried():
    service = LocalSettings()
    changes = []
    settings = service.device("plug", on_change=lambda *args: changes.append(args))
    service.fail_write = True
    assert not settings.set_position(1)
    assert settings.position == 0
    assert changes == []
    service.fail_write = False
    assert settings.set_position(1)
    assert settings.position == 1


def test_unavailable_settings_fail_discovery_until_retry():
    service = LocalSettings()
    service.fail_add = True
    with pytest.raises(RuntimeError, match="unavailable"):
        service.device("plug")
    service.fail_add = False
    assert service.device("plug").position == 0


def test_partial_addsettings_failure_is_not_treated_as_success():
    service = LocalSettings()
    service.omit_field = "position"
    with pytest.raises(KeyError):
        service.device("plug")


@pytest.mark.parametrize(
    ("field", "invalid"),
    [("ClassAndVrmInstance", "grid:1"), ("Position", 4), ("PhaseSetting", 0), ("CustomName", 4)],
)
def test_invalid_persisted_settings_fail_initialization(field, invalid):
    service = LocalSettings()
    service.values[settings_path("plug") + "/" + field] = invalid
    with pytest.raises(ValueError):
        service.device("plug")


@pytest.mark.parametrize("instance", [-1, True, 1.5, "1", 32768])
def test_invalid_preferred_instance_does_not_touch_settings(instance):
    service = LocalSettings()
    with pytest.raises(ValueError):
        service.device("plug", instance)
    assert not service.values


@pytest.mark.parametrize("instance", [0, 32767])
def test_device_instance_range_includes_venus_api_boundaries(instance):
    service = LocalSettings()
    settings = service.device("plug", instance)
    assert settings.instance == instance
    assert service.device("plug", 0).instance == instance


def test_native_allocation_outside_venus_range_is_rejected():
    service = LocalSettings()
    service.values["/Settings/Devices/other/ClassAndVrmInstance"] = "pvinverter:32767"
    with pytest.raises(ValueError, match="32767"):
        service.device("plug", 32767)
