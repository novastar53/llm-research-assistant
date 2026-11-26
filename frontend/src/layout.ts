import type { Graph } from './types'

export interface PositionedNode {
  id: string
  depth: number
  x: number
  y: number
}

export const H_GAP = 200
export const V_GAP = 165
// Node cards render at 180x144 (5:4); the gaps above leave ~20px of clear
// space between cards so layers never overlap.

/**
 * Deterministic topological-layer layout (spec section 6): roots at the top,
 * each child one layer below its deepest parent.
 *
 * Within a layer, nodes are ordered by barycenter — the mean column of their
 * already-placed parents — with ID as tie-break (see docs/decisions.md; the
 * spec suggested plain ID ordering, which makes dense layers unreadable
 * because edges from scattered parents cross everywhere). A single top-down
 * pass suffices because every parent's depth is strictly smaller than its
 * child's. Pure and stable for a given graph.
 */
export function layoutGraph(graph: Graph): PositionedNode[] {
  const ids = graph.nodes.map((node) => node.manifest.id).sort()
  const parentsOf = new Map<string, string[]>()
  for (const edge of graph.edges) {
    const list = parentsOf.get(edge.target) ?? []
    list.push(edge.source)
    parentsOf.set(edge.target, list)
  }

  const depthCache = new Map<string, number>()
  const depthOf = (id: string): number => {
    const cached = depthCache.get(id)
    if (cached !== undefined) return cached
    const parents = (parentsOf.get(id) ?? []).sort()
    const depth = parents.length === 0 ? 0 : Math.max(...parents.map(depthOf)) + 1
    depthCache.set(id, depth)
    return depth
  }

  const layers = new Map<number, string[]>()
  for (const id of ids) {
    const layer = layers.get(depthOf(id)) ?? []
    layer.push(id)
    layers.set(depthOf(id), layer)
  }

  const columnOf = new Map<string, number>()
  const positioned: PositionedNode[] = []
  for (const [depth, layer] of [...layers.entries()].sort((a, b) => a[0] - b[0])) {
    if (depth > 0) {
      const barycenter = (id: string): number => {
        const parents = parentsOf.get(id) ?? []
        const placed = parents.filter((parent) => columnOf.has(parent))
        if (placed.length === 0) return Number.POSITIVE_INFINITY
        return placed.reduce((sum, parent) => sum + columnOf.get(parent)!, 0) / placed.length
      }
      layer.sort((a, b) => {
        const byBarycenter = barycenter(a) - barycenter(b)
        if (byBarycenter !== 0) return byBarycenter
        return a < b ? -1 : a > b ? 1 : 0
      })
    }
    layer.forEach((id, column) => {
      columnOf.set(id, column)
      positioned.push({ id, depth, x: column * H_GAP, y: depth * V_GAP })
    })
  }
  return positioned
}
