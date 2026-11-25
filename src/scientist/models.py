"""Domain models. These names are the public contract defined by the spec.

Manifest fields are validated strictly (unknown fields are rejected) so
malformed manifests never pass silently.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# Full lowercase hex object IDs: SHA-1 (40) or SHA-256 (64). The repository
# layer additionally checks the length against the repository's object format.
HEX_PATTERN = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 16_000
MAX_RELATIONSHIP_LENGTH = 100  # retained for documentation; enum values are shorter


def _check_id(value: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise ValueError(f"invalid experiment ID {value!r}; must match {ID_PATTERN.pattern}")
    return value


def _check_commit(value: str) -> str:
    if not HEX_PATTERN.fullmatch(value):
        raise ValueError(f"invalid full object ID {value!r}")
    return value


class Relationship(StrEnum):
    """How a child experiment relates to this parent.

    Closed vocabulary (a deliberate deviation from the spec's open
    vocabulary; see docs/decisions.md). The mutation operations write
    ``extends`` / ``split_from`` / ``combines``; ``replicates`` and
    ``validates`` are authored when registering independent evidence.
    """

    EXTENDS = "extends"
    SPLIT_FROM = "split_from"
    COMBINES = "combines"
    REPLICATES = "replicates"
    VALIDATES = "validates"


class ParentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    commit: str = Field(min_length=1)
    # Required: the spec's default (``derived_from``) is not part of the
    # closed vocabulary, so there is no sensible default to inherit.
    relationship: Relationship

    _validate_id = field_validator("id", mode="after")(_check_id)
    _validate_commit = field_validator("commit", mode="after")(_check_commit)


class ExperimentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    # Required array; empty for a root experiment.
    parents: list[ParentRef]

    _validate_id = field_validator("id", mode="after")(_check_id)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value

    @model_validator(mode="after")
    def _parents_consistent(self) -> ExperimentManifest:
        seen: set[str] = set()
        for parent in self.parents:
            if parent.id == self.id:
                raise ValueError(f"experiment {self.id!r} cannot list itself as a parent")
            if parent.id in seen:
                raise ValueError(f"duplicate parent {parent.id!r}")
            seen.add(parent.id)
        return self


class Experiment(BaseModel):
    """An experiment node: its branch, captured head commit and manifest."""

    model_config = ConfigDict(extra="forbid")

    branch: str
    commit: str
    manifest: ExperimentManifest

    _validate_commit = field_validator("commit", mode="after")(_check_commit)


class Edge(BaseModel):
    """A directed scientific edge, parent -> child."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    source_commit: str
    relationship: Relationship

    _validate_source_commit = field_validator("source_commit", mode="after")(_check_commit)


class ExperimentGraph(BaseModel):
    """The full experiment graph at a captured ref view.

    Holds no open Git resources. Nodes are ordered by ID; edges by
    (source, target).
    """

    model_config = ConfigDict(extra="forbid")

    nodes: list[Experiment]
    edges: list[Edge]


class NewExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)

    _validate_id = field_validator("id", mode="after")(_check_id)


class FileKind(StrEnum):
    """Kind of a committed tree entry, as listed (never followed)."""

    FILE = "file"
    SYMLINK = "symlink"
    SUBMODULE = "submodule"


class FileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    #: Byte size of the blob; -1 when not applicable (submodules).
    size: int
    kind: FileKind


class TextFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    commit: str
    content: str

    _validate_commit = field_validator("commit", mode="after")(_check_commit)


class FileListing(BaseModel):
    """Response of the files endpoint: one pinned commit plus its entries."""

    model_config = ConfigDict(extra="forbid")

    commit: str
    files: list[FileEntry]

    _validate_commit = field_validator("commit", mode="after")(_check_commit)


def manifest_to_bytes(manifest: ExperimentManifest) -> bytes:
    """Deterministic UTF-8 JSON: indentation, field order, trailing newline."""
    data = manifest.model_dump(mode="json")
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
