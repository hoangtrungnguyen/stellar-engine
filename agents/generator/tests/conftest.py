"""Shared test setup: put `agents/generator/` on sys.path so tests can import
`generator.*` modules directly (mirrors orchestrator tests/conftest.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parent.parent
_AGENTS_DIR = _AGENT_ROOT.parent

# Put `agents/` on sys.path so `import generator.ir` works as a package.
for _p in (_AGENTS_DIR, _AGENT_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
