"""Milestone 3 tests: committed file inspection (spec section 3.3)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import add_experiment, advance_branch, run_git

from scientist import (
    FileTooLargeError,
    InvalidArgumentError,
    ListingLimitError,
    NotFoundError,
    ResearchRepository,
    UnsupportedContentError,
    UnsupportedPathError,
)

README_TEXT = "# Title   \nline with trailing space   \n\nunicode: café ✓\n"


@pytest.fixture
def files_repo(repo: Path) -> Path:
    """An experiment whose commit contains tricky-but-legal files."""
    add_experiment(repo, "baseline")
    run_git(repo, "checkout", "--quiet", "experiments/baseline")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (repo / "README.md").write_text(README_TEXT, encoding="utf-8")
    (repo / "file with spaces.md").write_text("spaces ok\n", encoding="utf-8")
    (repo / "glob[1]*.txt").write_text("literal glob chars\n", encoding="utf-8")
    (repo / "empty.txt").write_text("", encoding="utf-8")
    (repo / "bin.dat").write_bytes(b"\xff\xd8\xff\xe0\x00\x10binary\x00data")
    (repo / "big.txt").write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    (repo / "link.md").symlink_to("README.md")
    # A gitlink (submodule entry) without any network access:
    main_commit = run_git(repo, "rev-parse", "main").strip()
    run_git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{main_commit},vendorlib",
    )
    run_git(
        repo,
        "add",
        "src",
        "README.md",
        "file with spaces.md",
        "glob[1]*.txt",
        "empty.txt",
        "bin.dat",
        "big.txt",
        "link.md",
    )
    run_git(repo, "commit", "--quiet", "--no-verify", "-m", "files")
    run_git(repo, "checkout", "--quiet", "main")
    return repo


def list_paths(rr: ResearchRepository, commit: str | None = None) -> dict[str, str]:
    return {e.path: e.kind for e in rr.list_files("baseline", commit=commit)}


# --- listing -------------------------------------------------------------------


def test_list_files_kinds_and_order(files_repo: Path) -> None:
    rr = ResearchRepository(files_repo)
    kinds = list_paths(rr)
    assert kinds["experiment.json"] == "file"
    assert kinds["src/main.py"] == "file"
    assert kinds["link.md"] == "symlink"
    assert kinds["vendorlib"] == "submodule"
    assert list(kinds) == sorted(kinds)  # deterministic path order
    sizes = {e.path: e.size for e in rr.list_files("baseline")}
    assert sizes["empty.txt"] == 0
    assert sizes["vendorlib"] == -1  # not applicable for submodules
    assert sizes["big.txt"] == 256 * 1024 + 1


def test_list_files_untracked_and_uncommitted_are_invisible(repo: Path) -> None:
    add_experiment(repo, "baseline")
    run_git(repo, "checkout", "--quiet", "experiments/baseline")
    (repo / "committed.txt").write_text("in\n", encoding="utf-8")
    run_git(repo, "add", "committed.txt")
    run_git(repo, "commit", "--quiet", "--no-verify", "-m", "add committed")
    (repo / "untracked.txt").write_text("out\n", encoding="utf-8")
    (repo / "staged.txt").write_text("out\n", encoding="utf-8")
    run_git(repo, "add", "staged.txt")
    run_git(repo, "checkout", "--quiet", "main")

    paths = list_paths(ResearchRepository(repo))
    assert "committed.txt" in paths
    assert "untracked.txt" not in paths
    assert "staged.txt" not in paths


def test_listing_limit_error(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    add_experiment(repo, "baseline")
    advance_branch(repo, "experiments/baseline", "a.txt", "a\n")
    advance_branch(repo, "experiments/baseline", "b.txt", "b\n")
    monkeypatch.setattr("scientist.repository.MAX_LISTING_ENTRIES", 2)
    with pytest.raises(ListingLimitError, match="limit"):
        ResearchRepository(repo).list_files("baseline")


def test_non_utf8_path_is_a_clear_error(repo: Path) -> None:
    add_experiment(repo, "baseline")
    # Rebuild the tip tree with one non-UTF-8 filename alongside the manifest,
    # using hash-object/mktree/commit-tree plumbing.
    data_blob = (
        subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=b"data\n",
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    manifest_blob = run_git(repo, "rev-parse", "experiments/baseline:experiment.json").strip()
    tree_input = (
        b"100644 blob " + manifest_blob.encode() + b"\texperiment.json\n"
        b"100644 blob " + data_blob.encode() + b"\t" + b"bad\xff\xfe.txt\n"
    )
    tree = (
        subprocess.run(
            ["git", "-C", str(repo), "mktree"],
            input=tree_input,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    commit = (
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "commit-tree",
                tree,
                "-p",
                run_git(repo, "rev-parse", "experiments/baseline").strip(),
                "-m",
                "nonutf8",
            ],
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    run_git(repo, "update-ref", "refs/heads/experiments/baseline", commit)
    with pytest.raises(UnsupportedPathError, match="non-UTF-8"):
        ResearchRepository(repo).list_files("baseline")


# --- reading -------------------------------------------------------------------


def test_read_text_preserves_whitespace_and_unicode(files_repo: Path) -> None:
    rr = ResearchRepository(files_repo)
    text = rr.read_text("baseline", "README.md")
    assert text.content == README_TEXT  # trailing spaces and blank lines intact
    assert text.path == "README.md"
    assert text.commit == run_git(files_repo, "rev-parse", "experiments/baseline").strip()


def test_read_text_special_filenames_are_literal(files_repo: Path) -> None:
    rr = ResearchRepository(files_repo)
    assert rr.read_text("baseline", "file with spaces.md").content == "spaces ok\n"
    assert rr.read_text("baseline", "glob[1]*.txt").content == "literal glob chars\n"


def test_read_text_empty_file(files_repo: Path) -> None:
    assert ResearchRepository(files_repo).read_text("baseline", "empty.txt").content == ""


def test_read_text_historical_commit(files_repo: Path) -> None:
    rr = ResearchRepository(files_repo)
    head = run_git(files_repo, "rev-parse", "experiments/baseline").strip()
    old = advance_branch(files_repo, "experiments/baseline", "new.md", "newer\n")
    assert old != head
    assert "new.md" not in list_paths(rr, commit=head)
    text = rr.read_text("baseline", "README.md", commit=head)
    assert text.commit == head
    with pytest.raises(NotFoundError):
        rr.read_text("baseline", "new.md", commit=head)


def test_read_text_rejects_unsupported_and_missing(files_repo: Path) -> None:
    rr = ResearchRepository(files_repo)
    with pytest.raises(UnsupportedContentError, match="symlink"):
        rr.read_text("baseline", "link.md")
    with pytest.raises(UnsupportedContentError, match=r"submodule|gitlink"):
        rr.read_text("baseline", "vendorlib")
    with pytest.raises(UnsupportedContentError, match="binary"):
        rr.read_text("baseline", "bin.dat")
    with pytest.raises(FileTooLargeError, match="never truncated"):
        rr.read_text("baseline", "big.txt")
    with pytest.raises(NotFoundError):
        rr.read_text("baseline", "nope.txt")
    with pytest.raises(NotFoundError):
        rr.read_text("baseline", "src")


def test_read_text_rejects_bad_paths(files_repo: Path) -> None:
    rr = ResearchRepository(files_repo)
    for bad in ("../README.md", "..", "a/./b", "/abs/path", "back\\slash", ""):
        with pytest.raises(InvalidArgumentError, match="path"):
            rr.read_text("baseline", bad)


def test_preview_limit_configurable(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    add_experiment(repo, "baseline")
    advance_branch(repo, "experiments/baseline", "tiny.txt", "12345\n")
    monkeypatch.setattr("scientist.repository.MAX_PREVIEW_BYTES", 4)
    with pytest.raises(FileTooLargeError):
        ResearchRepository(repo).read_text("baseline", "tiny.txt")


# --- revision validation ---------------------------------------------------------


def test_commit_outside_allowed_history_rejected(repo: Path) -> None:
    add_experiment(repo, "baseline")
    add_experiment(repo, "other")
    other_tip = run_git(repo, "rev-parse", "experiments/other").strip()
    rr = ResearchRepository(repo)
    with pytest.raises(InvalidArgumentError, match="outside the history"):
        rr.list_files("baseline", commit=other_tip)
    with pytest.raises(InvalidArgumentError):
        rr.read_text("baseline", "README.md", commit=other_tip)


def test_commit_must_match_experiment_manifest(repo: Path) -> None:
    # A commit reachable from the head but carrying a different experiment's
    # manifest is still rejected: no cross-experiment revision access.
    add_experiment(repo, "baseline")
    baseline_tip = run_git(repo, "rev-parse", "experiments/baseline").strip()
    add_experiment(repo, "child", base="experiments/baseline")
    child_tip = run_git(repo, "rev-parse", "experiments/child").strip()
    rr = ResearchRepository(repo)
    # baseline's own tip is fine:
    assert rr.resolve_revision("baseline", commit=baseline_tip) == baseline_tip
    # child's tip is reachable from child but its manifest says "child":
    assert rr.resolve_revision("child", commit=child_tip) == child_tip

    # A side branch whose tip carries a manifest for a *different* ID, merged
    # into baseline and then corrected, stays reachable from baseline's head.
    run_git(repo, "checkout", "--quiet", "-b", "side", "experiments/baseline")
    (repo / "experiment.json").write_text(
        '{"id": "other", "title": "Other", "description": "", "parents": []}\n',
        encoding="utf-8",
    )
    run_git(repo, "add", "experiment.json")
    run_git(repo, "commit", "--quiet", "--no-verify", "-m", "other manifest")
    foreign = run_git(repo, "rev-parse", "HEAD").strip()
    run_git(repo, "checkout", "--quiet", "experiments/baseline")
    run_git(repo, "merge", "--quiet", "--no-edit", "side")
    (repo / "experiment.json").write_text(
        '{"id": "baseline", "title": "Baseline", "description": "", "parents": []}\n',
        encoding="utf-8",
    )
    run_git(repo, "add", "experiment.json")
    run_git(repo, "commit", "--quiet", "--no-verify", "-m", "restore baseline manifest")
    run_git(repo, "checkout", "--quiet", "main")

    with pytest.raises(InvalidArgumentError, match="belongs to experiment"):
        rr.list_files("baseline", commit=foreign)
    # the corrected head remains usable:
    assert rr.resolve_revision("baseline") != baseline_tip


def test_file_reads_leave_repository_untouched(files_repo: Path) -> None:
    before = run_git(files_repo, "status", "--porcelain")
    refs_before = run_git(files_repo, "for-each-ref")
    rr = ResearchRepository(files_repo)
    rr.list_files("baseline")
    rr.read_text("baseline", "README.md")
    assert run_git(files_repo, "status", "--porcelain") == before
    assert run_git(files_repo, "for-each-ref") == refs_before
