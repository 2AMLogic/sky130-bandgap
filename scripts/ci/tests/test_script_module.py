#!/usr/bin/env python3
"""Unit coverage for scripts/ci/script_module.py (issue #555).

Pins the three guarantees the fifteen hand-rolled loader copies could not
keep straight, directly against the one helper that now owns them:

* the #267 regression -- a module defining a `@dataclass` loads, because the
  module is registered before `exec_module` runs;
* idempotency -- two calls for one name return the same module object (the
  `except`-by-identity half of #267);
* the guard -- a path importlib cannot build a spec for raises a
  `RuntimeError` naming it, and a missing file raises `FileNotFoundError`
  rather than something indirect.

Run directly (`python3 scripts/ci/tests/test_script_module.py`) or via
`npm run test:unit`.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(CI_DIR))
from script_module import load_script_module  # noqa: E402


class LoadScriptModuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def load(self, name: str, body: str, **kwargs):
        """Write `body` to a temp file, load it under `name`, and unregister
        the name again when the test ends."""
        path = self.dir / f"{name}.py"
        path.write_text(body)
        self.addCleanup(sys.modules.pop, name, None)
        return load_script_module(path, name, **kwargs)

    def test_returns_the_module_and_registers_it(self) -> None:
        mod = self.load("sm_probe_basic", "VALUE = 41 + 1\n")
        self.assertEqual(mod.VALUE, 42)
        self.assertIs(sys.modules["sm_probe_basic"], mod)

    def test_dataclass_module_loads(self) -> None:
        """The #267 regression: `@dataclass` resolves annotations through
        `sys.modules[cls.__module__]` at class-creation time, so the module
        must already be registered while `exec_module` is still running."""
        mod = self.load(
            "sm_probe_dataclass",
            "from __future__ import annotations\n"
            "from dataclasses import dataclass\n"
            "\n"
            "@dataclass(frozen=True)\n"
            "class Corner:\n"
            "    section: str\n"
            "    temp_c: float\n",
        )
        corner = mod.Corner("tt", 27.0)
        self.assertEqual((corner.section, corner.temp_c), ("tt", 27.0))

    def test_registration_happens_before_exec_module_runs(self) -> None:
        mod = self.load(
            "sm_probe_order", "import sys\nSEEN = sys.modules.get('sm_probe_order')\n"
        )
        self.assertIs(mod.SEEN, mod)

    def test_two_calls_for_one_name_return_the_same_object(self) -> None:
        first = self.load("sm_probe_cached", "MARK = object()\n")
        again = load_script_module(self.dir / "sm_probe_cached.py", "sm_probe_cached")
        self.assertIs(first, again)

    def test_cached_false_reexecutes_the_file(self) -> None:
        first = self.load("sm_probe_fresh", "MARK = object()\n", cached=False)
        again = load_script_module(
            self.dir / "sm_probe_fresh.py", "sm_probe_fresh", cached=False
        )
        self.assertIsNot(first, again)
        self.assertIsNot(first.MARK, again.MARK)
        self.assertIs(sys.modules["sm_probe_fresh"], again)

    def test_a_spec_less_path_raises_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError):
            load_script_module(self.dir, "sm_probe_no_spec")

    def test_a_missing_file_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_script_module(self.dir / "no_such_module.py", "sm_probe_missing")


if __name__ == "__main__":
    unittest.main()
