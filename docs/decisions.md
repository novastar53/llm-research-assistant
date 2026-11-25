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
