"""Epic dependency analyzer.

Reads `> Depends on:` / `> Blocks:` / `> After:` blockquote markup from each
epic's description, resolves refs to other epics, builds a directed graph
where edges run *from prerequisite to dependent* (toposort produces creation
order: prereqs first), detects cycles, and emits a topological order.

Source of edges is operator-driven markup only — no inference, no LLM.
"""

from __future__ import annotations

import re
from typing import Iterable

from ir import DependencyEdge, DependencyGraph, EpicNode, ParseWarning

# Matches the start of a blockquote dep line. Captures the kind + payload.
# Accepts variations: "> Depends on:", ">Depends on:", "> depends-on:".
_DEP_LINE_RE = re.compile(
    r"^\s*>\s*(depends\s*[-_ ]?on|blocks|after)\s*:\s*(.*)$",
    re.IGNORECASE,
)

_EPIC_SLUG_RE = re.compile(r"^EPIC[-_ ]?(\d+)$", re.IGNORECASE)


def _kind_from_match(raw: str) -> str:
    s = raw.lower().replace(" ", "").replace("-", "").replace("_", "")
    if s == "dependson":
        return "depends_on"
    if s == "blocks":
        return "blocks"
    if s == "after":
        return "after"
    return "depends_on"


def _split_refs(payload: str) -> list[str]:
    """Split a comma- or 'and'-separated list of refs."""
    # normalize 'and' as separator
    payload = re.sub(r"\band\b", ",", payload, flags=re.IGNORECASE)
    return [p.strip().strip("`").strip() for p in payload.split(",") if p.strip()]


def extract_and_strip(epic: EpicNode) -> tuple[list[tuple[str, str]], str]:
    """Pull dep-blockquote lines out of `epic.description_md`.

    Returns (deps, cleaned_description) where deps is a list of
    (kind, raw_ref) and cleaned_description has the dep blockquote
    lines removed.
    """
    if not epic.description_md:
        return [], epic.description_md
    kept: list[str] = []
    deps: list[tuple[str, str]] = []
    for line in epic.description_md.splitlines():
        m = _DEP_LINE_RE.match(line)
        if not m:
            kept.append(line)
            continue
        kind = _kind_from_match(m.group(1))
        for ref in _split_refs(m.group(2)):
            deps.append((kind, ref))
    cleaned = "\n".join(kept)
    # Trim trailing/leading blank lines that may be left over.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip("\n")
    return deps, cleaned


def _norm_title(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def _resolve_ref(
    ref: str,
    epics: list[EpicNode],
    src_idx: int,
    ref_index: dict[str, int],
) -> int | None:
    """Match `ref` against an epic. Returns target index or None."""
    raw = ref.strip().strip("`").strip()
    if not raw:
        return None

    # EPIC-N slug (1-based).
    m = _EPIC_SLUG_RE.match(raw)
    if m:
        n = int(m.group(1))
        if 1 <= n <= len(epics):
            idx = n - 1
            return idx if idx != src_idx else None
        return None

    # Plane-style ref (e.g. WEBINTRO-12) — match against any epic that
    # carries the ref in related_refs (rare for epics, but supported).
    upper = raw.upper()
    if "-" in raw and any(c.isdigit() for c in raw):
        for i, e in enumerate(epics):
            if i == src_idx:
                continue
            if upper in {r.upper() for r in e.related_refs}:
                return i

    # Title match: exact (normalized), then substring.
    norm = _norm_title(raw)
    if norm in ref_index:
        idx = ref_index[norm]
        return idx if idx != src_idx else None
    # Substring fallback — only if exactly one epic matches.
    matches = [
        i for i, e in enumerate(epics)
        if i != src_idx and norm in _norm_title(e.title)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _detect_cycles(
    n: int, adj: dict[int, list[int]],
) -> list[list[int]]:
    """Find simple cycles via DFS. Returns cycles as lists of node indices."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = [WHITE] * n
    parent: list[int | None] = [None] * n
    cycles: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()

    def dfs(u: int) -> None:
        color[u] = GRAY
        for v in adj.get(u, []):
            if color[v] == WHITE:
                parent[v] = u
                dfs(v)
            elif color[v] == GRAY:
                # Back edge → cycle from v back to u then to v.
                cyc = [v]
                cur: int | None = u
                while cur is not None and cur != v:
                    cyc.append(cur)
                    cur = parent[cur]
                cyc.append(v)
                cyc.reverse()
                # Canonicalize for dedup: rotate to smallest, drop trailing dup.
                core = cyc[:-1]
                if not core:
                    continue
                k = core.index(min(core))
                canon = tuple(core[k:] + core[:k])
                if canon not in seen:
                    seen.add(canon)
                    cycles.append(list(canon))
        color[u] = BLACK

    for i in range(n):
        if color[i] == WHITE:
            dfs(i)
    return cycles


def _toposort(n: int, edges: list[DependencyEdge]) -> list[int]:
    """Stable Kahn: nodes with no incoming edges come out first, original
    order broken-tied. Edges are prereq→dependent."""
    indeg = [0] * n
    adj: dict[int, list[int]] = {i: [] for i in range(n)}
    for e in edges:
        indeg[e.dst_epic_idx] += 1
        adj[e.src_epic_idx].append(e.dst_epic_idx)
    # Use original index as tiebreaker.
    ready = [i for i in range(n) if indeg[i] == 0]
    out: list[int] = []
    while ready:
        ready.sort()
        i = ready.pop(0)
        out.append(i)
        for j in adj[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.append(j)
    # If cycles exist, append remaining in original order to avoid losing them.
    if len(out) < n:
        seen = set(out)
        for i in range(n):
            if i not in seen:
                out.append(i)
    return out


def analyze(
    epics: list[EpicNode],
    *,
    strip_from_description: bool = True,
) -> tuple[DependencyGraph, list[ParseWarning]]:
    """Build the dep graph for `epics`. Mutates each epic's `dependencies` /
    `blocks` fields, and (if `strip_from_description`) removes dep blockquote
    lines from `description_md`. Returns (graph, warnings)."""
    warnings: list[ParseWarning] = []
    ref_index = {_norm_title(e.title): i for i, e in enumerate(epics)}

    # Pass 1: extract markup per epic.
    per_epic_raw: list[list[tuple[str, str]]] = []
    for epic in epics:
        deps, cleaned = extract_and_strip(epic)
        per_epic_raw.append(deps)
        if strip_from_description:
            epic.description_md = cleaned

    # Pass 2: resolve refs into edges.
    edges: list[DependencyEdge] = []
    unresolved: list[dict] = []
    for src_idx, deps in enumerate(per_epic_raw):
        epic = epics[src_idx]
        for kind, raw in deps:
            target = _resolve_ref(raw, epics, src_idx, ref_index)
            if target is None:
                # Self-ref? Otherwise unresolved.
                if _norm_title(raw) == _norm_title(epic.title):
                    warnings.append(ParseWarning(
                        kind="self_dep",
                        detail=f"epic {src_idx + 1} ({epic.title!r}) declares dep on itself ({raw!r}); ignored",
                    ))
                else:
                    unresolved.append({
                        "epic_idx": src_idx,
                        "epic_title": epic.title,
                        "kind": kind,
                        "raw_ref": raw,
                    })
                    warnings.append(ParseWarning(
                        kind="unresolved_dep_ref",
                        detail=f"epic {src_idx + 1} ({epic.title!r}) → unresolved {kind} ref {raw!r}",
                    ))
                continue

            # `blocks` reverses direction: src blocks target ⇒ target depends on src.
            if kind == "blocks":
                edge = DependencyEdge(
                    src_epic_idx=src_idx,
                    dst_epic_idx=target,
                    source=kind,
                    raw_ref=raw,
                )
                epic.blocks.append(epics[target].title)
            else:
                # depends_on / after: src depends on target ⇒ target → src.
                edge = DependencyEdge(
                    src_epic_idx=target,
                    dst_epic_idx=src_idx,
                    source=kind,
                    raw_ref=raw,
                )
                epic.dependencies.append(epics[target].title)
            edges.append(edge)

    # Deduplicate edges by (src,dst). Keep first occurrence.
    deduped: list[DependencyEdge] = []
    seen_pairs: set[tuple[int, int]] = set()
    for e in edges:
        key = (e.src_epic_idx, e.dst_epic_idx)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        deduped.append(e)
    edges = deduped

    # Pass 3: cycle detection + topo sort.
    adj: dict[int, list[int]] = {i: [] for i in range(len(epics))}
    for e in edges:
        adj[e.src_epic_idx].append(e.dst_epic_idx)
    cycles = _detect_cycles(len(epics), adj)
    for cyc in cycles:
        names = " -> ".join(epics[i].title for i in cyc + [cyc[0]])
        warnings.append(ParseWarning(
            kind="dep_cycle",
            detail=f"cycle: {names}",
        ))

    topo = _toposort(len(epics), edges) if not cycles else list(range(len(epics)))

    graph = DependencyGraph(
        edges=edges,
        unresolved_refs=unresolved,
        cycles=cycles,
        topo_order=topo,
        original_order=list(range(len(epics))),
        epic_titles_original=[e.title for e in epics],
    )
    return graph, warnings


def reorder(epics: list[EpicNode], graph: DependencyGraph) -> list[EpicNode]:
    """Return epics permuted to the graph's topological order. If the graph
    has cycles, returns the original list unchanged."""
    if graph.cycles or not graph.topo_order:
        return list(epics)
    return [epics[i] for i in graph.topo_order]
