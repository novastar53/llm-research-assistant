"""Milestone 1 acceptance tests against real temporary Git repositories."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import (
    add_experiment,
    advance_branch,
    commit_manifest,
    init_repo,
    manifest_dict,
    parent_ref,
    run_git,
)

from scientist import (
    GraphError,
    InvalidArgumentError,
    ManifestError,
    NotFoundError,
    Relationship,
    RepositoryError,
    ResearchRepository,
)

# --- empty and ordinary repositories ----------------------------------------


def test_empty_namespace_produces_empty_graph(repo: Path) -> None:
    graph = ResearchRepository(repo).get_graph()
    assert graph.nodes == []
    assert graph.edges == []


def test_ordinary_branches_are_ignored(repo: Path) -> None:
    run_git(repo, "branch", "feature/not-an-experiment")
    run_git(repo, "branch", "experiments")  # a file branch, not the namespace
    graph = ResearchRepository(repo).get_graph()
    assert graph.nodes == []


def test_missing_path_rejected(tmp_path: Path) -> None:
    with pytest.raises(RepositoryError, match="does not exist"):
        ResearchRepository(tmp_path / "nope")


def test_non_repository_path_rejected(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(RepositoryError, match=r"not a Git repository|invalid repository"):
        ResearchRepository(plain)


def test_repository_without_commits_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(empty)], check=True)
    with pytest.raises(RepositoryError, match="no commits"):
        ResearchRepository(empty)


# --- the diamond graph -------------------------------------------------------


def test_diamond_graph_shape(diamond_repo: Path) -> None:
    graph = ResearchRepository(diamond_repo).get_graph()
    assert [n.manifest.id for n in graph.nodes] == [
        "baseline",
        "double-q",
        "gaussian",
        "joint-study",
    ]
    assert {(e.source, e.target, e.relationship) for e in graph.edges} == {
        ("baseline", "double-q", Relationship.EXTENDS),
        ("baseline", "gaussian", Relationship.EXTENDS),
        ("double-q", "joint-study", Relationship.COMBINES),
        ("gaussian", "joint-study", Relationship.COMBINES),
    }


def test_diamond_traversal(diamond_repo: Path) -> None:
    rr = ResearchRepository(diamond_repo)
    assert rr.get_ancestors("joint-study") == ["baseline", "double-q", "gaussian"]
    assert rr.get_descendants("baseline") == ["double-q", "gaussian", "joint-study"]
    assert rr.get_ancestors("baseline") == []
    assert rr.get_descendants("joint-study") == []
    assert rr.get_ancestors("double-q") == ["baseline"]
    assert rr.get_descendants("double-q") == ["joint-study"]
    # no duplicates, starting node excluded even on diamond reconvergence
    assert len(rr.get_ancestors("joint-study")) == len(set(rr.get_ancestors("joint-study")))


def test_edges_pin_historical_parent_commits(diamond_repo: Path) -> None:
    rr = ResearchRepository(diamond_repo)
    graph = rr.get_graph()
    by_target = {(e.source, e.target): e.source_commit for e in graph.edges}
    for parent, child in [("baseline", "double-q"), ("baseline", "gaussian")]:
        expected = run_git(diamond_repo, "rev-parse", f"experiments/{parent}").strip()
        assert by_target[(parent, child)] == expected


def test_parent_advancing_after_fork_keeps_child_valid(diamond_repo: Path) -> None:
    rr = ResearchRepository(diamond_repo)
    old_baseline = run_git(diamond_repo, "rev-parse", "experiments/baseline").strip()
    new_baseline = advance_branch(diamond_repo, "experiments/baseline", "notes.md", "more\n")

    graph = rr.get_graph()  # must not raise
    edge = next(e for e in graph.edges if e.target == "double-q")
    assert edge.source_commit == old_baseline  # pin unchanged
    baseline_node = next(n for n in graph.nodes if n.manifest.id == "baseline")
    assert baseline_node.commit == new_baseline  # head advanced


def test_scientific_edge_without_git_ancestry_is_accepted(repo: Path) -> None:
    add_experiment(repo, "baseline")
    # child is created from main, sharing no Git history with baseline:
    add_experiment(repo, "independent", parents=[parent_ref(repo, "baseline")])
    rr = ResearchRepository(repo)
    graph = rr.get_graph()
    assert ("baseline", "independent") in {(e.source, e.target) for e in graph.edges}
    assert rr.get_ancestors("independent") == ["baseline"]


def test_validates_relationship_allows_independent_validation(repo: Path) -> None:
    add_experiment(repo, "baseline")
    add_experiment(
        repo,
        "check",
        parents=[parent_ref(repo, "baseline", "validates")],
    )
    rr = ResearchRepository(repo)
    edge = rr.get_graph().edges[0]
    assert edge.relationship == Relationship.VALIDATES


# --- discovery and ordering ---------------------------------------------------


def test_results_are_deterministically_ordered(repo: Path) -> None:
    add_experiment(repo, "zeta")
    add_experiment(repo, "alpha")
    add_experiment(repo, "mid", parents=[parent_ref(repo, "zeta")])
    run_git(repo, "checkout", "--quiet", "main")
    graph = ResearchRepository(repo).get_graph()
    assert [n.manifest.id for n in graph.nodes] == ["alpha", "mid", "zeta"]
    assert [(e.source, e.target) for e in graph.edges] == [("zeta", "mid")]


def test_get_experiment_returns_branch_commit_manifest(diamond_repo: Path) -> None:
    rr = ResearchRepository(diamond_repo)
    exp = rr.get_experiment("double-q")
    assert exp.branch == "experiments/double-q"
    assert exp.commit == run_git(diamond_repo, "rev-parse", "experiments/double-q").strip()
    assert exp.manifest.id == "double-q"
    assert exp.manifest.title == "An experiment"
    assert [p.id for p in exp.manifest.parents] == ["baseline"]


def test_list_experiments_matches_graph_nodes(diamond_repo: Path) -> None:
    rr = ResearchRepository(diamond_repo)
    assert rr.list_experiments() == rr.get_graph().nodes


def test_unknown_experiment_raises_not_found(diamond_repo: Path) -> None:
    rr = ResearchRepository(diamond_repo)
    with pytest.raises(NotFoundError):
        rr.get_experiment("ghost")
    with pytest.raises(NotFoundError):
        rr.get_ancestors("ghost")


def test_malformed_id_raises_invalid_argument(diamond_repo: Path) -> None:
    rr = ResearchRepository(diamond_repo)
    with pytest.raises(InvalidArgumentError):
        rr.get_experiment("Bad ID")


# --- malformed manifests and branches ----------------------------------------


def test_manifest_id_must_match_branch_suffix(repo: Path) -> None:
    run_git(repo, "checkout", "--quiet", "-b", "experiments/alpha", "main")
    commit_manifest(repo, "experiments/alpha", manifest_dict("beta"))
    with pytest.raises(ManifestError) as exc_info:
        ResearchRepository(repo).get_graph()
    assert "experiments/alpha" in str(exc_info.value)
    assert "beta" in str(exc_info.value)


def test_missing_manifest_is_an_error(repo: Path) -> None:
    run_git(repo, "branch", "experiments/empty", "main")  # no experiment.json
    with pytest.raises(ManifestError, match=r"experiment.json"):
        ResearchRepository(repo).get_graph()


def test_invalid_branch_suffix_in_namespace_is_an_error(repo: Path) -> None:
    run_git(repo, "checkout", "--quiet", "-b", "experiments/Upper_Case", "main")
    commit_manifest(repo, "experiments/Upper_Case", manifest_dict("Upper_Case"))
    with pytest.raises(ManifestError) as exc_info:
        ResearchRepository(repo).get_graph()
    assert "Upper_Case" in str(exc_info.value)


def test_unknown_manifest_fields_rejected(repo: Path) -> None:
    manifest = manifest_dict("baseline")
    manifest["version"] = 3
    run_git(repo, "checkout", "--quiet", "-b", "experiments/baseline", "main")
    commit_manifest(repo, "experiments/baseline", manifest)
    with pytest.raises(ManifestError, match="version"):
        ResearchRepository(repo).get_graph()


def test_oversized_manifest_rejected(repo: Path) -> None:
    manifest = manifest_dict("baseline", description="x" * (256 * 1024))
    run_git(repo, "checkout", "--quiet", "-b", "experiments/baseline", "main")
    commit_manifest(repo, "experiments/baseline", manifest)
    with pytest.raises(ManifestError, match="limit"):
        ResearchRepository(repo).get_graph()


# --- graph-level parent validation -------------------------------------------


def test_missing_parent_branch_is_a_graph_error(repo: Path) -> None:
    main_commit = run_git(repo, "rev-parse", "main").strip()
    add_experiment(
        repo,
        "child",
        parents=[{"id": "ghost", "commit": main_commit, "relationship": "extends"}],
    )
    with pytest.raises(GraphError, match="experiments/ghost"):
        ResearchRepository(repo).get_graph()


def test_missing_historical_pin_object(repo: Path) -> None:
    add_experiment(repo, "baseline")
    add_experiment(
        repo,
        "child",
        parents=[{"id": "baseline", "commit": "0" * 40, "relationship": "extends"}],
    )
    with pytest.raises(GraphError, match=r"missing|not a commit"):
        ResearchRepository(repo).get_graph()


def test_pin_with_wrong_manifest_id(repo: Path) -> None:
    add_experiment(repo, "baseline")
    add_experiment(repo, "other")
    other_commit = run_git(repo, "rev-parse", "experiments/other").strip()
    add_experiment(
        repo,
        "child",
        parents=[{"id": "baseline", "commit": other_commit, "relationship": "extends"}],
    )
    with pytest.raises(GraphError, match="manifest ID"):
        ResearchRepository(repo).get_graph()


def test_pin_not_reachable_from_parent_tip(repo: Path) -> None:
    add_experiment(repo, "baseline")
    baseline_tree = run_git(repo, "rev-parse", "experiments/baseline^{tree}").strip()
    # Orphan commit: valid baseline manifest, but no Git ancestry at all.
    orphan = run_git(repo, "commit-tree", baseline_tree, "-m", "orphan").strip()
    add_experiment(
        repo,
        "child",
        parents=[{"id": "baseline", "commit": orphan, "relationship": "extends"}],
    )
    with pytest.raises(GraphError, match="reachable"):
        ResearchRepository(repo).get_graph()


def test_duplicate_parents_rejected(repo: Path) -> None:
    add_experiment(repo, "baseline")
    ref = parent_ref(repo, "baseline")
    run_git(repo, "checkout", "--quiet", "-b", "experiments/child", "main")
    commit_manifest(
        repo,
        "experiments/child",
        manifest_dict("child", parents=[ref, dict(ref)]),
    )
    with pytest.raises(ManifestError, match="duplicate parent"):
        ResearchRepository(repo).get_graph()


def test_self_edge_rejected(repo: Path) -> None:
    run_git(repo, "checkout", "--quiet", "-b", "experiments/loop", "main")
    self_ref = {
        "id": "loop",
        "commit": run_git(repo, "rev-parse", "HEAD").strip(),
        "relationship": "extends",
    }
    commit_manifest(repo, "experiments/loop", manifest_dict("loop", parents=[self_ref]))
    with pytest.raises(ManifestError, match="itself"):
        ResearchRepository(repo).get_graph()


def test_cycle_rejected(repo: Path) -> None:
    add_experiment(repo, "baseline")
    add_experiment(repo, "child-a", parents=[parent_ref(repo, "baseline")])
    # Repoint baseline's manifest at child-a, creating a 2-node cycle.
    run_git(repo, "checkout", "--quiet", "experiments/baseline")
    manifest = manifest_dict("baseline", parents=[parent_ref(repo, "child-a")])
    commit_manifest(repo, "experiments/baseline", manifest)
    with pytest.raises(GraphError, match="cycle"):
        ResearchRepository(repo).get_graph()


def test_wrong_object_format_pin_rejected(repo: Path) -> None:
    add_experiment(repo, "baseline")
    add_experiment(
        repo,
        "child",
        parents=[{"id": "baseline", "commit": "a" * 64, "relationship": "extends"}],
    )
    with pytest.raises(GraphError, match="sha1"):
        ResearchRepository(repo).get_graph()


# --- repository hygiene and object formats -----------------------------------


def test_dirty_worktree_unchanged_by_reads(repo: Path) -> None:
    add_experiment(repo, "baseline")
    run_git(repo, "checkout", "--quiet", "main")
    (repo / "README.md").write_text("# modified but not committed\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("scratch\n", encoding="utf-8")
    before = run_git(repo, "status", "--porcelain")

    rr = ResearchRepository(repo)
    rr.get_graph()
    rr.get_experiment("baseline")
    rr.get_ancestors("baseline")

    assert run_git(repo, "status", "--porcelain") == before
    assert run_git(repo, "rev-parse", "experiments/baseline") == run_git(
        repo, "rev-parse", "experiments/baseline"
    )


def test_bare_repository_supported(diamond_repo: Path, tmp_path: Path) -> None:
    bare = tmp_path / "research-bare"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(diamond_repo), str(bare)],
        check=True,
    )
    graph = ResearchRepository(bare).get_graph()
    assert len(graph.nodes) == 4
    assert len(graph.edges) == 4
    assert ResearchRepository(bare).get_descendants("baseline") == [
        "double-q",
        "gaussian",
        "joint-study",
    ]


def test_sha256_repository_supported(tmp_path: Path) -> None:
    repo256 = init_repo(tmp_path / "research256", object_format="sha256")
    add_experiment(repo256, "baseline")
    add_experiment(repo256, "child", parents=[parent_ref(repo256, "baseline")])
    graph = ResearchRepository(repo256).get_graph()
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert len(graph.edges[0].source_commit) == 64
