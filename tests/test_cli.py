"""Tests for the agent-facing CLI (spec section 4.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import run_git

from scientist.cli import main


def cli(repo: Path, *argv: str) -> int:
    return main(["--repo", str(repo), *argv])


def test_graph_on_empty_repo_prints_empty_graph(repo: Path, capsys) -> None:
    assert cli(repo, "graph") == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"nodes": [], "edges": []}


def test_full_workflow_through_the_cli(repo: Path, capsys) -> None:
    assert cli(repo, "create", "baseline", "--title", "Baseline", "--base", "main") == 0
    capsys.readouterr()
    assert cli(repo, "extend", "baseline", "double-q", "--title", "Double Q") == 0
    experiment = json.loads(capsys.readouterr().out)
    assert experiment["manifest"]["id"] == "double-q"
    assert experiment["branch"] == "experiments/double-q"

    specs = repo / "children.json"
    specs.write_text(
        json.dumps(
            [
                {"id": "gaussian", "title": "Gaussian", "description": ""},
                {"id": "momentum", "title": "Momentum", "description": ""},
            ]
        ),
        encoding="utf-8",
    )
    assert cli(repo, "split", "baseline", "--specs", str(specs)) == 0
    children = json.loads(capsys.readouterr().out)
    assert [c["manifest"]["id"] for c in children] == ["gaussian", "momentum"]

    assert (
        cli(
            repo,
            "merge",
            "double-q",
            "gaussian",
            "--id",
            "joint-study",
            "--title",
            "Joint study",
            "--base-parent",
            "double-q",
        )
        == 0
    )
    capsys.readouterr()

    assert cli(repo, "graph") == 0
    graph = json.loads(capsys.readouterr().out)
    assert {n["manifest"]["id"] for n in graph["nodes"]} == {
        "baseline",
        "double-q",
        "gaussian",
        "momentum",
        "joint-study",
    }
    assert {(e["source"], e["target"]) for e in graph["edges"]} == {
        ("baseline", "double-q"),
        ("baseline", "gaussian"),
        ("baseline", "momentum"),
        ("double-q", "joint-study"),
        ("gaussian", "joint-study"),
    }


def test_cli_errors_go_to_stderr_with_nonzero_exit(repo: Path, capsys) -> None:
    assert cli(repo, "create", "baseline", "--title", "B", "--base", "main") == 0
    capsys.readouterr()
    assert cli(repo, "create", "baseline", "--title", "Again", "--base", "main") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ref_conflict" in captured.err
    assert "already exists" in captured.err
    # stderr, not the graph: nothing was overwritten
    assert run_git(repo, "show", "experiments/baseline:experiment.json").count('"id"') == 1


def test_cli_split_with_bad_specs_file(repo: Path, capsys) -> None:
    bad = repo / "bad.json"
    bad.write_text('{"not": "an array"}', encoding="utf-8")
    assert cli(repo, "split", "baseline", "--specs", str(bad)) == 1
    assert "must contain a JSON array" in capsys.readouterr().err


def test_cli_merge_help_states_no_code_merge(repo: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["merge", "--help"])
    assert exc_info.value.code == 0
    assert "does NOT merge code trees" in capsys.readouterr().out
