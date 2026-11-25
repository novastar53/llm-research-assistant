import type { Graph } from './types'

export interface PositionedNode {
  id: string
  depth: number
  x: number
  y: number
}

export const H_GAP = 220
export const V_GAP = 110

/**
 * Deterministic topological-layer layout (spec section 6): roots at the top,
 * each child one layer below its deepest parent, experiments ordered by ID
 * within a layer. Pure and stable for a given graph.
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

  const byDepth = new Map<number, string[]>()
  for (const id of ids) {
    const depth = depthOf(id)
    const layer = byDepth.get(depth) ?? []
    layer.push(id)
    byDepth.set(depth, layer)
  }

  const positioned: PositionedNode[] = []
  for (const [depth, layer] of [...byDepth.entries()].sort((a, b) => a[0] - b[0])) {
    layer.forEach((id, column) => {
      positioned.push({ id, depth, x: column * H_GAP, y: depth * V_GAP })
    })
  }
  return positioned
}
