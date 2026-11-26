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
 * Within a layer, nodes are ordered by barycenter — the mean x of their
 * already-placed parents — with ID as tie-break (see docs/decisions.md).
 * Coordinates then place each child at that barycenter, resolved left-to-right
 * with a minimum H_GAP separation, so a child renders beneath its parent
 * rather than in an unrelated ordinal column (which read as a false parent).
 * Pure and stable for a given graph.
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

  const xOf = new Map<string, number>()
  const positioned: PositionedNode[] = []
  for (const [depth, layer] of [...layers.entries()].sort((a, b) => a[0] - b[0])) {
    // desired x: roots spread evenly by ID; children aim for their parents'
    // mean x (Infinity when no parent is placed yet, i.e. never for depth>0)
    const desiredX = (id: string): number => {
      const parents = parentsOf.get(id) ?? []
      const placed = parents.filter((parent) => xOf.has(parent))
      if (placed.length === 0) return Number.POSITIVE_INFINITY
      return placed.reduce((sum, parent) => sum + xOf.get(parent)!, 0) / placed.length
    }
    if (depth === 0) {
      layer.forEach((id, column) => xOf.set(id, column * H_GAP))
    } else {
      layer.sort((a, b) => {
        const byDesired = desiredX(a) - desiredX(b)
        if (byDesired !== 0 && !Number.isNaN(byDesired)) return byDesired
        return a < b ? -1 : a > b ? 1 : 0
      })
      let previous = -H_GAP
      for (const id of layer) {
        const desired = desiredX(id)
        const x = Number.isFinite(desired) ? Math.max(desired, previous + H_GAP) : previous + H_GAP
        xOf.set(id, x)
        previous = x
      }
    }
    for (const id of layer) {
      positioned.push({ id, depth, x: xOf.get(id)!, y: depth * V_GAP })
    }
  }
  return positioned
}
