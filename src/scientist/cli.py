"""Agent-facing CLI (spec section 4.2).

JSON on stdout for machine-readable operations; errors on stderr with a
nonzero exit status. This is a thin wrapper over ``ResearchRepository`` —
it is not a generic Git command proxy and has no interactive shell.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from .errors import InvalidArgumentError, ScientistError
from .models import NewExperiment
from .repository import ResearchRepository

MERGE_EPILOG = """\
This creates a new experiment that scientifically combines the parents:
the child records a "combines" edge to each parent at its captured tip and
inherits the tree of --base-parent unchanged. It does NOT merge code trees;
perform any ordinary Git merge (or port code selectively) inside the child
worktree afterwards, keeping the child's experiment.json manifest.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scientist",
        description="Git-native research experiment graph tool (read + graph mutations)",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="path to the research repository (default: current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("graph", help="print the experiment graph as JSON")

    p_create = sub.add_parser("create", help="create a root experiment (no scientific parents)")
    p_create.add_argument("id", help="experiment ID (becomes branch experiments/<id>)")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--description", default="")
    p_create.add_argument(
        "--base",
        required=True,
        help="base commit ID or full local ref (e.g. refs/heads/main); resolved once",
    )

    p_extend = sub.add_parser("extend", help="create one experiment extending a parent")
    p_extend.add_argument("parent", help="parent experiment ID")
    p_extend.add_argument("id", help="new experiment ID")
    p_extend.add_argument("--title", required=True)
    p_extend.add_argument("--description", default="")
    p_extend.add_argument(
        "--parent-commit",
        default=None,
        help="pin a historical parent revision (default: the parent's current tip)",
    )

    p_split = sub.add_parser("split", help="create two or more experiments from one parent")
    p_split.add_argument("parent", help="parent experiment ID")
    p_split.add_argument(
        "--specs",
        required=True,
        help="path to a JSON array of NewExperiment objects "
        '([{"id": ..., "title": ..., "description": ...}, ...])',
    )
    p_split.add_argument("--parent-commit", default=None, help="historical parent pin")

    p_merge = sub.add_parser(
        "merge",
        help="create one experiment scientifically combining two or more parents",
        epilog=MERGE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_merge.add_argument("parents", nargs="+", metavar="PARENT", help="parent experiment IDs")
    p_merge.add_argument("--id", required=True, help="new experiment ID")
    p_merge.add_argument("--title", required=True)
    p_merge.add_argument("--description", default="")
    p_merge.add_argument(
        "--base-parent",
        required=True,
        help="the parent whose tree the child inherits; must be one of the parents",
    )

    p_serve = sub.add_parser(
        "serve",
        help="run the read-only web explorer (serves the built frontend when present)",
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback)")
    p_serve.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    return parser


def _load_specs(path: str) -> list[NewExperiment]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidArgumentError(f"cannot read specs file {path!r}: {exc}") from exc
    if not isinstance(raw, list):
        raise InvalidArgumentError(f"specs file {path!r} must contain a JSON array")
    try:
        return [NewExperiment.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise InvalidArgumentError(f"specs file {path!r} failed validation: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = ResearchRepository(args.repo)
        if args.command == "graph":
            print(repo.get_graph().model_dump_json(indent=2))
        elif args.command == "create":
            experiment = repo.create_experiment(
                NewExperiment(id=args.id, title=args.title, description=args.description),
                base=args.base,
            )
            print(experiment.model_dump_json(indent=2))
        elif args.command == "extend":
            experiment = repo.extend_experiment(
                args.parent,
                NewExperiment(id=args.id, title=args.title, description=args.description),
                parent_commit=args.parent_commit,
            )
            print(experiment.model_dump_json(indent=2))
        elif args.command == "split":
            experiments = repo.split_experiment(
                args.parent, _load_specs(args.specs), parent_commit=args.parent_commit
            )
            print(json.dumps([e.model_dump(mode="json") for e in experiments], indent=2))
        elif args.command == "merge":
            experiment = repo.merge_experiments(
                args.parents,
                NewExperiment(id=args.id, title=args.title, description=args.description),
                base_parent_id=args.base_parent,
            )
            print(experiment.model_dump_json(indent=2))
        elif args.command == "serve":
            import uvicorn

            from .api import create_app

            app = create_app(args.repo)  # raises early on an invalid repository
            uvicorn.run(app, host=args.host, port=args.port)
        else:  # pragma: no cover - argparse enforces the command set
            raise ScientistError(f"unknown command: {args.command}")
    except ScientistError as exc:
        print(f"error [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
