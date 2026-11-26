import { describe, expect, it } from 'vitest'

import { initialState, reducer } from './state'
import type { Graph } from './types'

const graph: Graph = {
  nodes: [
    {
      branch: 'experiments/baseline',
      commit: 'a'.repeat(40),
      manifest: { id: 'baseline', title: 'Baseline', description: '', parents: [] },
    },
    {
      branch: 'experiments/double-q',
      commit: 'b'.repeat(40),
      manifest: {
        id: 'double-q',
        title: 'Double Q',
        description: '',
        parents: [
          { id: 'baseline', commit: 'a'.repeat(40), relationship: 'extends' },
        ],
      },
    },
  ],
  edges: [
    {
      source: 'baseline',
      target: 'double-q',
      source_commit: 'a'.repeat(40),
      relationship: 'extends',
    },
  ],
}

describe('selection and revision state', () => {
  it('selecting an experiment resets to HEAD', () => {
    const pinned = reducer(initialState, {
      type: 'select_pinned',
      id: 'baseline',
      commit: 'a'.repeat(40),
    })
    const state = reducer(pinned, { type: 'select', id: 'double-q' })
    expect(state.selectedId).toBe('double-q')
    expect(state.revision).toEqual({ kind: 'head' })
  })

  it('selecting a parent at its pinned commit marks the revision pinned', () => {
    const state = reducer(initialState, {
      type: 'select_pinned',
      id: 'baseline',
      commit: 'a'.repeat(40),
    })
    expect(state.selectedId).toBe('baseline')
    expect(state.revision).toEqual({ kind: 'pinned', commit: 'a'.repeat(40) })
  })

  it('return_to_head clears the pin but keeps the selection', () => {
    const pinned = reducer(initialState, {
      type: 'select_pinned',
      id: 'baseline',
      commit: 'a'.repeat(40),
    })
    const state = reducer(pinned, { type: 'return_to_head' })
    expect(state.selectedId).toBe('baseline')
    expect(state.revision).toEqual({ kind: 'head' })
  })

  it('a loaded graph clears errors and follows HEAD, keeping explicit pins', () => {
    const failed = reducer({ ...initialState, graph }, {
      type: 'graph_failed',
      error: { code: 'git_timeout', message: 'slow' },
    })
    expect(failed.stale).toBe(true)

    const pinned = reducer(failed, {
      type: 'select_pinned',
      id: 'baseline',
      commit: 'a'.repeat(40),
    })
    const loaded = reducer(pinned, { type: 'graph_loaded', graph })
    expect(loaded.error).toBeNull()
    expect(loaded.stale).toBe(false)
    // explicit historical pin survives a refresh:
    expect(loaded.revision).toEqual({ kind: 'pinned', commit: 'a'.repeat(40) })
  })

  it('drops the selection when the experiment disappears from the graph', () => {
    const selected = reducer({ ...initialState, graph }, { type: 'select', id: 'baseline' })
    const loaded = reducer(selected, { type: 'graph_loaded', graph: { nodes: [], edges: [] } })
    expect(loaded.selectedId).toBeNull()
    expect(loaded.revision).toEqual({ kind: 'head' })
  })

  it('deselect clears the selection and any pin', () => {
    const pinned = reducer(initialState, {
      type: 'select_pinned',
      id: 'baseline',
      commit: 'a'.repeat(40),
    })
    const state = reducer(pinned, { type: 'deselect' })
    expect(state.selectedId).toBeNull()
    expect(state.revision).toEqual({ kind: 'head' })
  })

  it('a failed load with no prior graph is an error state, not stale', () => {
    const state = reducer(initialState, {
      type: 'graph_failed',
      error: { code: 'invalid_graph', message: 'cycle' },
    })
    expect(state.graph).toBeNull()
    expect(state.stale).toBe(false)
    expect(state.error?.code).toBe('invalid_graph')
  })

  it('a failed refresh keeps the old graph and marks it stale', () => {
    const loaded = reducer(initialState, { type: 'graph_loaded', graph })
    const state = reducer(loaded, {
      type: 'graph_failed',
      error: { code: 'git_timeout', message: 'slow' },
    })
    expect(state.graph).toBe(graph)
    expect(state.stale).toBe(true)
  })
})
