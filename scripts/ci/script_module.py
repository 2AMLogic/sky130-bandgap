#!/usr/bin/env python3
"""One importlib file loader, carrying the #267 contract the copies kept
dropping (issue #555).

Fifteen hand-rolled copies of the same four-call sequence --
`spec_from_file_location` -> `module_from_spec` -> (`sys.modules[name] = mod`)
-> `exec_module` -- lived across `sim/`, `layout/` and `scripts/ci/` under six
names (`load_corner_run`, `_tracked_hashes`, `_load_runner`, `_load_harness`,
`load_runner`, `load`) plus bare module-level blocks. No copy failed, but
their guarantees had drifted into two opposite camps: six registered the
module in `sys.modules` before `exec_module`, five of them without a spec
guard; eight guarded the spec yet never registered; one did neither. Exactly
one (`sim_common.load_corner_run`, #268 fixing #267) did both, and it was the
only copy that explained why either half matters. Nothing told the author of
the next copy which half their call site needed, so each new one was pasted
from whichever neighbour was closest.

Both halves of that contract live here, for every call site:

* `sys.modules[name]` is registered BEFORE `exec_module` runs. A
  `@dataclass`-decorated class in the loaded file resolves its annotations
  through `sys.modules[cls.__module__]` (string annotations make this a
  lookup at class-creation time, not a stored type), and that lookup fails on
  an unregistered module -- on CPython 3.12 the `@dataclass` itself raises
  `AttributeError` out of `dataclasses._is_type` (issue #267).
* With `cached=True` (the default) a module already registered under `name`
  is returned as-is rather than re-executed. A fresh `exec_module` produces a
  brand-new exception class each time, and Python `except` matches by class
  identity, so two independently-loaded copies of one harness script would
  give a caller's `except SomeHarnessError` a chance of not matching an error
  raised through a differently-loaded copy. One name, one module object, one
  exception class per process (issue #267).
* A path importlib cannot build a spec/loader for raises `RuntimeError`
  naming the path, instead of failing later on a `None` spec.

Why this directory: the same reason as `content_hash.py` (#538) -- it is the
direction the repo's cross-tree imports already run (`sim/bin/sim_common.py`
loads helpers out of `scripts/ci` so there is one copy, while nothing under
`scripts/ci/` imports from `sim/`). Consumers add this directory to `sys.path`
and `from script_module import load_script_module`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_script_module(path: Path | str, name: str, *, cached: bool = True) -> ModuleType:
    """Import the Python file at `path` as module `name` and return it.

    Registers `sys.modules[name]` before `exec_module` (a `@dataclass` in the
    loaded file resolves its annotations through that entry, issue #267) and,
    with `cached=True`, returns the already-registered module on a repeat call
    instead of re-executing the file (a repeat execution would mint a second
    exception class, and `except` matches by identity). `cached=False`
    re-executes unconditionally and replaces the previous registration, for
    call sites that need a fresh module object each call. Raises
    `RuntimeError` naming `path` when importlib cannot build a spec or loader
    for it; callers that must fail closed with their own error type wrap this
    call rather than letting the `RuntimeError` escape (see
    `sim_common._tracked_hashes`).
    """
    if cached:
        cached_module = sys.modules.get(name)
        if cached_module is not None:
            return cached_module
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
