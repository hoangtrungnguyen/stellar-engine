"""Shared test setup: put `agents/orchestrator/cli/` on sys.path and provide
fakes for `subprocess.run` so tests never touch real `grava`, `git`, `gh`, or
`go` binaries.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

_CLI_ROOT = Path(__file__).resolve().parent.parent / "cli"
_TESTS_ROOT = Path(__file__).resolve().parent
for _p in (_CLI_ROOT, _TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ─────────────────────────────────────────────────────────────────────────────
# Fake subprocess.run
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FakeCompleted:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class Recorder:
    """Records every subprocess.run invocation + dispatches by argv prefix."""

    handlers: dict[tuple[str, ...], Callable[[list[str]], FakeCompleted]] = field(
        default_factory=dict
    )
    calls: list[list[str]] = field(default_factory=list)
    default: FakeCompleted = field(default_factory=lambda: FakeCompleted(0, "", ""))

    def register(self, *prefix: str, returncode: int = 0, stdout: str = "", stderr: str = ""):
        result = FakeCompleted(returncode, stdout, stderr)
        self.handlers[tuple(prefix)] = lambda _argv: result

    def register_fn(self, *prefix: str, fn: Callable[[list[str]], FakeCompleted]):
        self.handlers[tuple(prefix)] = fn

    def __call__(self, argv, **_kwargs) -> FakeCompleted:
        # Normalise: subprocess.run accepts list or string; tests use lists.
        if isinstance(argv, str):
            argv_list = argv.split()
        else:
            argv_list = [str(a) for a in argv]
        self.calls.append(argv_list)

        # Longest-prefix match.
        for prefix in sorted(self.handlers, key=len, reverse=True):
            if tuple(argv_list[: len(prefix)]) == prefix:
                return self.handlers[prefix](argv_list)
        return self.default

    def find_calls(self, *prefix: str) -> list[list[str]]:
        return [c for c in self.calls if tuple(c[: len(prefix)]) == tuple(prefix)]


@pytest.fixture
def recorder(monkeypatch) -> Recorder:
    """Replace subprocess.run with a Recorder that dispatches by argv prefix."""
    r = Recorder()
    monkeypatch.setattr(subprocess, "run", r)
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Wisp helpers — orchestrator scripts call `grava wisp read/write`.
# ─────────────────────────────────────────────────────────────────────────────


class WispStore:
    """In-memory wisp store; back the recorder with this for read/write."""

    def __init__(self):
        self._data: dict[tuple[str, str], str] = {}

    def read(self, issue_id: str, key: str) -> str:
        return self._data.get((issue_id, key), "")

    def write(self, issue_id: str, key: str, value: str) -> None:
        self._data[(issue_id, key)] = value

    def all(self) -> dict[tuple[str, str], str]:
        return dict(self._data)

    def wire(self, recorder: Recorder) -> None:
        """Attach this store to the given recorder's `grava wisp` handlers."""

        def read_handler(argv: list[str]) -> FakeCompleted:
            # ["grava", "wisp", "read", <id>, <key>]
            iid, key = argv[3], argv[4]
            value = self.read(iid, key)
            return FakeCompleted(0 if value else 1, stdout=value)

        def write_handler(argv: list[str]) -> FakeCompleted:
            # ["grava", "wisp", "write", <id>, <key>, <value>]
            iid, key, value = argv[3], argv[4], argv[5]
            self.write(iid, key, value)
            return FakeCompleted(0)

        recorder.register_fn("grava", "wisp", "read", fn=read_handler)
        recorder.register_fn("grava", "wisp", "write", fn=write_handler)


@pytest.fixture
def wisps(recorder) -> WispStore:
    store = WispStore()
    store.wire(recorder)
    return store


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: build a grava-show JSON blob.
# ─────────────────────────────────────────────────────────────────────────────


def grava_show_payload(
    *,
    issue_id: str,
    issue_type: str = "task",
    title: str = "Sample",
    status: str = "open",
    labels: list[str] | None = None,
    description: str = "",
) -> str:
    return json.dumps(
        {
            "id": issue_id,
            "type": issue_type,
            "title": title,
            "status": status,
            "labels": labels or [],
            "description": description,
        }
    )
