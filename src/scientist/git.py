"""Adapter around the native Git CLI.

All commands run with ``subprocess`` argument arrays (never a shell), a
controlled noninteractive environment, and timeouts. Reads never touch the
working tree, index or HEAD; ``GIT_OPTIONAL_LOCKS=0`` keeps Git from even
attempting index locks.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import GitError, GitTimeoutError, RepositoryError

DEFAULT_TIMEOUT_SECONDS = 30.0

_SAFE_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "LC_ALL": "C",  # stable, parseable command output
}


def resolve_git_dir(path: str | Path) -> Path:
    """Validate that *path* is a Git repository and return its absolute git dir.

    Supports normal working repositories and bare repositories (including
    linked worktrees). Nothing is initialized or modified.
    """
    candidate = Path(path)
    if not candidate.exists():
        raise RepositoryError(f"repository path does not exist: {candidate}")
    proc = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        env=_SAFE_ENV,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or "not a Git repository"
        raise RepositoryError(f"invalid repository at {candidate}: {detail}")
    return Path(proc.stdout.strip())


class Git:
    """Runs read-only Git commands against a fixed repository."""

    def __init__(self, git_dir: Path, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.git_dir = git_dir
        self.timeout = timeout

    def run(
        self, *args: str, input_bytes: bytes | None = None, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        """Run ``git --git-dir=<dir> <args>`` and return the completed process.

        Never raises on nonzero exit; callers that expect success should use
        :meth:`run_checked`. Timeout and spawn failures raise typed errors.
        *extra_env* is merged over the safe base environment (used, for
        example, to point ``GIT_INDEX_FILE`` at a temporary index).
        """
        command = ["git", f"--git-dir={self.git_dir}", *args]
        env = {**_SAFE_ENV, **extra_env} if extra_env else _SAFE_ENV
        try:
            return subprocess.run(
                command,
                capture_output=True,
                input=input_bytes,
                env=env,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitTimeoutError(
                f"git command timed out after {self.timeout:.0f}s: {' '.join(args)}",
                command=tuple(command),
            ) from exc
        except OSError as exc:
            raise GitError(f"failed to run git: {exc}", command=tuple(command)) from exc

    def run_checked(
        self, *args: str, input_bytes: bytes | None = None, extra_env: dict[str, str] | None = None
    ) -> bytes:
        proc = self.run(*args, input_bytes=input_bytes, extra_env=extra_env)
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise GitError(f"git {' '.join(args)} failed: {stderr}")
        return proc.stdout

    # --- repository facts -------------------------------------------------

    def object_format(self) -> str:
        out = self.run_checked("rev-parse", "--show-object-format").decode().strip()
        if out not in ("sha1", "sha256"):
            raise RepositoryError(f"unsupported repository object format: {out}")
        return out

    def has_any_commit(self) -> bool:
        proc = self.run("rev-list", "--all", "--max-count=1")
        return proc.returncode == 0 and bool(proc.stdout.strip())

    # --- refs and objects -------------------------------------------------

    def for_each_ref(self, prefix: str) -> list[tuple[str, str]]:
        """Return ``(refname, object ID)`` pairs under *prefix*, one snapshot."""
        out = self.run_checked("for-each-ref", "--format=%(refname) %(objectname)", prefix).decode(
            "utf-8", errors="strict"
        )
        pairs: list[tuple[str, str]] = []
        for line in out.splitlines():
            if not line:
                continue
            refname, _, oid = line.partition(" ")
            pairs.append((refname, oid))
        return pairs

    def ref_oid(self, ref: str) -> str | None:
        """Resolve a full ref to an object ID, or ``None`` if it does not exist."""
        proc = self.run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if proc.returncode != 0:
            return None
        return proc.stdout.decode().strip()

    def cat_file_type(self, oid: str) -> str | None:
        """Return the object type (``commit``/``tree``/``blob``/``tag``) or None."""
        proc = self.run("cat-file", "-t", oid)
        if proc.returncode != 0:
            return None
        return proc.stdout.decode().strip()

    def cat_file_bytes(self, kind: str, oid: str) -> bytes:
        return self.run_checked("cat-file", kind, oid)

    def ls_tree_entry(self, commit: str, path: str) -> tuple[str, str, str, int] | None:
        """Look up a literal path in a commit's tree.

        Returns ``(mode, object type, object ID, size)`` where size is -1 when
        Git reports no size (e.g. directories). ``None`` when the path is
        absent or does not match exactly.
        """
        out = self.run_checked("ls-tree", "-l", "-z", commit, "--", path)
        entries = [e for e in out.split(b"\x00") if e]
        if not entries:
            return None
        # Format: "<mode> <type> <oid> <size>\t<path>" (size is "-" for trees)
        meta, _, entry_path = entries[0].partition(b"\t")
        if entry_path.decode("utf-8", errors="surrogateescape") != path:
            return None
        # Format: "<mode> <type> <oid> <size>\t<path>". Git pads the size
        # column with spaces, so drop empty tokens. Size is "-" for trees.
        parts = [token for token in meta.split(b" ") if token]
        mode = parts[0].decode()
        kind = parts[1].decode()
        oid = parts[2].decode()
        size = -1 if parts[3] == b"-" else int(parts[3])
        return mode, kind, oid, size

    def merge_base_is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Whether *ancestor* is reachable from *descendant*.

        Exit status 1 means "not an ancestor" (a valid answer); any other
        failure is an error, per the spec.
        """
        proc = self.run("merge-base", "--is-ancestor", ancestor, descendant)
        if proc.returncode == 0:
            return True
        if proc.returncode == 1:
            return False
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git merge-base --is-ancestor {ancestor} {descendant} failed: {stderr}")
