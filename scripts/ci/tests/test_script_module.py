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
  rather than something indirect;
* the #592 hazards -- a name already registered from a different file
  raises instead of silently returning the wrong module (resolved paths, so
  a symlink to the same file still hits the cache), and a raising
  `exec_module` leaves no half-initialized registration behind.

Run directly (`python3 scripts/ci/tests/test_script_module.py`) or via
`npm run test:unit`.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

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

    def test_a_name_reused_for_a_different_file_raises_even_uncached(self) -> None:
        """The origin guard runs on every call that finds an existing
        registration, not only cached ones: `cached=False` must not
        silently re-execute a different file under an occupied name, and
        the raise must leave the prior registration untouched."""
        first = self.load("sm_probe_reused_fresh", "VALUE = 1\n")
        other = self.dir / "sm_probe_other_fresh.py"
        other.write_text("VALUE = 2\n")
        with self.assertRaises(RuntimeError) as ctx:
            load_script_module(other, "sm_probe_reused_fresh", cached=False)
        message = str(ctx.exception)
        self.assertIn("sm_probe_reused_fresh", message)
        self.assertIn("sm_probe_reused_fresh.py", message)
        self.assertIn("sm_probe_other_fresh.py", message)
        self.assertIs(sys.modules["sm_probe_reused_fresh"], first)

    def test_symlinked_same_file_reload_reexecutes_uncached(self) -> None:
        """`cached=False` through a differently-spelled path to the same
        file passes the origin guard (resolved comparison) and re-executes
        instead of raising."""
        real = self.dir / "sm_probe_link_fresh.py"
        real.write_text("MARK = object()\n")
        self.addCleanup(sys.modules.pop, "sm_probe_link_fresh", None)
        first = load_script_module(real, "sm_probe_link_fresh")
        link = self.dir / "sm_probe_link_alias.py"
        link.symlink_to(real)
        again = load_script_module(link, "sm_probe_link_fresh", cached=False)
        self.assertIsNot(first, again)
        self.assertIs(sys.modules["sm_probe_link_fresh"], again)

    def test_path_spellings_resolve_for_the_origin_check(self) -> None:
        """`str` vs `Path` and redundant-`..` spellings compare resolved:
        spellings of the same file are a cache hit, a `str` path to a
        different file still raises."""
        first = self.load("sm_probe_spelling", "VALUE = 9\n")
        plain = str(self.dir / "sm_probe_spelling.py")
        self.assertIs(load_script_module(plain, "sm_probe_spelling"), first)
        roundabout = str(self.dir / "sub" / ".." / "sm_probe_spelling.py")
        self.assertIs(load_script_module(roundabout, "sm_probe_spelling"), first)
        other = self.dir / "sm_probe_spelling_other.py"
        other.write_text("VALUE = 10\n")
        with self.assertRaises(RuntimeError):
            load_script_module(str(other), "sm_probe_spelling")
        self.assertIs(sys.modules["sm_probe_spelling"], first)

    def test_a_spec_less_path_raises_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError):
            load_script_module(self.dir, "sm_probe_no_spec")

    def test_a_missing_file_raises_file_not_found(self) -> None:
        self.addCleanup(sys.modules.pop, "sm_probe_missing", None)
        with self.assertRaises(FileNotFoundError):
            load_script_module(self.dir / "no_such_module.py", "sm_probe_missing")
        self.assertNotIn("sm_probe_missing", sys.modules)

    def test_a_name_reused_for_a_different_file_raises(self) -> None:
        """The cache is keyed on `name` alone; without the origin check a
        repeat call for a different file would return the first file's module
        without ever reading the second (issue #592)."""
        first = self.load("sm_probe_reused", "VALUE = 1\n")
        other = self.dir / "sm_probe_other.py"
        other.write_text("VALUE = 2\n")
        with self.assertRaises(RuntimeError) as ctx:
            load_script_module(other, "sm_probe_reused")
        message = str(ctx.exception)
        self.assertIn("sm_probe_reused.py", message)
        self.assertIn("sm_probe_other.py", message)
        self.assertIs(sys.modules["sm_probe_reused"], first)

    def test_a_symlink_to_the_same_file_still_hits_the_cache(self) -> None:
        """Resolved paths are compared, so a differently-spelled path to the
        same file is a cache hit, not a false mismatch."""
        real = self.dir / "sm_probe_real.py"
        real.write_text("VALUE = 7\n")
        self.addCleanup(sys.modules.pop, "sm_probe_symlinked", None)
        first = load_script_module(real, "sm_probe_symlinked")
        link = self.dir / "sm_probe_link.py"
        link.symlink_to(real)
        again = load_script_module(link, "sm_probe_symlinked")
        self.assertIs(first, again)

    def test_a_cached_entry_without_a_usable_origin_is_returned(self) -> None:
        """A namespace package or ad-hoc module registered under `name`
        carries no `__spec__.origin`; there is nothing to compare, so it is
        returned as-is (the pre-#582 behaviour of `load_corner_run`)."""
        marker = ModuleType("sm_probe_foreign")
        sys.modules["sm_probe_foreign"] = marker
        self.addCleanup(sys.modules.pop, "sm_probe_foreign", None)
        other = self.dir / "sm_probe_foreign_file.py"
        other.write_text("VALUE = 3\n")
        self.assertIs(load_script_module(other, "sm_probe_foreign"), marker)

    def test_a_failed_exec_leaves_no_registration(self) -> None:
        """`exec_module` runs with the module already registered; when it
        raises, the entry must be removed before the exception propagates,
        and the next `cached=True` call re-executes rather than returning
        the broken module (issue #592)."""
        path = self.dir / "sm_probe_boom.py"
        path.write_text("raise ValueError('boom')\n")
        self.addCleanup(sys.modules.pop, "sm_probe_boom", None)
        with self.assertRaises(ValueError):
            load_script_module(path, "sm_probe_boom")
        self.assertNotIn("sm_probe_boom", sys.modules)
        path.write_text("VALUE = 5\n")
        mod = load_script_module(path, "sm_probe_boom")
        self.assertEqual(mod.VALUE, 5)

    def test_a_failed_cached_false_reload_restores_the_prior_module(self) -> None:
        """Only `cached=False` reaches `exec_module` with a registration
        already present; a failed reload puts that prior module back."""
        path = self.dir / "sm_probe_reload.py"
        path.write_text("VALUE = 1\n")
        self.addCleanup(sys.modules.pop, "sm_probe_reload", None)
        first = load_script_module(path, "sm_probe_reload")
        path.write_text("raise RuntimeError('boom')\n")
        with self.assertRaises(RuntimeError):
            load_script_module(path, "sm_probe_reload", cached=False)
        self.assertIs(sys.modules["sm_probe_reload"], first)


if __name__ == "__main__":
    unittest.main()
