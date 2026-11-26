import { describe, expect, it } from 'vitest'

import { H_GAP, V_GAP, layoutGraph } from './layout'
import type { Graph } from './types'

function makeGraph(edges: Array<[string, string]>, extraNodes: string[] = []): Graph {
  const ids = new Set<string>(extraNodes)
  for (const [source, target] of edges) {
    ids.add(source)
    ids.add(target)
  }
  return {
    nodes: [...ids].sort().map((id) => ({
      branch: `experiments/${id}`,
      commit: 'a'.repeat(40),
      manifest: { id, title: `Title ${id}`, description: '', parents: [] },
    })),
    edges: edges.map(([source, target]) => ({
      source,
      target,
      source_commit: 'a'.repeat(40),
      relationship: 'extends',
    })),
  }
}

function positions(graph: Graph): Map<string, { x: number; y: number; depth: number }> {
  return new Map(layoutGraph(graph).map((p) => [p.id, p]))
}

describe('layoutGraph', () => {
  it('places the diamond in three layers with children below parents', () => {
    const pos = positions(
      makeGraph([
        ['baseline', 'double-q'],
        ['baseline', 'gaussian'],
        ['double-q', 'joint-study'],
        ['gaussian', 'joint-study'],
      ]),
    )
    expect(pos.get('baseline')).toMatchObject({ depth: 0, y: 0 })
    expect(pos.get('double-q')).toMatchObject({ depth: 1, y: V_GAP })
    expect(pos.get('gaussian')).toMatchObject({ depth: 1, y: V_GAP })
    expect(pos.get('joint-study')).toMatchObject({ depth: 2, y: 2 * V_GAP })
  })

  it('orders experiments by ID within a layer', () => {
    const pos = positions(
      makeGraph([
        ['root', 'zeta'],
        ['root', 'alpha'],
      ]),
    )
    expect(pos.get('alpha')!.x).toBeLessThan(pos.get('zeta')!.x)
    expect(pos.get('alpha')!.x % H_GAP).toBe(0)
  })

  it('keeps a child below its deepest parent', () => {
    // chain root -> mid -> leaf, plus root -> other: leaf sits at depth 2
    const pos = positions(
      makeGraph([
        ['root', 'mid'],
        ['mid', 'leaf'],
        ['root', 'other'],
      ]),
    )
    expect(pos.get('leaf')!.y).toBe(2 * V_GAP)
    expect(pos.get('other')!.y).toBe(V_GAP)
  })

  it('orders children under their parents (barycenter), not alphabetically', () => {
    // two side-by-side roots; 'a-child' would sort first alphabetically but
    // belongs to the right-hand parent and must stay under it
    const pos = positions(makeGraph([['left', 'z-child'], ['right', 'a-child']]))
    expect(pos.get('left')!.x).toBeLessThan(pos.get('right')!.x)
    expect(pos.get('z-child')!.x).toBe(pos.get('left')!.x)
    expect(pos.get('a-child')!.x).toBe(pos.get('right')!.x)
  })

  it('keeps a child of two parents below both parents', () => {
    // alphabetical order would put 'both' first; its barycenter (mean of p1,
    // p2 = 0.5) must place it after 'left-only' (barycenter 0)
    const pos = positions(
      makeGraph([
        ['p1', 'both'],
        ['p1', 'left-only'],
        ['p2', 'both'],
      ]),
    )
    expect(pos.get('both')!.y).toBeGreaterThan(pos.get('p1')!.y)
    expect(pos.get('both')!.y).toBeGreaterThan(pos.get('p2')!.y)
  })

  it('keeps sibling subtrees separate instead of placing a child under an unrelated parent', () => {
    const pos = positions(makeGraph([
      ['root', 'variance'], ['root', 'ucb'],
      ['variance', 'diagnostics'], ['variance', 'joint'],
      ['ucb', 'deployment'],
    ]))
    expect(pos.get('joint')!.x).toBeGreaterThan(pos.get('ucb')!.x)
    expect(pos.get('deployment')!.x).toBeLessThan(pos.get('joint')!.x)
  })

  it('places a child under its parent even when another root is leftmost', () => {
    // regression: ordinal columns put the child at x=0, directly beneath the
    // unrelated leftmost root, which read as a false parent
    const pos = positions(makeGraph([['p-b', 'child']], ['p-a']))
    expect(pos.get('p-a')!.x).toBe(0)
    expect(pos.get('child')!.x).toBe(pos.get('p-b')!.x)
    expect(pos.get('child')!.x).not.toBe(0)
  })

  it('treats disconnected nodes as roots', () => {
    const pos = positions(makeGraph([], ['solo1', 'solo2']))
    expect(pos.get('solo1')).toMatchObject({ depth: 0, y: 0 })
    expect(pos.get('solo2')).toMatchObject({ depth: 0, y: 0 })
  })

  it('is deterministic for a fixed graph', () => {
    const graph = makeGraph([
      ['baseline', 'double-q'],
      ['baseline', 'gaussian'],
      ['double-q', 'joint-study'],
    ])
    expect(layoutGraph(graph)).toEqual(layoutGraph(graph))
  })

  it('emits every node exactly once', () => {
    const graph = makeGraph([
      ['a', 'b'],
      ['a', 'c'],
      ['b', 'd'],
      ['c', 'd'],
    ])
    const laidOut = layoutGraph(graph)
    expect(laidOut.map((p) => p.id).sort()).toEqual(['a', 'b', 'c', 'd'])
  })
})
