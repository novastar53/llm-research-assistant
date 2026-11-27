# LLM Scientist

![CI](https://github.com/novastar53/llm-research-assistant/actions/workflows/ci.yml/badge.svg)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A small, local, single-user tool that turns an ordinary Git repository into a
research experiment graph:

- **Experiments are Git branches** under `experiments/<id>`, each carrying an
  `experiment.json` manifest at the repository root.
- **Revisions are Git commits.** Parent references pin the exact historical
  commit a child was derived from.
- **The repository is the only persistent state.** No database, no registry,
  no artifact store — Git and the repository's own files are the product.
- **The web app is a read-only projection** of the experiment DAG, with
  metadata and committed-text-file inspection.
- **A coding agent (or a human) is the scientist**, using ordinary Git and a
  thin `scientist` CLI for graph-aware operations.

The central rule: *the research repository is the source of truth; the
explorer is a read-only projection, and the coding agent is an external
operator.*

![The Research Explorer showing a real experiment graph: the selected
experiment's manifest, parents and children, committed file list, and an
inline preview of a results figure](docs/images/explorer.png)

*The explorer on a real research repository: experiment graph with pinned
historical lineage, per-experiment file browser, and inline previews of
committed text, markdown and figures.*

See [`llm_scientist_mvp_spec.md`](llm_scientist_mvp_spec.md) for the full
implementation contract and [`docs/decisions.md`](docs/decisions.md) for
deliberate deviations from it.

## Install

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Git, and —
for the browser UI — Node.js 20+ with npm.

```bash
git clone https://github.com/novastar53/llm-research-assistant.git
cd llm-research-assistant
uv sync                       # backend + CLI
cd frontend && npm install && npm run build && cd ..   # browser UI (optional)
```

## Quick start

Point the tool at any existing Git repository (it needs at least one commit;
remote repositories can be cloned beforehand with ordinary Git):

```bash
cd /path/to/research-repo

scientist --repo . create baseline --title "Baseline" --base main
scientist --repo . extend baseline double-q --title "Double Q-learning"
scientist --repo . graph

scientist --repo . serve      # then open http://127.0.0.1:8000
```

In the browser: click a node to inspect its manifest, navigate to parents at
their pinned historical revisions, browse committed files, and read text
previews. Click **Refresh** after creating branches or committing — the
server re-reads Git on every request and never caches.

## The Git convention

- Experiment branches live at `refs/heads/experiments/<id>`; an ID matches
  `^[a-z0-9][a-z0-9-]{0,63}$` and equals the manifest `id` and the branch
  suffix. Only local branches in this namespace are discovered.
- `experiment.json` (repository root, regular file, ≤ 256 KiB, strict UTF-8
  JSON, unknown fields rejected):

```json
{
  "id": "joint-study",
  "title": "Joint noise and learning-rate investigation",
  "description": "Evaluate whether the two factors interact.",
  "parents": [
    {"id": "double-q", "commit": "<full commit object ID>", "relationship": "combines"},
    {"id": "gaussian", "commit": "<full commit object ID>", "relationship": "combines"}
  ]
}
```

- `relationship` is a closed vocabulary: `extends`, `split_from`, `combines`,
  `replicates`, `validates` (a deliberate deviation from the spec's open
  vocabulary — see `docs/decisions.md`).
- Scientific lineage comes **only** from manifests; a pinned parent commit
  must exist, carry a manifest identifying the parent, and be reachable from
  the parent's current tip. Git ancestry between parent and child is *not*
  required — independent validation is legitimate.
- Experiment branches normally advance by commits and fast-forwards. Do not
  force-push or rewrite history. Renaming, reparenting, or deleting an
  experiment is exceptional researcher-authorized maintenance: update every
  affected manifest and pinned child reference atomically, then validate the
  complete graph with `scientist graph`.
- The tool itself permits ordinary repository layouts for code, notebooks,
  results, and notes. When a coding agent works under this repository's
  [`AGENTS.md`](AGENTS.md), that file defines the required agent workflow,
  including its one-script-per-experiment and no-inherited-results
  conventions.

## CLI

```
scientist --repo PATH graph                                # print the graph as JSON
scientist --repo PATH create ID --title T --base REF       # root experiment
scientist --repo PATH extend PARENT ID --title T [--parent-commit OID]
scientist --repo PATH split PARENT --specs children.json [--parent-commit OID]
scientist --repo PATH merge P1 P2 ... --id ID --title T --base-parent P1
scientist --repo PATH serve [--host 127.0.0.1] [--port 8000]
```

- `--base` accepts a full commit ID or a local ref, resolved once.
- `split` takes a JSON array of `{"id", "title", "description"}` objects and
  publishes all children in a single transaction (a collision aborts the
  whole split).
- `merge` creates a **scientific** combination only: the child inherits the
  `--base-parent` tree unchanged and records `combines` edges to every parent
  at its captured tip. It does **not** merge code — do that afterwards with
  ordinary Git inside the child's worktree, keeping the child's manifest.
- The CLI's `create` / `extend` / `split` / `merge` mutations never change an
  existing experiment: they create new branches with a fresh initial commit
  (whose Git parent is the chosen base). Researcher-authorized structural
  maintenance, such as a rename, uses ordinary Git as described above.

## HTTP API (read-only)

| Endpoint | Response |
| --- | --- |
| `GET /api/graph` | full `ExperimentGraph` (nodes, manifests, edges) |
| `GET /api/experiments/{id}` | one experiment at its current head |
| `GET /api/experiments/{id}/files?commit=...` | `{commit, files}` at the pinned revision |
| `GET /api/experiments/{id}/file?path=...&commit=...` | exact text content (`TextFile`) |
| `GET /api/experiments/{id}/file/raw?path=...&commit=...` | inline raster image bytes (PNG/JPEG/GIF/WebP only; SVG never served) |

Errors share one envelope: `{"error": {"code", "message"}}` with statuses
404 / 400 / 409 / 413 / 415 / 503 / 500. All responses are `Cache-Control:
no-store`. There are no mutation endpoints; the repository path is fixed at
server startup and the server binds to loopback by default.

File inspection reads committed blobs only: previews are strict UTF-8 text up
to 256 KiB (never truncated), listings cap at 10,000 entries, symlinks and
submodules are listed but never followed, and uncommitted work is invisible.

## Development

```bash
uv run pytest -q               # backend tests (real temporary Git repos)
uv run ruff check .            # lint
uv run ruff format --check .   # format

cd frontend
npm run dev                    # vite dev server (proxies /api to :8000)
npm test                       # vitest: layout + selection/revision state
npm run typecheck              # tsc
npm run build                  # emits frontend/dist, served by FastAPI
```

### Manual browser smoke test

1. Create a demo repository, run `scientist create baseline`, two `extend`s
   from `baseline`, and a `merge` of the two children — a diamond.
2. `scientist serve`, open `http://127.0.0.1:8000`.
3. Expected (verified against a built checkout during development): the
   diamond renders as four selectable nodes with four directed labeled
   edges; selecting `joint-study` shows two `combines` parents; clicking a
   parent opens it at the pinned commit with an orange "historical
   revision" banner; **Return to HEAD** restores the current view; the file
   list matches `git ls-tree -r` of that commit; text files preview
   verbatim; clicking **Refresh** after `scientist extend ... newcomer`
   shows the new node without a server restart; a repository with no
   experiments shows the empty state; a malformed `experiments/*` branch
   shows the invalid-graph error with the branch name and reason.

## Working with a coding agent

[`AGENTS.md`](AGENTS.md) is the authoritative workflow for agents working
with experiment repositories from this checkout. It requires graph-first
inspection, CLI-created nodes, independent worktrees, clean experiment trees,
explicit scientific merges, and graph validation before reporting.
[`docs/AGENTS.example.md`](docs/AGENTS.example.md) remains a generic template
for researchers who want to adapt similar guidance to a separate repository.

## Limitations

- Local, single-user, one repository per server process; loopback by
  default. Not a hardened multi-tenant service.
- The split/merge ref transaction protects cooperating local writers, not
  arbitrary concurrent destructive Git operations, and it is not a
  distributed transaction. Complete local histories are assumed.
- The explorer previews committed text only. Plots, binaries, LFS/DVC
  content and uncommitted results stay in your IDE/agent workflow.
- The library reports invalid repository state; it never repairs or mutates
  your research data to "fix" it.
