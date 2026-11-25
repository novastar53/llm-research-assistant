"""Unit tests for the pure graph algorithms (no Git involved)."""

from __future__ import annotations

import pytest

from scientist import Edge, Experiment, GraphError, Relationship
from scientist.graph import ancestors, assemble_graph, descendants
from scientist.models import ExperimentManifest, ParentRef

OID = "a" * 40


def make_experiment(exp_id: str) -> Experiment:
    return Experiment(
        branch=f"experiments/{exp_id}",
        commit=OID,
        manifest=ExperimentManifest(id=exp_id, title=f"title {exp_id}", parents=[]),
    )


def make_edge(source: str, target: str) -> Edge:
    return Edge(
        source=source,
        target=target,
        source_commit=OID,
        relationship=Relationship.EXTENDS,
    )


def test_assemble_sorts_nodes_and_edges() -> None:
    nodes = [make_experiment("zeta"), make_experiment("mid"), make_experiment("alpha")]
    edges = [make_edge("zeta", "mid"), make_edge("alpha", "zeta")]
    graph = assemble_graph(nodes, edges)
    assert [n.manifest.id for n in graph.nodes] == ["alpha", "mid", "zeta"]
    assert [(e.source, e.target) for e in graph.edges] == [("alpha", "zeta"), ("zeta", "mid")]


def test_assemble_rejects_duplicate_ids() -> None:
    with pytest.raises(GraphError, match="duplicate"):
        assemble_graph([make_experiment("a"), make_experiment("a")], [])


def test_assemble_rejects_edges_to_unknown_nodes() -> None:
    with pytest.raises(GraphError, match="unknown experiment"):
        assemble_graph([make_experiment("a")], [make_edge("a", "ghost")])


def test_assemble_rejects_cycle() -> None:
    nodes = [make_experiment("a"), make_experiment("b")]
    edges = [make_edge("a", "b"), make_edge("b", "a")]
    with pytest.raises(GraphError, match="cycle"):
        assemble_graph(nodes, edges)


def test_assemble_rejects_self_loop() -> None:
    with pytest.raises(GraphError, match=r"unknown|cycle"):
        assemble_graph([make_experiment("a")], [make_edge("a", "a")])


def test_assemble_allows_disconnected_nodes() -> None:
    graph = assemble_graph([make_experiment("a"), make_experiment("b")], [])
    assert len(graph.nodes) == 2


def test_traversal_excludes_start_and_duplicates() -> None:
    # a -> b -> d, a -> c -> d: d has two paths back to a.
    edges = [
        make_edge("a", "b"),
        make_edge("a", "c"),
        make_edge("b", "d"),
        make_edge("c", "d"),
    ]
    assert ancestors("d", edges) == ["a", "b", "c"]
    assert descendants("a", edges) == ["b", "c", "d"]
    assert ancestors("a", edges) == []
    assert descendants("d", edges) == []


def test_traversal_isolated_node() -> None:
    assert ancestors("solo", []) == []
    assert descendants("solo", []) == []


def test_parent_ref_rejects_bad_values() -> None:
    with pytest.raises(Exception, match="object ID"):
        ParentRef(id="ok", commit="nothex", relationship=Relationship.EXTENDS)
    with pytest.raises(Exception, match="experiment ID"):
        ParentRef(id="Bad ID", commit=OID, relationship=Relationship.EXTENDS)


def test_relationship_is_a_closed_enum() -> None:
    assert Relationship("extends") is Relationship.EXTENDS
    with pytest.raises(ValueError):
        Relationship("derived_from")  # the spec's old default is not a value
    with pytest.raises(ValueError):
        Relationship("EXTENDS")  # case-sensitive
