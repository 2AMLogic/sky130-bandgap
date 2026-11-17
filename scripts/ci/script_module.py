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
  exception class per process (issue #267). The registration is keyed on
  `name` alone, so whenever a call finds an entry under `name` -- cached or
  not -- its `__spec__.origin` is compared (resolved) against the requested
  `path`: a name already registered from a *different* file raises, whatever
  `cached` is, rather than silently returning or re-executing the wrong
  module; re-pointing the name deliberately requires an explicit
  `sys.modules.pop(name)` first. An entry with no usable origin (a namespace
  package, an ad-hoc module) has nothing to compare and is returned as-is
  with `cached=True` or re-executed with `cached=False` (issue #592).
* A raising `exec_module` removes the registration again (restoring any
  previous one, which only `cached=False` can have replaced) before the
  exception propagates, so no half-initialized module stays reachable through
  `sys.modules` (issue #592).
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
    re-executes and replaces the previous registration, for call sites that
    need a fresh module object each call. Raises `RuntimeError` naming
    `path` when importlib cannot build a spec or loader for it; callers that
    must fail closed with their own error type wrap this call rather than
    letting the `RuntimeError` escape (see `sim_common._tracked_hashes`).

    Whenever a call finds an entry already registered under `name` -- whether
    or not it would be returned from the cache -- that entry's resolved
    `__spec__.origin` is compared against the resolved `path`, and a mismatch
    raises `RuntimeError` naming `name` and both paths (issue #592):
    `cached=True` would otherwise return the wrong module without reading the
    file at all, and `cached=False` would otherwise silently re-execute it.
    Re-pointing the name at another file deliberately requires an explicit
    `sys.modules.pop(name)` first. An entry with no usable `__spec__.origin`
    (a namespace package, a module registered by other means) has nothing to
    compare: it is returned as-is with `cached=True` and re-executed with
    `cached=False`. If `exec_module` raises, whatever registration was
    present before the call is restored (for `cached=False`) or the entry is
    removed (nothing was there), so no half-initialized module stays
    registered.
    """
    existing = sys.modules.get(name)
    if existing is not None:
        existing_spec = getattr(existing, "__spec__", None)
        existing_origin = getattr(existing_spec, "origin", None)
        if existing_origin and Path(existing_origin).resolve() != Path(path).resolve():
            raise RuntimeError(
                f"module name {name!r} is already registered from"
                f" {existing_origin} but was asked for {path}; load {path}"
                " under a different name"
            )
        if cached:
            return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    previous = sys.modules.get(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module
