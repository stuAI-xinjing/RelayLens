"""Load the built-in or an operator-owned private task suite."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Callable


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _load_module(path: Path) -> ModuleType:
    module_name = "_relaylens_external_suite_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"cannot load suite module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def load_suite(path: str | None = None) -> tuple[Callable, str, str, str | None]:
    """Return ``suite(seed, rounds)``, version, source kind and commitment hash.

    A private suite is ordinary local Python loaded only by the audit process. It
    is intentionally not treated as a secret once its prompts are sent to a
    gateway; the commitment hash only proves which local file was used.
    """
    if not path:
        from .tasks import SUITE_VERSION, suite
        source = Path(__file__).with_name("tasks.py")
        return suite, SUITE_VERSION, "builtin", _sha256(source)

    suite_path = Path(path).expanduser().resolve()
    if not suite_path.is_file():
        raise FileNotFoundError(f"private suite file not found: {suite_path}")
    module = _load_module(suite_path)
    suite = getattr(module, "suite", None)
    if not callable(suite):
        raise TypeError("private suite must define suite(seed, rounds)")
    version = str(getattr(module, "SUITE_VERSION", f"external:{suite_path.stem}"))
    return suite, version, "external", _sha256(suite_path)
