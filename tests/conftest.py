"""Shared fixtures: real temporary Git repositories (no mocks)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

BRANCH = "refs/heads/experiments/{}"


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed ({proc.returncode}):\n{proc.stderr}")
    return proc.stdout


def init_repo(path: Path, *, bare: bool = False, object_format: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["init", "--quiet"]
    if bare:
        args.append("--bare")
    else:
        args += ["-b", "main"]
    if object_format:
        args += ["--object-format", object_format]
    subprocess.run(["git", *args, str(path)], check=True, capture_output=True, text=True)
    if not bare:
        run_git(path, "config", "user.name", "Test Scientist")
        run_git(path, "config", "user.email", "test@example.com")
        run_git(path, "config", "commit.gpgsign", "false")
        (path / "README.md").write_text("# research\n", encoding="utf-8")
        run_git(path, "add", "README.md")
        run_git(path, "commit", "--quiet", "-m", "initial commit")
    return path


def manifest_dict(
    exp_id: str,
    *,
    title: str = "An experiment",
    description: str = "",
    parents: list[dict] | None = None,
) -> dict:
    return {
        "id": exp_id,
        "title": title,
        "description": description,
        "parents": parents if parents is not None else [],
    }


def parent_ref(repo: Path, parent_id: str, relationship: str = "extends") -> dict:
    commit = run_git(repo, "rev-parse", f"experiments/{parent_id}").strip()
    return {"id": parent_id, "commit": commit, "relationship": relationship}


def commit_manifest(
    repo: Path,
    branch: str,
    manifest: dict,
    *,
    message: str | None = None,
) -> str:
    """Write *manifest* as experiment.json on *branch* and commit it."""
    run_git(repo, "checkout", "--quiet", branch)
    (repo / "experiment.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    run_git(repo, "add", "experiment.json")
    run_git(
        repo,
        "commit",
        "--quiet",
        "--no-verify",
        "-m",
        message or f"manifest: {manifest['id']}",
    )
    return run_git(repo, "rev-parse", "HEAD").strip()


def add_experiment(
    repo: Path,
    exp_id: str,
    *,
    parents: list[dict] | None = None,
    title: str = "An experiment",
    description: str = "",
    base: str = "main",
) -> str:
    """Create experiments/<id> from *base* with a fresh manifest commit."""
    run_git(repo, "checkout", "--quiet", "-b", f"experiments/{exp_id}", base)
    manifest = manifest_dict(exp_id, title=title, description=description, parents=parents)
    return commit_manifest(repo, f"experiments/{exp_id}", manifest)


def advance_branch(repo: Path, branch: str, filename: str, content: str) -> str:
    """Commit a new file on *branch*, advancing its head."""
    run_git(repo, "checkout", "--quiet", branch)
    (repo / filename).write_text(content, encoding="utf-8")
    run_git(repo, "add", filename)
    run_git(repo, "commit", "--quiet", "--no-verify", "-m", f"add {filename}")
    return run_git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A normal working repository with one commit on main and no experiments."""
    return init_repo(tmp_path / "research")


@pytest.fixture
def diamond_repo(repo: Path) -> Path:
    """baseline -> {double-q, gaussian} -> joint-study (a diamond)."""
    add_experiment(repo, "baseline", title="Baseline")
    add_experiment(repo, "double-q", parents=[parent_ref(repo, "baseline")])
    add_experiment(repo, "gaussian", parents=[parent_ref(repo, "baseline")])
    add_experiment(
        repo,
        "joint-study",
        parents=[
            parent_ref(repo, "double-q", "combines"),
            parent_ref(repo, "gaussian", "combines"),
        ],
    )
    run_git(repo, "checkout", "--quiet", "main")
    return repo
