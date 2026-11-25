"""Milestone 2 acceptance tests: Git-native mutations against real repositories."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import add_experiment, advance_branch, init_repo, run_git

from scientist import (
    GitError,
    GraphError,
    InvalidArgumentError,
    NewExperiment,
    RefConflictError,
    Relationship,
    ResearchRepository,
)


def tree_files(repo: Path, commit: str) -> set[str]:
    return set(run_git(repo, "ls-tree", "-r", "--name-only", commit).splitlines())


def file_at(repo: Path, commit: str, path: str) -> str:
    return run_git(repo, "show", f"{commit}:{path}")


def commit_parents(repo: Path, commit: str) -> list[str]:
    return run_git(repo, "log", "-1", "--format=%P", commit).split()


def spec(exp_id: str, title: str = "T") -> NewExperiment:
    return NewExperiment(id=exp_id, title=title)


# --- create --------------------------------------------------------------------


def test_root_inherits_base_files_with_new_manifest_and_no_edge(repo: Path) -> None:
    main_commit = run_git(repo, "rev-parse", "main").strip()
    rr = ResearchRepository(repo)
    experiment = rr.create_experiment(spec("baseline", "Baseline"), base="refs/heads/main")

    assert experiment.manifest.id == "baseline"
    assert experiment.manifest.parents == []
    assert tree_files(repo, experiment.commit) == {"README.md", "experiment.json"}
    assert commit_parents(repo, experiment.commit) == [main_commit]

    graph = rr.get_graph()
    assert [n.manifest.id for n in graph.nodes] == ["baseline"]
    assert graph.edges == []


def test_create_accepts_raw_commit_id_as_base(repo: Path) -> None:
    main_commit = run_git(repo, "rev-parse", "main").strip()
    experiment = ResearchRepository(repo).create_experiment(spec("root"), base=main_commit)
    assert commit_parents(repo, experiment.commit) == [main_commit]


def test_create_with_missing_base_rejected(repo: Path) -> None:
    rr = ResearchRepository(repo)
    with pytest.raises(InvalidArgumentError):
        rr.create_experiment(spec("x"), base="refs/heads/nonexistent")
    with pytest.raises(InvalidArgumentError):
        rr.create_experiment(spec("x"), base="f" * 40)
    assert run_git(repo, "for-each-ref", "refs/heads/experiments/").strip() == ""


def test_create_source_branch_untouched(repo: Path) -> None:
    main_before = run_git(repo, "rev-parse", "main").strip()
    ResearchRepository(repo).create_experiment(spec("baseline"), base="main")
    assert run_git(repo, "rev-parse", "main").strip() == main_before


def test_directory_named_experiment_json_rejected(repo: Path) -> None:
    run_git(repo, "checkout", "--quiet", "main")
    (repo / "experiment.json").mkdir()
    (repo / "experiment.json" / "nested.txt").write_text("oops\n", encoding="utf-8")
    run_git(repo, "add", "experiment.json")
    run_git(repo, "commit", "--quiet", "-m", "dir collision")
    with pytest.raises(InvalidArgumentError, match=r"experiment.json"):
        ResearchRepository(repo).create_experiment(spec("x"), base="main")
    assert run_git(repo, "for-each-ref", "refs/heads/experiments/").strip() == ""


# --- extend --------------------------------------------------------------------


def test_extend_inherits_pinned_tree_replacing_only_manifest(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline"), base="main")
    advance_branch(repo, "experiments/baseline", "results.md", "initial results\n")

    child = rr.extend_experiment("baseline", spec("double-q", "Double Q"))
    baseline_tip = run_git(repo, "rev-parse", "experiments/baseline").strip()

    assert tree_files(repo, child.commit) == tree_files(repo, baseline_tip)
    manifest_text = file_at(repo, child.commit, "experiment.json")
    assert json.loads(manifest_text)["id"] == "double-q"
    assert manifest_text.startswith('{\n  "id": "double-q"')
    assert manifest_text.endswith("\n")
    assert commit_parents(repo, child.commit) == [baseline_tip]

    edge = next(e for e in rr.get_graph().edges if e.target == "double-q")
    assert edge.source == "baseline"
    assert edge.source_commit == baseline_tip
    assert edge.relationship == Relationship.EXTENDS


def test_extend_with_historical_parent_commit(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline"), base="main")
    old_tip = advance_branch(repo, "experiments/baseline", "v1.md", "version 1\n")
    new_tip = advance_branch(repo, "experiments/baseline", "v2.md", "version 2\n")
    assert old_tip != new_tip

    child = rr.extend_experiment("baseline", spec("child"), parent_commit=old_tip)
    assert "v1.md" in tree_files(repo, child.commit)
    assert "v2.md" not in tree_files(repo, child.commit)
    edge = next(e for e in rr.get_graph().edges if e.target == "child")
    assert edge.source_commit == old_tip  # pin fixed at creation time


def test_extend_rejects_unreachable_parent_commit(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline"), base="main")
    # Orphan commit carrying a *valid baseline manifest* but no Git ancestry:
    # passes manifest checks, fails reachability from the parent's tip.
    baseline_tree = run_git(repo, "rev-parse", "experiments/baseline^{tree}").strip()
    orphan = run_git(repo, "commit-tree", baseline_tree, "-m", "orphan").strip()
    with pytest.raises(InvalidArgumentError, match="reachable"):
        rr.extend_experiment("baseline", spec("child"), parent_commit=orphan)
    # Nonexistent and wrong-format pins are rejected too.
    with pytest.raises(InvalidArgumentError):
        rr.extend_experiment("baseline", spec("child"), parent_commit="0" * 40)
    with pytest.raises(InvalidArgumentError):
        rr.extend_experiment("baseline", spec("child"), parent_commit="A" * 40)


def test_mutation_on_invalid_graph_rejected(repo: Path) -> None:
    # A child pointing at a missing parent makes the whole graph invalid;
    # mutations must refuse to run on top of it.
    main_commit = run_git(repo, "rev-parse", "main").strip()
    add_experiment(
        repo,
        "broken",
        parents=[{"id": "ghost", "commit": main_commit, "relationship": "extends"}],
    )
    rr = ResearchRepository(repo)
    with pytest.raises(GraphError):
        rr.create_experiment(spec("later"), base="main")


# --- split ---------------------------------------------------------------------


def test_split_creates_children_from_same_pin_and_preserves_parent(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline"), base="main")
    tip = advance_branch(repo, "experiments/baseline", "data.md", "dataset\n")

    children = rr.split_experiment(
        "baseline", [spec("gaussian", "Gaussian"), spec("double-q", "Double Q")]
    )
    assert [c.manifest.id for c in children] == ["gaussian", "double-q"]
    assert run_git(repo, "rev-parse", "experiments/baseline").strip() == tip

    edges = {(e.source, e.target): e for e in rr.get_graph().edges}
    for child_id in ("gaussian", "double-q"):
        edge = edges[("baseline", child_id)]
        assert edge.source_commit == tip
        assert edge.relationship == Relationship.SPLIT_FROM
        child_tip = run_git(repo, "rev-parse", f"experiments/{child_id}").strip()
        assert tree_files(repo, child_tip) == tree_files(repo, tip)
        assert json.loads(file_at(repo, child_tip, "experiment.json"))["id"] == child_id


def test_split_requires_at_least_two_children(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline"), base="main")
    with pytest.raises(InvalidArgumentError, match="at least two"):
        rr.split_experiment("baseline", [spec("only-one")])


def test_split_rejects_duplicate_child_ids(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline"), base="main")
    with pytest.raises(InvalidArgumentError, match="duplicate"):
        rr.split_experiment("baseline", [spec("x"), spec("x")])


def test_split_with_preexisting_branch_creates_nothing(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline"), base="main")
    # A competing writer already created a valid experiment with this ID.
    rr.create_experiment(spec("double-q"), base="main")
    baseline_tip = run_git(repo, "rev-parse", "experiments/baseline").strip()
    double_q_tip = run_git(repo, "rev-parse", "experiments/double-q").strip()
    with pytest.raises(RefConflictError, match="experiments/double-q"):
        rr.split_experiment("baseline", [spec("gaussian"), spec("double-q")])
    # transactional: the other child must not exist either, originals intact
    assert (
        run_git(
            repo, "rev-parse", "--verify", "--quiet", "refs/heads/experiments/gaussian", check=False
        )
        == ""
    )
    assert run_git(repo, "rev-parse", "experiments/baseline").strip() == baseline_tip
    assert run_git(repo, "rev-parse", "experiments/double-q").strip() == double_q_tip


# --- merge ----------------------------------------------------------------------


def test_merge_combines_parents_without_merging_code(repo: Path) -> None:
    rr = ResearchRepository(repo)
    run_git(repo, "checkout", "--quiet", "main")
    (repo / "shared.txt").write_text("shared\n", encoding="utf-8")
    run_git(repo, "add", "shared.txt")
    run_git(repo, "commit", "--quiet", "-m", "shared file")

    rr.create_experiment(spec("exp1"), base="main")
    rr.create_experiment(spec("exp2"), base="main")
    exp2_tip = advance_branch(repo, "experiments/exp2", "only-on-2.txt", "exclusive\n")
    exp1_tip = run_git(repo, "rev-parse", "experiments/exp1").strip()

    child = rr.merge_experiments(["exp1", "exp2"], spec("joint", "Joint"), base_parent_id="exp1")

    # inherits the base parent's tree exactly, apart from the manifest:
    assert tree_files(repo, child.commit) == tree_files(repo, exp1_tip)
    assert "only-on-2.txt" not in tree_files(repo, child.commit)  # no code merge
    assert commit_parents(repo, child.commit) == [exp1_tip]
    assert json.loads(file_at(repo, child.commit, "experiment.json"))["id"] == "joint"

    edges = {(e.source, e.target): e for e in rr.get_graph().edges}
    joint_edges = [edges[("exp1", "joint")], edges[("exp2", "joint")]]
    assert all(e.relationship == Relationship.COMBINES for e in joint_edges)
    assert edges[("exp1", "joint")].source_commit == exp1_tip
    assert edges[("exp2", "joint")].source_commit == exp2_tip

    # originals preserved:
    assert run_git(repo, "rev-parse", "experiments/exp1").strip() == exp1_tip
    assert run_git(repo, "rev-parse", "experiments/exp2").strip() == exp2_tip


def test_merge_validates_parents_and_base(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("a"), base="main")
    rr.create_experiment(spec("b"), base="main")
    with pytest.raises(InvalidArgumentError, match="base parent"):
        rr.merge_experiments(["a", "b"], spec("j"), base_parent_id="ghost")
    with pytest.raises(InvalidArgumentError, match="at least two"):
        rr.merge_experiments(["a"], spec("j"), base_parent_id="a")
    with pytest.raises(InvalidArgumentError, match="distinct"):
        rr.merge_experiments(["a", "a"], spec("j"), base_parent_id="a")


# --- collisions, identity, and repository hygiene --------------------------------


def test_duplicate_id_never_overwrites_existing_branch(repo: Path) -> None:
    rr = ResearchRepository(repo)
    original = rr.create_experiment(spec("baseline"), base="main")
    original_tip = run_git(repo, "rev-parse", "experiments/baseline").strip()
    with pytest.raises(RefConflictError, match="already exists"):
        rr.create_experiment(spec("baseline"), base="main")
    with pytest.raises(RefConflictError):
        rr.extend_experiment("baseline", spec("baseline"))
    assert run_git(repo, "rev-parse", "experiments/baseline").strip() == original_tip
    assert original.manifest.id == "baseline"


def test_missing_git_identity_fails_without_creating_refs(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    noident = init_repo(repo.parent / "noident")
    run_git(noident, "config", "--unset", "user.name")
    run_git(noident, "config", "--unset", "user.email")
    # Forbid hostname auto-detection, and hide the developer's global
    # identity config from the library's git calls.
    run_git(noident, "config", "user.useConfigOnly", "true")
    import scientist.git as git_module

    empty_home = tmp_path / "no-home"
    empty_home.mkdir()
    monkeypatch.setitem(git_module._SAFE_ENV, "HOME", str(empty_home))
    monkeypatch.setitem(git_module._SAFE_ENV, "XDG_CONFIG_HOME", str(empty_home))

    rr = ResearchRepository(noident)
    with pytest.raises(GitError, match="identity"):
        rr.create_experiment(spec("baseline"), base="main")
    assert run_git(noident, "for-each-ref", "refs/heads/experiments/").strip() == ""


def test_real_index_and_worktree_untouched_by_mutations(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline"), base="main")
    run_git(repo, "checkout", "--quiet", "main")
    (repo / "staged.txt").write_text("staged change\n", encoding="utf-8")
    run_git(repo, "add", "staged.txt")
    (repo / "untracked.txt").write_text("scratch\n", encoding="utf-8")
    before_status = run_git(repo, "status", "--porcelain")
    head_before = run_git(repo, "rev-parse", "HEAD").strip()

    rr.extend_experiment("baseline", spec("child"))

    assert run_git(repo, "status", "--porcelain") == before_status
    assert run_git(repo, "rev-parse", "HEAD").strip() == head_before
    # the staged change is still staged, not committed anywhere:
    assert "staged.txt" in run_git(repo, "diff", "--cached", "--name-only")


# --- graph evolution after mutations ----------------------------------------------


def test_commits_advance_head_without_changing_child_pins(repo: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline"), base="main")
    rr.extend_experiment("baseline", spec("child"))
    pin_before = next(e for e in rr.get_graph().edges).source_commit

    advance_branch(repo, "experiments/baseline", "more.md", "more results\n")
    graph = rr.get_graph()  # stays valid
    edge = next(e for e in graph.edges if e.target == "child")
    assert edge.source_commit == pin_before
    assert next(n for n in graph.nodes if n.manifest.id == "baseline").commit != pin_before


def test_clone_preserves_the_graph(repo: Path, tmp_path: Path) -> None:
    rr = ResearchRepository(repo)
    rr.create_experiment(spec("baseline", "Baseline"), base="main")
    rr.extend_experiment("baseline", spec("double-q", "Double Q"))
    rr.split_experiment("baseline", [spec("gaussian"), spec("momentum")])
    rr.merge_experiments(["double-q", "gaussian"], spec("joint"), base_parent_id="double-q")

    clone = tmp_path / "clone-bare"
    subprocess.run(["git", "clone", "--quiet", "--bare", str(repo), str(clone)], check=True)
    cloned = ResearchRepository(clone).get_graph()
    assert len(cloned.nodes) == 5
    assert len(cloned.edges) == 5
    assert {n.manifest.id for n in cloned.nodes} == {
        "baseline",
        "double-q",
        "gaussian",
        "joint",
        "momentum",
    }
