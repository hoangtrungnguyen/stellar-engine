"""Smoke tests for writer stubs."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import grava_writer  # noqa: E402
import plane_writer  # noqa: E402


def test_plane_writer_raises_phase_2():
    with pytest.raises(NotImplementedError, match="Phase 2"):
        plane_writer.execute(None, None, None)


def test_grava_writer_raises_phase_3():
    with pytest.raises(NotImplementedError, match="Phase 3"):
        grava_writer.execute(None, None, None)
