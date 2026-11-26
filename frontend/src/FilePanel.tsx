import { useEffect, useRef, useState } from 'react'

import { api, isAbortError, toApiError } from './api'
import { isMarkdownPath, renderMarkdown } from './markdown'
import type { Revision } from './state'
import type { ApiError, FileEntry, FileListing, TextFile } from './types'

interface FilePanelProps {
  experimentId: string
  revision: Revision
}

/**
 * Committed file list + whitespace-preserving text preview for the selected
 * experiment at the selected revision. All asynchronous responses from
 * previous selections are ignored (AbortController), and the file selection
 * resets whenever the node or revision changes, so stale content can never
 * be shown under a new revision.
 */
export function FilePanel({ experimentId, revision }: FilePanelProps) {
  const commit = revision.kind === 'pinned' ? revision.commit : null
  const [listing, setListing] = useState<FileListing | null>(null)
  const [listingError, setListingError] = useState<ApiError | null>(null)
  const [preview, setPreview] = useState<TextFile | null>(null)
  const [previewError, setPreviewError] = useState<ApiError | null>(null)
  const previewAbort = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setListing(null)
    setListingError(null)
    setPreview(null)
    setPreviewError(null)
    api
      .files(experimentId, commit, controller.signal)
      .then(setListing)
      .catch((error: unknown) => {
        if (!isAbortError(error)) setListingError(toApiError(error))
      })
    return () => controller.abort()
  }, [experimentId, commit])

  // A preview request that is still in flight when the panel unmounts (or a
  // new preview starts) is aborted so a stale response can never land.
  useEffect(() => () => previewAbort.current?.abort(), [])

  const openFile = (entry: FileEntry) => {
    if (entry.kind !== 'file') {
      setPreview(null)
      setPreviewError({
        code: 'unsupported_content',
        message: `${entry.path} is a ${entry.kind}; only regular files can be previewed`,
      })
      return
    }
    previewAbort.current?.abort()
    const controller = new AbortController()
    previewAbort.current = controller
    setPreview(null)
    setPreviewError(null)
    api
      .file(experimentId, entry.path, commit, controller.signal)
      .then(setPreview)
      .catch((error: unknown) => {
        if (!isAbortError(error)) setPreviewError(toApiError(error))
      })
  }

  return (
    <section className="file-panel">
      <h3>Files</h3>
      {listingError && (
        <p className="error">
          [{listingError.code}] {listingError.message}
        </p>
      )}
      {listing && (
        <p className="muted mono">
          {listing.files.length} files @ {listing.commit.slice(0, 12)}
        </p>
      )}
      <ul className="file-list">
        {listing?.files.map((entry) => (
          <li key={entry.path}>
            <button
              className={`link-button${preview?.path === entry.path ? ' link-button--active' : ''}`}
              onClick={() => openFile(entry)}
            >
              {entry.path}
            </button>
            {entry.kind !== 'file' && <span className="badge">{entry.kind}</span>}
          </li>
        ))}
      </ul>

      <h3>Text preview</h3>
      {previewError && (
        <p className="error">
          [{previewError.code}] {previewError.message}
        </p>
      )}
      {!preview && !previewError && <p className="muted">Select a file to view its content.</p>}
      {preview && (
        <>
          <p className="muted mono">
            {preview.path} @ {preview.commit.slice(0, 12)}
          </p>
          {isMarkdownPath(preview.path) ? (
            // HTML is produced by markdown-it (raw source HTML escaped) and
            // sanitized by DOMPurify before injection; see markdown.ts.
            <div
              className="markdown-preview"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(preview.content) }}
            />
          ) : (
            <pre className="file-preview">{preview.content}</pre>
          )}
        </>
      )}
    </section>
  )
}
