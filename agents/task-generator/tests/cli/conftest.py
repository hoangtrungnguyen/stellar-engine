"""Shared test setup: put `agents/task-generator/` and its `cli/` subdir on sys.path."""

import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent.parent  # agents/task-generator/
_CLI_ROOT = _PKG_ROOT / "cli"

for p in (_PKG_ROOT, _CLI_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
