"""The public research repository interface (spec sections 3.1 and 4)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pydantic import ValidationError

from . import graph as graph_ops
from .errors import (
    FileTooLargeError,
    GitError,
    GraphError,
    InvalidArgumentError,
    ListingLimitError,
    ManifestError,
    NotFoundError,
    RefConflictError,
    RepositoryError,
    UnsupportedContentError,
    UnsupportedPathError,
)
from .git import Git, resolve_git_dir
from .models import (
    HEX_PATTERN,
    ID_PATTERN,
    Edge,
    Experiment,
    ExperimentGraph,
    ExperimentManifest,
    FileEntry,
    FileKind,
    NewExperiment,
    ParentRef,
    Relationship,
    TextFile,
    manifest_to_bytes,
)

BRANCH_PREFIX = "refs/heads/"  #: Git prefix for all local branches.
EXPERIMENT_PREFIX = "refs/heads/experiments/"  #: Reserved experiment namespace.
MANIFEST_PATH = "experiment.json"  #: Required manifest path, repo-relative.
MAX_MANIFEST_BYTES = 256 * 1024  #: Manifests larger than this are invalid.
MAX_PREVIEW_BYTES = 256 * 1024  #: Text previews larger than this are rejected.
MAX_LISTING_ENTRIES = 10_000  #: Recursive listings larger than this are rejected.


class ResearchRepository:
    """Opens an existing Git repository and projects its experiment graph.

    All persistent scientific state lives in the repository itself; instances
    of this class hold no open Git resources and never modify the repository.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        git_dir = resolve_git_dir(self.path)
        self._git = Git(git_dir)
        self._object_format = self._git.object_format()
        if not self._git.has_any_commit():
            raise RepositoryError(
                f"repository at {self.path} has no commits; a research repository "
                "needs at least one commit"
            )
        self._oid_length = 64 if self._object_format == "sha256" else 40

    # --- public read API ---------------------------------------------------

    def get_graph(self) -> ExperimentGraph:
        """Discover experiment branches and build the validated DAG.

        Refs are read once into a captured snapshot; each manifest is then
        read at its captured object ID. A malformed branch in the reserved
        namespace fails the whole request with a typed error naming the
        branch and reason.
        """
        refs = self._git.for_each_ref(EXPERIMENT_PREFIX)
        nodes: dict[str, Experiment] = {}
        for refname, oid in refs:
            node = self._discover_node(refname, oid)
            if node.manifest.id in nodes:
                raise GraphError(f"duplicate experiment ID: {node.manifest.id}")
            nodes[node.manifest.id] = node

        edges: list[Edge] = []
        for node in nodes.values():
            child_id = node.manifest.id
            for parent in node.manifest.parents:
                parent_node = nodes.get(parent.id)
                if parent_node is None:
                    raise GraphError(
                        f"Parent branch {BRANCH_PREFIX}experiments/{parent.id} "
                        f"referenced by '{node.branch}' is missing."
                    )
                self._validate_parent_pin(node.branch, parent, parent_node.commit)
                edges.append(
                    Edge(
                        source=parent.id,
                        target=child_id,
                        source_commit=parent.commit,
                        relationship=parent.relationship,
                    )
                )
        return graph_ops.assemble_graph(list(nodes.values()), edges)

    def list_experiments(self) -> list[Experiment]:
        return self.get_graph().nodes

    def get_experiment(self, experiment_id: str) -> Experiment:
        self._check_id(experiment_id)
        refname = f"{EXPERIMENT_PREFIX}{experiment_id}"
        oid = self._git.ref_oid(refname)
        if oid is None:
            raise NotFoundError(f"unknown experiment: {experiment_id}")
        return self._discover_node(refname, oid)

    def get_ancestors(self, experiment_id: str) -> list[str]:
        return self._traverse(experiment_id, forward=False)

    def get_descendants(self, experiment_id: str) -> list[str]:
        return self._traverse(experiment_id, forward=True)

    def _traverse(self, experiment_id: str, *, forward: bool) -> list[str]:
        self._check_id(experiment_id)
        result = self.get_graph()
        ids = {node.manifest.id for node in result.nodes}
        if experiment_id not in ids:
            raise NotFoundError(f"unknown experiment: {experiment_id}")
        if forward:
            return graph_ops.descendants(experiment_id, result.edges)
        return graph_ops.ancestors(experiment_id, result.edges)

    # --- committed file inspection (spec section 3.3) ------------------------

    def resolve_revision(self, experiment_id: str, *, commit: str | None = None) -> str:
        """Resolve the revision to inspect: the captured HEAD, or a validated pin.

        An explicit *commit* must be a full object ID reachable from the
        captured experiment head whose manifest identifies this experiment;
        anything else is an :class:`InvalidArgumentError` (never a silent
        fallback to HEAD).
        """
        self._check_id(experiment_id)
        experiment = self.get_experiment(experiment_id)
        if commit is None:
            return experiment.commit
        if not HEX_PATTERN.fullmatch(commit) or len(commit) != self._oid_length:
            raise InvalidArgumentError(
                f"commit {commit!r} is not a full {self._object_format} object ID"
            )
        if self._git.cat_file_type(commit) != "commit":
            raise InvalidArgumentError(f"commit {commit} does not exist or is not a commit")
        if not self._git.merge_base_is_ancestor(commit, experiment.commit):
            raise InvalidArgumentError(
                f"commit {commit} is outside the history of {experiment.branch}"
            )
        try:
            manifest = self._load_manifest(commit, experiment.branch)
        except ManifestError as exc:
            raise InvalidArgumentError(
                f"commit {commit} has no valid manifest for {experiment_id}: {exc.reason}"
            ) from exc
        if manifest.id != experiment_id:
            raise InvalidArgumentError(
                f"commit {commit} belongs to experiment {manifest.id!r}, not {experiment_id!r}"
            )
        return commit

    def list_files(self, experiment_id: str, *, commit: str | None = None) -> list[FileEntry]:
        """List committed files recursively at the resolved revision.

        Symlinks and submodules are listed as unsupported kinds and never
        followed. Entries are sorted by path; listings over the entry cap
        raise :class:`ListingLimitError` rather than pretending to be complete.
        """
        resolved = self.resolve_revision(experiment_id, commit=commit)
        out = self._git.run_checked("ls-tree", "-r", "-z", "-l", resolved)
        entries: list[FileEntry] = []
        for raw_entry in out.split(b"\x00"):
            if not raw_entry:
                continue
            meta, _, raw_path = raw_entry.partition(b"\t")
            # "<mode> <type> <oid> <size>"; Git pads the size column with
            # spaces, so drop empty tokens. Size is "-" for gitlinks.
            parts = [token for token in meta.split(b" ") if token]
            mode = parts[0].decode()
            kind = parts[1].decode()
            size = -1 if parts[3] == b"-" else int(parts[3])
            try:
                path = raw_path.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise UnsupportedPathError(
                    f"repository contains a non-UTF-8 path ({raw_path!r}) that cannot "
                    "be listed; rename it with ordinary Git"
                ) from exc
            entries.append(FileEntry(path=path, size=size, kind=self._file_kind(mode, kind, path)))
            if len(entries) > MAX_LISTING_ENTRIES:
                raise ListingLimitError(
                    f"file listing exceeds the limit of {MAX_LISTING_ENTRIES} entries"
                )
        entries.sort(key=lambda entry: entry.path)
        return entries

    def read_text(self, experiment_id: str, path: str, *, commit: str | None = None) -> TextFile:
        """Read a committed regular file as strict UTF-8 text (spec limits:
        256 KiB, no truncation, no smudge filters, no worktree reads).

        Raises :class:`NotFoundError` for missing paths,
        :class:`UnsupportedContentError` for symlinks/submodules/binary data,
        and :class:`FileTooLargeError` over the preview limit.
        """
        resolved = self.resolve_revision(experiment_id, commit=commit)
        self._check_repo_path(path)
        entry = self._git.ls_tree_entry(resolved, path)
        if entry is None:
            raise NotFoundError(f"no such committed file: {path}")
        mode, kind, blob_oid, size = entry
        if kind == "tree":
            raise NotFoundError(f"{path} is a directory, not a file")
        if kind != "blob" or mode == "120000":
            what = "a symlink" if mode == "120000" else "a submodule entry"
            raise UnsupportedContentError(f"{path} is {what}; only regular files can be previewed")
        if size > MAX_PREVIEW_BYTES:
            raise FileTooLargeError(
                f"{path} is {size} bytes; the preview limit is {MAX_PREVIEW_BYTES} "
                "and content is never truncated"
            )
        raw = self._git.cat_file_bytes("blob", blob_oid)
        if b"\x00" in raw:
            raise UnsupportedContentError(f"{path} contains NUL bytes and is treated as binary")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedContentError(
                f"{path} is not valid UTF-8; binary files have no preview"
            ) from exc
        return TextFile(path=path, commit=resolved, content=text)

    @staticmethod
    def _file_kind(mode: str, kind: str, path: str) -> FileKind:
        if kind == "commit" or mode == "160000":
            return FileKind.SUBMODULE
        if mode == "120000":
            return FileKind.SYMLINK
        if kind == "blob" and mode in ("100644", "100755"):
            return FileKind.FILE
        raise UnsupportedContentError(
            f"{path} has unsupported tree entry mode {mode} (type {kind})"
        )

    @staticmethod
    def _check_repo_path(path: str) -> None:
        if not path:
            raise InvalidArgumentError("path must not be empty")
        if "\x00" in path:
            raise InvalidArgumentError("path must not contain NUL characters")
        if "\\" in path:
            raise InvalidArgumentError("path must use forward slashes, not backslashes")
        if path.startswith("/"):
            raise InvalidArgumentError("path must be repository-relative, not absolute")
        components = path.split("/")
        if any(component in ("", ".", "..") for component in components):
            raise InvalidArgumentError(f"invalid repository path: {path!r}")

    # --- discovery internals ------------------------------------------------

    def _discover_node(self, refname: str, oid: str) -> Experiment:
        """Build and validate one experiment node at a captured object ID."""
        branch = refname[len(BRANCH_PREFIX) :]
        suffix = refname[len(EXPERIMENT_PREFIX) :]
        if not ID_PATTERN.fullmatch(suffix):
            raise ManifestError(
                branch,
                f"branch name suffix {suffix!r} is not a valid experiment ID "
                f"(must match {ID_PATTERN.pattern})",
            )
        if self._git.cat_file_type(oid) != "commit":
            raise ManifestError(branch, "ref does not point to a commit")
        manifest = self._load_manifest(oid, branch)
        if manifest.id != suffix:
            raise ManifestError(
                branch,
                f"manifest ID {manifest.id!r} does not match branch suffix {suffix!r}",
            )
        return Experiment(branch=branch, commit=oid, manifest=manifest)

    def _load_manifest(self, commit: str, branch: str) -> ExperimentManifest:
        """Read and strictly validate ``experiment.json`` at *commit*."""
        entry = self._git.ls_tree_entry(commit, MANIFEST_PATH)
        if entry is None:
            raise ManifestError(branch, f"missing required file {MANIFEST_PATH}")
        mode, kind, blob_oid, size = entry
        if kind == "commit":
            raise ManifestError(branch, f"{MANIFEST_PATH} is a submodule entry")
        if kind != "blob" or mode == "120000":
            raise ManifestError(branch, f"{MANIFEST_PATH} must be a regular file (mode {mode})")
        if size > MAX_MANIFEST_BYTES:
            raise ManifestError(
                branch, f"{MANIFEST_PATH} is {size} bytes; limit is {MAX_MANIFEST_BYTES}"
            )
        raw = self._git.cat_file_bytes("blob", blob_oid)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ManifestError(branch, f"{MANIFEST_PATH} is not valid UTF-8: {exc}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError(branch, f"{MANIFEST_PATH} is not valid JSON: {exc}") from exc
        try:
            return ExperimentManifest.model_validate(data)
        except ValidationError as exc:
            raise ManifestError(branch, f"{MANIFEST_PATH} failed validation: {exc}") from exc

    def _validate_parent_pin(self, child_branch: str, parent: ParentRef, parent_head: str) -> None:
        """Validate one historical parent pin (spec section 2.2).

        The pinned commit must exist, carry a manifest identifying the parent,
        and be reachable from the captured current tip of the parent's branch.
        Git ancestry between parent and child is deliberately NOT required.
        """
        pin = parent.commit
        parent_id = parent.id
        if len(pin) != self._oid_length:
            raise GraphError(
                f"'{child_branch}': parent {parent_id!r} pin {pin} is not a full "
                f"{self._object_format} object ID"
            )
        if self._git.cat_file_type(pin) != "commit":
            raise GraphError(
                f"'{child_branch}': parent {parent_id!r} pin {pin} is missing or not a commit"
            )
        try:
            pinned_manifest = self._load_manifest(pin, child_branch)
        except ManifestError as exc:
            raise GraphError(
                f"'{child_branch}': parent {parent_id!r} pin {pin} does not "
                f"contain a valid manifest: {exc.reason}"
            ) from exc
        if pinned_manifest.id != parent_id:
            raise GraphError(
                f"'{child_branch}': parent {parent_id!r} pin {pin} has manifest "
                f"ID {pinned_manifest.id!r}"
            )
        if not self._git.merge_base_is_ancestor(pin, parent_head):
            raise GraphError(
                f"'{child_branch}': parent {parent_id!r} pin {pin} is not "
                f"reachable from the captured tip of {parent_id!r}"
            )

    def _check_id(self, experiment_id: str) -> None:
        if not ID_PATTERN.fullmatch(experiment_id):
            raise InvalidArgumentError(
                f"invalid experiment ID {experiment_id!r}; must match {ID_PATTERN.pattern}"
            )

    # --- scientific mutation operations (spec section 4) --------------------

    def create_experiment(self, spec: NewExperiment, *, base: str) -> Experiment:
        """Create a root experiment with no scientific parents.

        The new branch starts at *base* (a full commit ID or local ref) with a
        single initial commit replacing the root manifest; the Git parent of
        that commit is *base*, but the graph gains no scientific edge.
        """
        self.get_graph()  # the existing graph must be valid before any mutation
        ref = self._target_ref(spec.id)
        self._ensure_ref_available(ref)
        base_commit = self._resolve_base(base)
        self._check_manifest_slot(base_commit)
        manifest = ExperimentManifest(
            id=spec.id, title=spec.title, description=spec.description, parents=[]
        )
        commit = self._commit_manifest(base_commit, manifest, f"scientist: create {spec.id}")
        self._publish_new_refs([(ref, commit)])
        return self.get_experiment(spec.id)

    def extend_experiment(
        self,
        parent_id: str,
        spec: NewExperiment,
        *,
        parent_commit: str | None = None,
    ) -> Experiment:
        """Create one experiment extending *parent_id* (``extends`` edge).

        The child inherits the exact tree pinned by *parent_commit* (default:
        the parent's captured tip), with only the root manifest replaced.
        """
        self.get_graph()
        ref = self._target_ref(spec.id)
        self._ensure_ref_available(ref)
        pin = self._resolve_parent_pin(parent_id, parent_commit)
        manifest = self._child_manifest(
            spec, [ParentRef(id=parent_id, commit=pin, relationship=Relationship.EXTENDS)]
        )
        commit = self._commit_manifest(pin, manifest, f"scientist: extend {parent_id} -> {spec.id}")
        self._publish_new_refs([(ref, commit)])
        return self.get_experiment(spec.id)

    def split_experiment(
        self,
        parent_id: str,
        specs: list[NewExperiment],
        *,
        parent_commit: str | None = None,
    ) -> list[Experiment]:
        """Create two or more experiments split from *parent_id*.

        All children share the same pinned source tree and a ``split_from``
        edge to the parent; the parent branch is untouched. All new refs are
        published in a single transaction: a collision on any child aborts
        the whole split with no refs created.
        """
        self.get_graph()
        if len(specs) < 2:
            raise InvalidArgumentError("split requires at least two child experiments")
        self._ensure_distinct_specs(specs)
        refs = [self._target_ref(spec.id) for spec in specs]
        for ref in refs:
            self._ensure_ref_available(ref)
        pin = self._resolve_parent_pin(parent_id, parent_commit)

        commits: list[str] = []
        for spec in specs:
            manifest = self._child_manifest(
                spec,
                [ParentRef(id=parent_id, commit=pin, relationship=Relationship.SPLIT_FROM)],
            )
            commits.append(
                self._commit_manifest(pin, manifest, f"scientist: split {parent_id} -> {spec.id}")
            )
        self._publish_new_refs(list(zip(refs, commits, strict=True)))
        return [self.get_experiment(spec.id) for spec in specs]

    def merge_experiments(
        self,
        parent_ids: list[str],
        spec: NewExperiment,
        *,
        base_parent_id: str,
    ) -> Experiment:
        """Create one experiment scientifically combining *parent_ids*.

        This is NOT a code merge: the child inherits the tree of
        *base_parent_id*'s captured tip unchanged, records a ``combines`` edge
        to every parent at its captured tip, and the caller integrates code
        afterwards using ordinary Git inside the child worktree.
        """
        self.get_graph()
        if len(parent_ids) < 2:
            raise InvalidArgumentError("merge requires at least two parents")
        if len(set(parent_ids)) != len(parent_ids):
            raise InvalidArgumentError("merge parents must be distinct")
        if base_parent_id not in parent_ids:
            raise InvalidArgumentError("base parent must be one of the merge parents")
        ref = self._target_ref(spec.id)
        self._ensure_ref_available(ref)

        # Capture every parent's tip before creating any objects.
        tips = {pid: self._resolve_parent_pin(pid, None) for pid in parent_ids}
        manifest = self._child_manifest(
            spec,
            [
                ParentRef(id=pid, commit=tips[pid], relationship=Relationship.COMBINES)
                for pid in parent_ids
            ],
        )
        message = f"scientist: merge {', '.join(parent_ids)} -> {spec.id} (base: {base_parent_id})"
        commit = self._commit_manifest(tips[base_parent_id], manifest, message)
        self._publish_new_refs([(ref, commit)])
        return self.get_experiment(spec.id)

    # --- mutation internals ---------------------------------------------------

    def _target_ref(self, experiment_id: str) -> str:
        self._check_id(experiment_id)
        return f"{EXPERIMENT_PREFIX}{experiment_id}"

    def _ensure_distinct_specs(self, specs: list[NewExperiment]) -> None:
        ids = [spec.id for spec in specs]
        if len(set(ids)) != len(ids):
            raise InvalidArgumentError(f"duplicate child experiment ID in {ids}")

    def _ensure_ref_available(self, ref: str) -> None:
        if self._git.ref_oid(ref) is not None:
            branch = ref[len(BRANCH_PREFIX) :]
            raise RefConflictError(f"experiment branch already exists: {branch}")

    def _resolve_base(self, base: str) -> str:
        """Resolve *base* (full commit ID or local ref) once to a commit."""
        if HEX_PATTERN.fullmatch(base):
            if len(base) != self._oid_length:
                raise InvalidArgumentError(
                    f"base {base!r} is not a full {self._object_format} object ID"
                )
            if self._git.cat_file_type(base) != "commit":
                raise InvalidArgumentError(f"base commit not found: {base}")
            return base
        proc = self._git.run(
            "rev-parse", "--verify", "--quiet", "--end-of-options", f"{base}^{{commit}}"
        )
        if proc.returncode != 0:
            raise InvalidArgumentError(
                f"base {base!r} is neither a commit ID nor a resolvable local ref"
            )
        return proc.stdout.decode().strip()

    def _resolve_parent_pin(self, parent_id: str, parent_commit: str | None) -> str:
        """Pin a parent's source revision, fixing it before any object creation."""
        parent = self.get_experiment(parent_id)
        pin = parent_commit if parent_commit is not None else parent.commit
        if not HEX_PATTERN.fullmatch(pin) or len(pin) != self._oid_length:
            raise InvalidArgumentError(
                f"parent_commit {pin!r} is not a full {self._object_format} object ID"
            )
        if self._git.cat_file_type(pin) != "commit":
            raise InvalidArgumentError(f"parent_commit {pin!r} does not exist or is not a commit")
        try:
            manifest = self._load_manifest(pin, parent.branch)
        except ManifestError as exc:
            raise InvalidArgumentError(f"parent_commit {pin!r}: {exc.reason}") from exc
        if manifest.id != parent_id:
            raise InvalidArgumentError(
                f"parent_commit {pin!r} has manifest ID {manifest.id!r}, expected {parent_id!r}"
            )
        if pin != parent.commit and not self._git.merge_base_is_ancestor(pin, parent.commit):
            raise InvalidArgumentError(
                f"parent_commit {pin!r} is not reachable from the current tip of {parent.branch}"
            )
        return pin

    def _check_manifest_slot(self, base_commit: str) -> None:
        """The new manifest must replace a regular file, never a directory."""
        entry = self._git.ls_tree_entry(base_commit, MANIFEST_PATH)
        if entry is None:
            return
        mode, kind, _, _ = entry
        if kind != "blob" or mode == "120000":
            raise InvalidArgumentError(
                f"source tree has a non-regular entry named {MANIFEST_PATH} "
                f"(mode {mode}, type {kind}); refusing to replace it"
            )

    @staticmethod
    def _child_manifest(spec: NewExperiment, parents: list[ParentRef]) -> ExperimentManifest:
        return ExperimentManifest(
            id=spec.id, title=spec.title, description=spec.description, parents=parents
        )

    def _require_identity(self) -> None:
        """Commit creation needs a configured (or environment-provided) identity."""
        missing = [
            name
            for name in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT")
            if self._git.run("var", name).returncode != 0
        ]
        if missing:
            raise GitError(
                "git identity is not configured; set user.name and user.email (or the "
                f"GIT_AUTHOR_*/GIT_COMMITTER_* variables) to create experiments: {missing}"
            )

    def _commit_manifest(self, base_commit: str, manifest: ExperimentManifest, message: str) -> str:
        """Create a commit on top of *base_commit* whose tree is the base tree
        with the root manifest replaced.

        Uses a temporary index (``GIT_INDEX_FILE``); the real index, worktrees
        and HEAD are untouched. The temporary index is removed on every path.
        """
        self._require_identity()
        with tempfile.TemporaryDirectory(prefix="scientist-index-") as tmp:
            index_file = str(Path(tmp) / "index")
            env = {"GIT_INDEX_FILE": index_file}
            self._git.run_checked("read-tree", base_commit, extra_env=env)
            blob = (
                self._git.run_checked(
                    "hash-object", "-w", "--stdin", input_bytes=manifest_to_bytes(manifest)
                )
                .decode()
                .strip()
            )
            # --cacheinfo --add inserts or replaces the manifest entry; a
            # directory occupying the path is rejected by the slot check.
            self._git.run_checked(
                "update-index",
                "--add",
                "--cacheinfo",
                "100644",
                blob,
                MANIFEST_PATH,
                extra_env=env,
            )
            tree = self._git.run_checked("write-tree", extra_env=env).decode().strip()
            return (
                self._git.run_checked("commit-tree", tree, "-p", base_commit, "-m", message)
                .decode()
                .strip()
            )

    def _publish_new_refs(self, refs: list[tuple[str, str]]) -> None:
        """Publish new branch refs in one compare-and-create transaction.

        A competing creation of the same ref fails rather than overwriting
        it; if the transaction fails, no new refs remain.
        """
        script = "".join(
            "start\n"
            + "".join(f"create {ref} {oid}\n" for ref, oid in refs)
            + "prepare\n"
            + "commit\n"
        )
        proc = self._git.run("update-ref", "--stdin", input_bytes=script.encode("ascii"))
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            for ref, _ in refs:
                if self._git.ref_oid(ref) is not None:
                    branch = ref[len(BRANCH_PREFIX) :]
                    raise RefConflictError(
                        f"experiment branch appeared concurrently and was not "
                        f"overwritten: {branch} ({stderr})"
                    )
            raise GitError(f"git update-ref --stdin failed: {stderr}")
