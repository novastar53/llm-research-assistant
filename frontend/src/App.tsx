import { useCallback, useEffect, useReducer, useState } from 'react'

import { api, isAbortError, toApiError } from './api'
import { FilePanel } from './FilePanel'
import { GraphPane } from './GraphPane'
import { Inspector } from './Inspector'
import { initialState, reducer } from './state'

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const [refreshing, setRefreshing] = useState(false)

  const loadGraph = useCallback(async (signal?: AbortSignal) => {
    try {
      dispatch({ type: 'graph_loaded', graph: await api.graph(signal) })
    } catch (error: unknown) {
      if (!isAbortError(error)) dispatch({ type: 'graph_failed', error: toApiError(error) })
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void loadGraph(controller.signal)
    return () => controller.abort()
  }, [loadGraph])

  const onRefresh = useCallback(() => {
    setRefreshing(true)
    const controller = new AbortController()
    void loadGraph(controller.signal).finally(() => setRefreshing(false))
    return () => controller.abort()
  }, [loadGraph])

  const selected = state.graph?.nodes.find((node) => node.manifest.id === state.selectedId)

  return (
    <div className="app">
      <header className="app__header">
        <h1>Research Explorer</h1>
        <div className="app__header-actions">
          {state.stale && <span className="badge badge--stale">stale (refresh failed)</span>}
          <button onClick={onRefresh} disabled={refreshing}>
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>

      {state.error && !state.stale && (
        <div className="app__error" role="alert">
          <h2>{state.error.code === 'invalid_graph' ? 'Invalid experiment graph' : 'Error'}</h2>
          <p>
            [{state.error.code}] {state.error.message}
          </p>
          {state.error.code === 'invalid_graph' && (
            <p className="muted">
              Repair the repository with ordinary Git (fix or delete the offending
              experiments/* branch), then refresh.
            </p>
          )}
        </div>
      )}

      {state.graph && state.graph.nodes.length === 0 && !state.error && (
        <div className="app__empty">
          <h2>No experiments yet</h2>
          <p>
            This repository has no <span className="mono">experiments/*</span> branches. Create
            one with the CLI, e.g.{' '}
            <span className="mono">scientist --repo . create baseline --title Baseline --base main</span>
            , then refresh.
          </p>
        </div>
      )}

      {state.graph && state.graph.nodes.length > 0 && (
        <main className="app__main">
          <GraphPane
            graph={state.graph}
            selectedId={state.selectedId}
            onSelect={(id) => dispatch({ type: 'select', id })}
          />
          <div className="app__side">
            {selected ? (
              <>
                <Inspector
                  graph={state.graph}
                  node={selected}
                  revision={state.revision}
                  onSelectExperiment={(id) => dispatch({ type: 'select', id })}
                  onSelectParent={(id, commit) => dispatch({ type: 'select_pinned', id, commit })}
                  onReturnToHead={() => dispatch({ type: 'return_to_head' })}
                />
                <FilePanel experimentId={selected.manifest.id} revision={state.revision} />
              </>
            ) : (
              <p className="muted app__hint">Select an experiment node to inspect it.</p>
            )}
          </div>
        </main>
      )}
    </div>
  )
}
