"""Verify production-loader routing separately from native engine coverage."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import contextlib
import importlib.abc
import runpy
import sys
import types
from pathlib import Path

root = Path(sys.argv[1])
route_imports = sys.argv[2] == "enabled"
seen = set()

class Observer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        seen.add(fullname)
        return None

@contextlib.contextmanager
def instrument_imports():
    observer = Observer()
    if route_imports:
        sys.meta_path.insert(0, observer)
    try:
        yield
    finally:
        if route_imports:
            sys.meta_path.remove(observer)

def instrument_func(function):
    # Model only the public API's idempotence, not native instrumentation.
    if function.__module__ not in seen:
        function.__code__ = function.__code__.replace()
    return function

atheris = types.ModuleType("atheris")
atheris.instrument_imports = instrument_imports
atheris.instrument_func = instrument_func
sys.modules["atheris"] = atheris
try:
    harness = runpy.run_path(str(root / "fuzz/fuzz_energy.py"))
except RuntimeError as error:
    if route_imports or "not instrumented during import" not in str(error):
        raise
else:
    assert route_imports, "Missing production instrumentation was accepted"
    parser = harness["parse_energy_payload"]
    assert parser.__module__ in seen, "Production loader bypassed the import hook"
    assert Path(parser.__code__.co_filename).resolve() == root / "dbus-tasmota-pv.py"
    for seed in (root / "fuzz/corpus/energy").iterdir():
        harness["test_one_input"](seed.read_bytes())
'''


def test_production_parser_uses_import_hook():
    subprocess.run(
        [sys.executable, "-c", PROBE, str(ROOT), "enabled"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_missing_production_instrumentation_fails_before_campaign():
    subprocess.run(
        [sys.executable, "-c", PROBE, str(ROOT), "disabled"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
