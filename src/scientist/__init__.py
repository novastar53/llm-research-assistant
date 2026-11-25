"""Git-native, registry-free research experiment explorer."""

from .errors import (
    FileTooLargeError,
    GitError,
    GitTimeoutError,
    GraphError,
    InvalidArgumentError,
    ListingLimitError,
    ManifestError,
    NotFoundError,
    RefConflictError,
    RepositoryError,
    ScientistError,
    UnsupportedContentError,
    UnsupportedPathError,
)
from .models import (
    Edge,
    Experiment,
    ExperimentGraph,
    ExperimentManifest,
    FileEntry,
    FileKind,
    FileListing,
    NewExperiment,
    ParentRef,
    Relationship,
    TextFile,
)
from .repository import ResearchRepository

__all__ = [
    "Edge",
    "Experiment",
    "ExperimentGraph",
    "ExperimentManifest",
    "FileEntry",
    "FileKind",
    "FileListing",
    "FileTooLargeError",
    "GitError",
    "GitTimeoutError",
    "GraphError",
    "InvalidArgumentError",
    "ListingLimitError",
    "ManifestError",
    "NewExperiment",
    "NotFoundError",
    "ParentRef",
    "RefConflictError",
    "Relationship",
    "RepositoryError",
    "ResearchRepository",
    "ScientistError",
    "TextFile",
    "UnsupportedContentError",
    "UnsupportedPathError",
]

__version__ = "0.1.0"
