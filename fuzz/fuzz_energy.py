import math
import sys
from pathlib import Path

import atheris

ROOT = Path(__file__).resolve().parents[1]
import importlib.util

sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("fuzz_tasmota_runtime", ROOT / "dbus-tasmota-pv.py")
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
with atheris.instrument_imports():
    spec.loader.exec_module(runtime)

with atheris.instrument_imports():
    from fuzz_tasmota_runtime import parse_energy_payload


def test_one_input(data: bytes) -> None:
    reading = parse_energy_payload(data)
    if reading is not None:
        assert len(reading) == 6  # nosec B101 - intentional test oracle
        assert all(value is None or math.isfinite(value) for value in reading)  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, atheris.instrument_func(test_one_input))
    atheris.Fuzz()
