"""Persistent device identity and user settings in Venus OS localsettings.

ClassAndVrmInstance delegates collision allocation to localsettings, which
reserves instances across drivers and retains each allocation across restarts.
The supplied bus must stay alive for the lifetime of all SettingsDevice users.
"""

import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("TasmotaPV.settings")
MAX_DEVICE_INSTANCE = 32767


def settings_path(topic: str) -> str:
    """Encode the entire MQTT identity as a collision-free D-Bus path element."""
    if not isinstance(topic, str) or not topic:
        raise ValueError("The MQTT device topic must be a non-empty string")
    return "/Settings/Devices/tasmota_" + topic.encode("utf-8").hex()


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"Expected an integer between {minimum} and {maximum}")
    return int(value)


def _instance(value: Any) -> int:
    match = re.fullmatch(r"pvinverter:([0-9]+)", value) if isinstance(value, str) else None
    if match is None:
        raise ValueError("ClassAndVrmInstance must contain pvinverter:<instance>")
    return _integer(int(match.group(1)), 0, MAX_DEVICE_INSTANCE)


def _name(value: Any) -> str:
    if not isinstance(value, str) or "\0" in value:
        raise ValueError("CustomName must be a D-Bus string")
    value.encode("utf-8")
    return str(value)


class TasmotaSettings:
    """Validated settings, with callbacks for accepted local and external changes.

    ``on_change(field, old, new)`` uses the fields ``instance``, ``position``,
    ``phase``, and ``custom_name``. The owner must restart its D-Bus service when
    instance changes. Construction fails if persistent settings cannot be read.
    Restart the process before retrying: the installed SettingsDevice uses
    global signal trackers that cannot safely replace partially created objects.
    """

    def __init__(
        self,
        bus: Any,
        topic: str,
        default_instance: int,
        *,
        on_change: Callable[[str, Any, Any], None] | None = None,
        settings_factory: Callable[..., Any] | None = None,
    ):
        default_instance = _integer(default_instance, 0, MAX_DEVICE_INSTANCE)
        self.settings_base = settings_path(topic)
        self._on_change = on_change
        self._values: dict[str, Any] = {}
        self._ready = False
        if settings_factory is None:
            # The driver adds Venus OS velib to sys.path before discovery. Keep
            # this import lazy so development hosts need no D-Bus dependencies.
            from settingsdevice import SettingsDevice  # pylint: disable=import-outside-toplevel

            settings_factory = SettingsDevice

        self._settings = settings_factory(
            bus=bus,
            supportedSettings={
                "instance": [
                    self.settings_base + "/ClassAndVrmInstance",
                    f"pvinverter:{default_instance}",
                    0,
                    0,
                ],
                "position": [self.settings_base + "/Position", 0, 0, 2],
                "phase": [self.settings_base + "/PhaseSetting", 1, 1, 3],
                "custom_name": [self.settings_base + "/CustomName", f"Solar Tasmota {topic}", 0, 0],
            },
            eventCallback=self._setting_changed,
            timeout=0,
        )
        # SettingsDevice logs individual AddSettings errors without raising.
        # Reading every field makes a partial or invalid registration fail here.
        for field in ("instance", "position", "phase", "custom_name"):
            self._values[field] = self._validate(field, self._settings[field])
        self._ready = True

    @staticmethod
    def _validate(field: str, value: Any) -> Any:
        if field == "instance":
            return _instance(value)
        if field == "position":
            return _integer(value, 0, 2)
        if field == "phase":
            return _integer(value, 1, 3)
        if field == "custom_name":
            return _name(value)
        raise ValueError(f"Unknown device setting: {field}")

    @property
    def instance(self) -> int:
        return self._values["instance"]

    @property
    def position(self) -> int:
        return self._values["position"]

    @property
    def phase(self) -> int:
        return self._values["phase"]

    @property
    def custom_name(self) -> str:
        return self._values["custom_name"]

    def _accept(self, field: str, value: Any) -> None:
        old = self._values[field]
        self._values[field] = value
        if old != value and self._on_change is not None:
            self._on_change(field, old, value)

    def _setting_changed(self, field: str, old: Any, value: Any) -> None:
        if not self._ready:
            return
        try:
            value = self._validate(field, value)
        except (ValueError, UnicodeError):
            logger.warning("Ignoring invalid localsettings %s value %r", field, value)
            return
        self._accept(field, value)

    def _set(self, field: str, value: Any) -> bool:
        try:
            value = self._validate(field, value)
        except (ValueError, UnicodeError):
            return False
        try:
            self._settings[field] = value
        except Exception:
            logger.exception("Failed to persist %s for %s", field, self.settings_base)
            return False
        # A successful SetValue precedes its asynchronous D-Bus notification.
        # Update immediately; that later notification is deduplicated by _accept.
        self._accept(field, value)
        return True

    def set_position(self, value: Any) -> bool:
        return self._set("position", value)

    def set_phase(self, value: Any) -> bool:
        return self._set("phase", value)

    def set_custom_name(self, value: Any) -> bool:
        return self._set("custom_name", value)
