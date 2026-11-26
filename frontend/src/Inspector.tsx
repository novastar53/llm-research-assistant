import { useEffect, useState } from 'react'

import { api, isAbortError } from './api'
import type { Revision } from './state'
import type { ApiError, Experiment, ExperimentManifest, Graph } from './types'

function shortCommit(commit: string): string {
  return commit.slice(0, 12)
}

interface InspectorProps {
  graph: Graph
  node: Experiment
  revision: Revision
  onSelectExperiment: (id: string) => void
  onSelectParent: (id: string, pinnedCommit: string) => void
  onReturnToHead: () => void
  onClose: () => void
}

/**
 * Selected-experiment details. At HEAD the manifest comes from the graph;
 * at a pinned revision it is fetched from the pinned experiment.json text
 * endpoint and validated/displayed as the historical manifest.
 */
export function Inspector({
  graph,
  node,
  revision,
  onSelectExperiment,
  onSelectParent,
  onReturnToHead,
  onClose,
}: InspectorProps) {
  const pinnedCommit = revision.kind === 'pinned' ? revision.commit : null
  const [historicalManifest, setHistoricalManifest] = useState<ExperimentManifest | null>(null)
  const [manifestError, setManifestError] = useState<ApiError | null>(null)

  useEffect(() => {
    if (!pinnedCommit) return
    const controller = new AbortController()
    setHistoricalManifest(null)
    setManifestError(null)
    api
      .file(node.manifest.id, 'experiment.json', pinnedCommit, controller.signal)
      .then((text) => setHistoricalManifest(JSON.parse(text.content) as ExperimentManifest))
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setManifestError(
            error instanceof Error
              ? { code: 'invalid_manifest', message: error.message }
              : { code: 'invalid_manifest', message: String(error) },
          )
        }
      })
    return () => controller.abort()
  }, [node.manifest.id, pinnedCommit])

  const manifest = pinnedCommit ? historicalManifest : node.manifest
  const children = graph.edges.filter((edge) => edge.source === node.manifest.id)
  const parents = graph.edges.filter((edge) => edge.target === node.manifest.id)

  return (
    <section className="inspector">
      <header className="inspector__header">
        <button className="inspector__close" title="Close inspector" onClick={onClose}>
          ×
        </button>
        <h2>{manifest?.title ?? node.manifest.title}</h2>
        <div className="inspector__meta">
          <span className="mono">{node.manifest.id}</span>
          {pinnedCommit ? (
            <span className="badge badge--pinned">
              historical revision <span className="mono">{shortCommit(pinnedCommit)}</span>
            </span>
          ) : (
            <span className="badge">HEAD</span>
          )}
        </div>
        <div className="inspector__meta mono">
          {node.branch} @ {shortCommit(pinnedCommit ?? node.commit)}
        </div>
      </header>

      {pinnedCommit && (
        <div className="pin-banner">
          <span>
            Viewing the historical revision pinned by a child. The graph always shows current
            branch heads.
          </span>
          <button onClick={onReturnToHead}>Return to HEAD</button>
        </div>
      )}
      {manifestError && (
        <p className="error">
          Could not load the historical manifest: [{manifestError.code}] {manifestError.message}
        </p>
      )}

      <p className="inspector__description">{manifest?.description || '(no description)'}</p>

      <div className="inspector__relations">
        <div>
          <h3>Parents</h3>
          {parents.length === 0 && <p className="muted">root experiment</p>}
          <ul>
            {parents.map((edge) => (
              <li key={edge.source}>
                <button
                  className="link-button"
                  title={`select ${edge.source} at pinned revision ${edge.source_commit}`}
                  onClick={() => onSelectParent(edge.source, edge.source_commit)}
                >
                  {edge.source}
                </button>
                <span className="muted"> ({edge.relationship})</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Children</h3>
          {children.length === 0 && <p className="muted">none</p>}
          <ul>
            {children.map((edge) => (
              <li key={edge.target}>
                <button className="link-button" onClick={() => onSelectExperiment(edge.target)}>
                  {edge.target}
                </button>
                <span className="muted"> ({edge.relationship})</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}
