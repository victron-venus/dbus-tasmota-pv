import importlib
import math
import sys
from pathlib import Path

import atheris

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
with atheris.instrument_imports():
    # Normal import machinery lets Atheris replace the production module loader.
    # Calling a pre-created SourceFileLoader directly bypasses its import hook.
    runtime = importlib.import_module("dbus-tasmota-pv")

parse_energy_payload = runtime.parse_energy_payload

for function_name in ("parse_energy_payload", "_parse_energy_payload", "_energy_reading"):
    function = getattr(runtime, function_name)
    imported_code = function.__code__
    # The locked Atheris version leaves already-instrumented code unchanged.
    # Fail before fuzzing if the production parser did not pass its import hook.
    atheris.instrument_func(function)
    if function.__code__ is not imported_code:
        raise RuntimeError(f"Production parser was not instrumented during import: {function_name}")
print("Atheris production instrumentation verified: dbus-tasmota-pv.py (3 parser functions)", file=sys.stderr)


def test_one_input(data: bytes) -> None:
    reading = parse_energy_payload(data)
    if reading is not None:
        assert len(reading) == 6  # nosec B101 - intentional test oracle
        assert all(value is None or math.isfinite(value) for value in reading)  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, atheris.instrument_func(test_one_input))
    atheris.Fuzz()
