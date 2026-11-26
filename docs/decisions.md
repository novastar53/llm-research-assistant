# Design decisions

Records deliberate deviations from, or interpretations of,
`llm_scientist_mvp_spec.md`. Each entry states the contract, the decision,
and why.

## 2026-11-24 — `parents[].relationship` is a closed, required enum

**Spec contract:** open vocabulary, optional field defaulting to
`derived_from`, max 100 characters; suggested values `extends`,
`split_from`, `combines`, `replicates`, `validates`.

**Decision:** `Relationship` is a closed `StrEnum` with exactly the five
suggested values, and the field is **required** in manifests (no default).

**Why:** Open vocabulary invites case/whitespace/synonym drift
(`Extends`, `based_on`, `derived_from`), which makes the value useless for
display and querying. The mutation operations write three of the values
mechanically; the other two (`replicates`, `validates`) cover the
meaningful agent-authored cases. Anything more nuanced belongs in the
free-text `description`. The spec's own default (`derived_from`) is not in
its suggested set, so no sensible default exists — requiring the field is
explicit and unambiguous. Relationship is display-only metadata; nothing in
graph construction depends on it, so this cannot corrupt lineage.

**Cost:** manifests authored outside this tool must use the exact five
values, lowercase.

## 2026-11-24 — Markdown files render as sanitized HTML in the preview panel

**Spec contract:** "No HTML rendering"; "Render repository-controlled
strings as text, not raw HTML. No `dangerouslySetInnerHTML` for file
previews."

**Decision:** committed `.md`/`.markdown` files render as formatted HTML
in the text preview (other files remain verbatim plain text). This
requires `dangerouslySetInnerHTML`, applied only to output that has passed
through two layers of defense in `frontend/src/markdown.ts`:

1. `markdown-it` parses with `html: false`, so raw HTML in the repository
   file is escaped, never passed through.
2. `DOMPurify` sanitizes the rendered HTML; `img`/`style` are forbidden
   entirely (no external resource loading, preserving the spec's ban on
   external URLs), and only safe link protocols survive.
3. External links open in a new tab with `rel="noopener noreferrer"`.

**Why:** the researcher asked for readable markdown rendering in the
viewer. Sanitized rendering is the standard safe way to show untrusted
markdown; plain-text display of every note made results files hard to
read.

**Cost:** a sanitizer bypass in DOMPurify would become an XSS vector in a
trusted local tool; keep the dependency current. The backend's text
endpoint still returns exact bytes — rendering is a client-side view.

## 2026-11-24 — Within-layer order is barycenter, not plain ID

**Spec contract:** "A basic deterministic topological-layer layout is
sufficient: roots at the top, children below the deepest parent, order
within a layer by ID."

**Decision:** within a layer, nodes are ordered by barycenter — the mean
column of their already-placed parents — with ID as tie-break, one
top-down pass. Roots and disconnected nodes still order by ID. Edges
additionally route as orthogonal `smoothstep` paths rather than beziers.

**Why:** with plain ID ordering, dense layers (six-plus nodes) produced
indistinguishable, crossing-heavy bezier bundles — user-reported
unreadability. Barycenter placement makes most edges short and near
vertical; smoothstep routing gives each remaining edge a distinct
vertical/horizontal path.

**Cost:** layout output for a given graph is still deterministic but
differs from the spec's example ordering; no persisted state depends on
it (layouts are never stored).
