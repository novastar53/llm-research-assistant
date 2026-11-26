import type { Graph } from './types'

export interface PositionedNode {
  id: string
  depth: number
  x: number
  y: number
}

export const H_GAP = 250
export const V_GAP = 260

export function layoutGraph(graph: Graph): PositionedNode[] {
  const ids = graph.nodes.map((node) => node.manifest.id).sort()
  const parents = new Map<string, string[]>()
  const children = new Map<string, string[]>()
  for (const edge of graph.edges) {
    const list = parents.get(edge.target) ?? []
    list.push(edge.source)
    parents.set(edge.target, list)
  }
  for (const list of parents.values()) list.sort()
  for (const id of ids) {
    const primaryParent = parents.get(id)?.[0]
    if (primaryParent) {
      const siblings = children.get(primaryParent) ?? []
      siblings.push(id)
      children.set(primaryParent, siblings)
    }
  }

  const depths = new Map<string, number>()
  const depthOf = (id: string): number => {
    const cached = depths.get(id)
    if (cached !== undefined) return cached
    const sources = parents.get(id) ?? []
    const depth = sources.length ? Math.max(...sources.map(depthOf)) + 1 : 0
    depths.set(id, depth)
    return depth
  }

  const xCoordinates = new Map<string, number>()
  let nextLeaf = 0
  const place = (id: string): number => {
    const descendants = children.get(id) ?? []
    const positions = descendants.map(place)
    const x = positions.length ? (positions[0] + positions[positions.length - 1]) / 2 : nextLeaf++ * H_GAP
    xCoordinates.set(id, x)
    return x
  }
  for (const id of ids) if (!parents.has(id)) place(id)

  return ids.map((id) => ({
    id,
    depth: depthOf(id),
    x: xCoordinates.get(id)!,
    y: depthOf(id) * V_GAP,
  }))
}
