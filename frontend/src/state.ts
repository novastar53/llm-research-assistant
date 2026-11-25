import type { ApiError, Graph } from './types'

/** Which revision of the selected experiment is being viewed. */
export type Revision = { kind: 'head' } | { kind: 'pinned'; commit: string }

export interface ExplorerState {
  graph: Graph | null
  /** Error from the most recent graph load. */
  error: ApiError | null
  /** True when `graph` is retained from before a failed refresh. */
  stale: boolean
  selectedId: string | null
  revision: Revision
}

export const initialState: ExplorerState = {
  graph: null,
  error: null,
  stale: false,
  selectedId: null,
  revision: { kind: 'head' },
}

export type Action =
  | { type: 'graph_loaded'; graph: Graph }
  | { type: 'graph_failed'; error: ApiError }
  | { type: 'select'; id: string }
  | { type: 'select_pinned'; id: string; commit: string }
  | { type: 'return_to_head' }

/**
 * Selection/revision state machine (spec section 6, "Required behavior").
 *
 * - Selecting always clears the file selection implicitly (components key
 *   their file state on selectedId+revision) and resets to HEAD unless a pin
 *   is given.
 * - A new graph follows HEAD automatically for HEAD viewers (the UI always
 *   renders the selected node from the current graph object), while pinned
 *   revisions are kept as-is.
 * - A failed refresh keeps the old graph and marks it stale, so old content
 *   is never shown as if it were fresh.
 */
export function reducer(state: ExplorerState, action: Action): ExplorerState {
  switch (action.type) {
    case 'select':
      return { ...state, selectedId: action.id, revision: { kind: 'head' } }
    case 'select_pinned':
      return {
        ...state,
        selectedId: action.id,
        revision: { kind: 'pinned', commit: action.commit },
      }
    case 'return_to_head':
      return { ...state, revision: { kind: 'head' } }
    case 'graph_loaded': {
      const stillThere = action.graph.nodes.some(
        (node) => node.manifest.id === state.selectedId,
      )
      return {
        graph: action.graph,
        error: null,
        stale: false,
        selectedId: stillThere ? state.selectedId : null,
        revision: stillThere ? state.revision : { kind: 'head' },
      }
    }
    case 'graph_failed':
      return { ...state, error: action.error, stale: state.graph !== null }
  }
}
