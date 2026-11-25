"""Typed errors for the scientist library.

Every error carries a stable ``code`` (used by the HTTP layer in a later
milestone) and a human-readable ``message``. Errors never mutate the research
repository; they only report invalid state.
"""

from __future__ import annotations


class ScientistError(Exception):
    """Base class for all scientist errors."""

    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RepositoryError(ScientistError):
    """The supplied path is not a usable research repository."""

    code = "invalid_repository"


class GitError(ScientistError):
    """An unexpected Git failure (not a validation failure)."""

    code = "git_error"

    def __init__(self, message: str, *, command: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.command = command


class GitTimeoutError(GitError):
    """A Git command exceeded its timeout."""

    code = "git_timeout"


class ManifestError(ScientistError):
    """An experiment branch has a missing or invalid manifest.

    Carries the full branch name plus a specific reason so a researcher can
    repair the repository with ordinary Git.
    """

    code = "invalid_manifest"

    def __init__(self, branch: str, reason: str) -> None:
        self.branch = branch
        self.reason = reason
        super().__init__(f"Invalid experiment branch '{branch}': {reason}")


class GraphError(ScientistError):
    """The experiment graph is structurally invalid (dangling parents,
    duplicate IDs, self-edges, cycles, or invalid parent pins)."""

    code = "invalid_graph"


class NotFoundError(ScientistError):
    """An unknown experiment ID or missing Git object."""

    code = "not_found"


class InvalidArgumentError(ScientistError):
    """A malformed argument such as an experiment ID that fails validation."""

    code = "invalid_argument"


class RefConflictError(ScientistError):
    """A target experiment branch already exists; nothing was overwritten.

    Raised before any ref publication, and again after a failed transactional
    publish if a competing writer won the race.
    """

    code = "ref_conflict"


# File-inspection errors (HTTP status mapping lives in api.py and must be
# updated when a new code is added here).
class FileTooLargeError(ScientistError):
    """A text preview exceeds the size limit; content is never truncated."""

    code = "file_too_large"


class ListingLimitError(ScientistError):
    """A recursive file listing exceeds the entry cap."""

    code = "listing_too_large"


class UnsupportedContentError(ScientistError):
    """A preview was requested for binary data, a symlink or a submodule."""

    code = "unsupported_content"


class UnsupportedPathError(ScientistError):
    """A committed path cannot be represented (e.g. non-UTF-8)."""

    code = "unsupported_path"
