"""Unit tests for dependency_analyzer.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dependency_analyzer  # noqa: E402
from ir import EpicNode  # noqa: E402


def _epic(title: str, description: str = "", related_refs=None) -> EpicNode:
    return EpicNode(
        title=title,
        description_md=description,
        spec_page_url="https://x",
        spec_page_id="page-A",
        related_refs=list(related_refs or []),
    )


def test_no_markup_no_edges():
    epics = [_epic("Auth"), _epic("Schema"), _epic("Mobile")]
    graph, warnings = dependency_analyzer.analyze(epics)
    assert graph.edges == []
    assert warnings == []
    assert graph.topo_order == [0, 1, 2]


def test_depends_on_blockquote_resolves_by_title():
    epics = [
        _epic("Schema cleanup", "Some prose."),
        _epic(
            "Auth migration",
            "Intro line.\n\n> Depends on: Schema cleanup\n\nMore body.",
        ),
    ]
    graph, warnings = dependency_analyzer.analyze(epics)
    assert warnings == []
    assert len(graph.edges) == 1
    e = graph.edges[0]
    assert e.src_epic_idx == 0
    assert e.dst_epic_idx == 1
    assert e.source == "depends_on"
    # Dep blockquote removed from description.
    assert "Depends on" not in epics[1].description_md
    # Surface on the epic itself for previews.
    assert epics[1].dependencies == ["Schema cleanup"]


def test_blocks_reverses_edge_direction():
    epics = [
        _epic("Schema cleanup", "> Blocks: Auth migration"),
        _epic("Auth migration"),
    ]
    graph, _ = dependency_analyzer.analyze(epics)
    assert len(graph.edges) == 1
    # blocks means: src blocks dst → dst depends on src → edge src→dst.
    assert graph.edges[0].src_epic_idx == 0
    assert graph.edges[0].dst_epic_idx == 1
    assert epics[0].blocks == ["Auth migration"]


def test_after_alias_for_depends_on():
    epics = [
        _epic("Schema"),
        _epic("Auth", "> After: Schema"),
    ]
    graph, _ = dependency_analyzer.analyze(epics)
    assert len(graph.edges) == 1
    assert graph.edges[0].src_epic_idx == 0
    assert graph.edges[0].dst_epic_idx == 1


def test_epic_slug_resolution():
    epics = [_epic("First"), _epic("Second"), _epic("Third", "> Depends on: EPIC-1")]
    graph, _ = dependency_analyzer.analyze(epics)
    assert any(e.src_epic_idx == 0 and e.dst_epic_idx == 2 for e in graph.edges)


def test_comma_separated_multiple_refs():
    epics = [
        _epic("A"),
        _epic("B"),
        _epic("C", "> Depends on: A, B"),
    ]
    graph, _ = dependency_analyzer.analyze(epics)
    pairs = {(e.src_epic_idx, e.dst_epic_idx) for e in graph.edges}
    assert pairs == {(0, 2), (1, 2)}


def test_and_separator_supported():
    epics = [
        _epic("A"),
        _epic("B"),
        _epic("C", "> Depends on: A and B"),
    ]
    graph, _ = dependency_analyzer.analyze(epics)
    pairs = {(e.src_epic_idx, e.dst_epic_idx) for e in graph.edges}
    assert pairs == {(0, 2), (1, 2)}


def test_unresolved_ref_emits_warning():
    epics = [_epic("A", "> Depends on: Nonexistent")]
    graph, warnings = dependency_analyzer.analyze(epics)
    assert graph.edges == []
    assert len(graph.unresolved_refs) == 1
    assert any(w.kind == "unresolved_dep_ref" for w in warnings)


def test_self_dep_ignored_with_warning():
    epics = [_epic("Solo", "> Depends on: Solo")]
    graph, warnings = dependency_analyzer.analyze(epics)
    assert graph.edges == []
    assert any(w.kind == "self_dep" for w in warnings)


def test_cycle_detected_and_reorder_skipped():
    epics = [
        _epic("A", "> Depends on: B"),
        _epic("B", "> Depends on: A"),
    ]
    graph, warnings = dependency_analyzer.analyze(epics)
    assert len(graph.cycles) >= 1
    assert any(w.kind == "dep_cycle" for w in warnings)
    # reorder() returns the original order when cycles are present.
    out = dependency_analyzer.reorder(epics, graph)
    assert [e.title for e in out] == ["A", "B"]


def test_three_node_cycle():
    epics = [
        _epic("A", "> Depends on: C"),
        _epic("B", "> Depends on: A"),
        _epic("C", "> Depends on: B"),
    ]
    graph, _ = dependency_analyzer.analyze(epics)
    assert len(graph.cycles) >= 1


def test_toposort_stable_when_independent():
    # Markdown order: A, B, C, D. No deps. Should preserve original order.
    epics = [_epic("A"), _epic("B"), _epic("C"), _epic("D")]
    graph, _ = dependency_analyzer.analyze(epics)
    assert graph.topo_order == [0, 1, 2, 3]


def test_toposort_reorders_when_dependent():
    epics = [
        _epic("Auth migration", "> Depends on: Schema"),
        _epic("Schema"),
    ]
    graph, _ = dependency_analyzer.analyze(epics)
    assert graph.topo_order == [1, 0]
    out = dependency_analyzer.reorder(epics, graph)
    assert [e.title for e in out] == ["Schema", "Auth migration"]


def test_dedup_redundant_edges():
    epics = [
        _epic("Schema"),
        _epic(
            "Auth",
            "> Depends on: Schema\n\n> Depends on: Schema\n\n> After: Schema",
        ),
    ]
    graph, _ = dependency_analyzer.analyze(epics)
    assert len(graph.edges) == 1


def test_dependencies_blockquote_stripped_from_description():
    body = "Intro paragraph.\n\n> Depends on: Schema\n\nMore prose."
    epics = [_epic("Schema"), _epic("Auth", body)]
    dependency_analyzer.analyze(epics)
    assert epics[1].description_md.startswith("Intro paragraph.")
    assert "Depends on" not in epics[1].description_md
    assert "More prose." in epics[1].description_md


def test_no_strip_when_disabled():
    body = "Body.\n\n> Depends on: Schema"
    epics = [_epic("Schema"), _epic("Auth", body)]
    dependency_analyzer.analyze(epics, strip_from_description=False)
    assert "Depends on" in epics[1].description_md


def test_case_insensitive_title_match():
    epics = [_epic("Schema Cleanup"), _epic("Auth", "> Depends on: schema cleanup")]
    graph, _ = dependency_analyzer.analyze(epics)
    assert len(graph.edges) == 1


def test_substring_title_match_unique():
    epics = [
        _epic("Schema cleanup migration"),
        _epic("Auth", "> Depends on: Schema cleanup"),
    ]
    graph, _ = dependency_analyzer.analyze(epics)
    assert len(graph.edges) == 1


def test_substring_ambiguous_skipped():
    epics = [
        _epic("Schema A"),
        _epic("Schema B"),
        _epic("Auth", "> Depends on: Schema"),
    ]
    graph, warnings = dependency_analyzer.analyze(epics)
    assert graph.edges == []
    assert any(w.kind == "unresolved_dep_ref" for w in warnings)


def test_graph_records_original_titles():
    epics = [_epic("First"), _epic("Second")]
    graph, _ = dependency_analyzer.analyze(epics)
    assert graph.epic_titles_original == ["First", "Second"]
