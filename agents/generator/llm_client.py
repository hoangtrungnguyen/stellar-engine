"""Anthropic SDK wrapper for the Generator agent (Phase D — DEFERRED).

Direct SDK calls require a paid `ANTHROPIC_API_KEY`. Today the interim
workflow runs the outline step manually inside a Claude Code session
(see `docs/generator/plan.md` §Phase D). This module is a stub that
errors loudly if invoked before Phase D lands.
"""

from __future__ import annotations


class LLMNotEnabled(RuntimeError):
    """Raised when `--llm` is requested but Phase D is not yet implemented."""


def outline(_ir_root, *, model: str = "claude-sonnet-4-5", max_tokens: int = 4096):
    """Call the Anthropic API to produce an outline. Not implemented in Phase A."""
    raise LLMNotEnabled(
        "Phase D (LLM outline) is deferred. Run with `--no-llm` and produce "
        "outline.json manually via a Claude Code session — see "
        "docs/generator/plan.md §Phase D for the interim workflow."
    )
