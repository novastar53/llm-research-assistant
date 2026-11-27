import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'

import { api, isAbortError, toApiError } from './api'
import { FilePanel } from './FilePanel'
import { GraphPane } from './GraphPane'
import { Inspector } from './Inspector'
import { initialState, reducer } from './state'

const DEFAULT_SIDE_WIDTH = 420
const MIN_SIDE_WIDTH = 280

type Theme = 'dark' | 'light'

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const [refreshing, setRefreshing] = useState(false)
  const [sideWidth, setSideWidth] = useState(DEFAULT_SIDE_WIDTH)
  const [search, setSearch] = useState('')
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.dataset.theme as Theme) || 'dark',
  )
  const dragging = useRef(false)

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === 'dark' ? 'light' : 'dark'
      document.documentElement.dataset.theme = next
      try {
        localStorage.setItem('theme', next)
      } catch {
        // private browsing etc.: theme just won't persist
      }
      return next
    })
  }, [])

  const startResize = useCallback((event: React.MouseEvent) => {
    event.preventDefault()
    dragging.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    const onMove = (move: MouseEvent) => {
      if (!dragging.current) return
      const width = window.innerWidth - move.clientX
      setSideWidth(
        Math.min(Math.max(width, MIN_SIDE_WIDTH), Math.round(window.innerWidth * 0.75)),
      )
    }
    const onUp = () => {
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [])

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
  const normalizedSearch = search.trim().toLocaleLowerCase()
  const searchMatches = useMemo(() => {
    const matches = new Set<string>()
    if (!state.graph || !normalizedSearch) return matches
    for (const node of state.graph.nodes) {
      const haystack = [node.manifest.id, node.manifest.title, node.manifest.description, node.branch, ...node.manifest.parents.map((parent) => parent.relationship)].join(' ').toLocaleLowerCase()
      if (haystack.includes(normalizedSearch)) matches.add(node.manifest.id)
    }
    return matches
  }, [state.graph, normalizedSearch])

  return (
    <div className="app">
      <header className="app__header">
        <h1>Research Explorer</h1>
        <div className="app__header-actions">
          <label className="search-box">
            <span className="search-box__label">Search experiments</span>
            <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search experiments…" aria-label="Search experiments" />
            {normalizedSearch && <span className="search-box__count" aria-live="polite">{searchMatches.size} match{searchMatches.size === 1 ? '' : 'es'}</span>}
          </label>
          {state.stale && <span className="badge badge--stale">stale (refresh failed)</span>}
          <button onClick={toggleTheme}>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</button>
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
            theme={theme}
            searchMatches={searchMatches}
            hasSearch={Boolean(normalizedSearch)}
            onSelect={(id) => dispatch({ type: 'select', id })}
          />
          {selected && (
            <>
              <div
                className="app__divider"
                role="separator"
                aria-orientation="vertical"
                title="Drag to resize; double-click to reset"
                onMouseDown={startResize}
                onDoubleClick={() => setSideWidth(DEFAULT_SIDE_WIDTH)}
              />
              <div
                className="app__side"
                style={{ '--side-width': `${sideWidth}px` } as React.CSSProperties}
              >
                <Inspector
                  graph={state.graph}
                  node={selected}
                  revision={state.revision}
                  onSelectExperiment={(id) => dispatch({ type: 'select', id })}
                  onSelectParent={(id, commit) => dispatch({ type: 'select_pinned', id, commit })}
                  onReturnToHead={() => dispatch({ type: 'return_to_head' })}
                  onClose={() => dispatch({ type: 'deselect' })}
                />
                <FilePanel experimentId={selected.manifest.id} revision={state.revision} />
              </div>
            </>
          )}
        </main>
      )}
    </div>
  )
}
