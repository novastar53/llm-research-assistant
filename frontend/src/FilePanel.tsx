import { useEffect, useMemo, useRef, useState } from 'react'

import { api, isAbortError, isImagePath, toApiError } from './api'
import { buildFileTree, directoryPaths } from './fileTree'
import { isMarkdownPath, renderMarkdown } from './markdown'
import type { Revision } from './state'
import type { ApiError, FileEntry, FileListing, TextFile } from './types'
import type { FileTreeNode } from './fileTree'

interface FilePanelProps {
  experimentId: string
  revision: Revision
}

interface FileTreeListProps {
  nodes: FileTreeNode[]
  expandedDirectories: Set<string>
  onToggleDirectory: (path: string) => void
  onOpenFile: (entry: FileEntry) => void
  selectedPath: string | null
  depth?: number
}

function FileTreeList({
  nodes,
  expandedDirectories,
  onToggleDirectory,
  onOpenFile,
  selectedPath,
  depth = 0,
}: FileTreeListProps) {
  return (
    <ul className="file-tree" role={depth === 0 ? 'tree' : 'group'}>
      {nodes.map((node) => {
        const paddingLeft = `${8 + depth * 16}px`
        if (node.kind === 'directory') {
          const expanded = expandedDirectories.has(node.path)
          return (
            <li key={node.path} role="treeitem" aria-expanded={expanded}>
              <button
                className="file-tree__directory"
                style={{ paddingLeft }}
                onClick={() => onToggleDirectory(node.path)}
              >
                <span className="file-tree__chevron" aria-hidden="true">
                  {expanded ? '▾' : '▸'}
                </span>
                {node.name}
              </button>
              {expanded && (
                <FileTreeList
                  nodes={node.children}
                  expandedDirectories={expandedDirectories}
                  onToggleDirectory={onToggleDirectory}
                  onOpenFile={onOpenFile}
                  selectedPath={selectedPath}
                  depth={depth + 1}
                />
              )}
            </li>
          )
        }
        const { entry } = node
        return (
          <li key={entry.path} role="treeitem">
            <button
              className={`file-tree__file${selectedPath === entry.path ? ' file-tree__file--active' : ''}`}
              style={{ paddingLeft }}
              onClick={() => onOpenFile(entry)}
            >
              {node.name}
            </button>
            {entry.kind !== 'file' && <span className="badge">{entry.kind}</span>}
          </li>
        )
      })}
    </ul>
  )
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
  const [imagePreview, setImagePreview] = useState<{ path: string; url: string } | null>(null)
  const [previewError, setPreviewError] = useState<ApiError | null>(null)
  const [expandedDirectories, setExpandedDirectories] = useState<Set<string>>(() => new Set())
  const previewAbort = useRef<AbortController | null>(null)
  const tree = useMemo(() => buildFileTree(listing?.files ?? []), [listing])
  const directories = useMemo(() => directoryPaths(tree), [tree])

  useEffect(() => {
    const controller = new AbortController()
    setListing(null)
    setListingError(null)
    setPreview(null)
    setImagePreview(null)
    setPreviewError(null)
    setExpandedDirectories(new Set())
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
      setImagePreview(null)
      setPreviewError({
        code: 'unsupported_content',
        message: `${entry.path} is a ${entry.kind}; only regular files can be previewed`,
      })
      return
    }
    previewAbort.current?.abort()
    setPreview(null)
    setImagePreview(null)
    setPreviewError(null)
    if (isImagePath(entry.path)) {
      // the browser fetches the bytes from the same-origin raw endpoint
      setImagePreview({
        path: entry.path,
        url: api.rawFileUrl(experimentId, entry.path, commit),
      })
      return
    }
    const controller = new AbortController()
    previewAbort.current = controller
    api
      .file(experimentId, entry.path, commit, controller.signal)
      .then(setPreview)
      .catch((error: unknown) => {
        if (!isAbortError(error)) setPreviewError(toApiError(error))
      })
  }

  const toggleDirectory = (path: string) => {
    setExpandedDirectories((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const selectedPath = preview?.path ?? imagePreview?.path ?? null

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
      <div className="file-tree-panel">
        {directories.length > 0 && (
          <div className="file-tree__actions">
            <button onClick={() => setExpandedDirectories(new Set(directories))}>Expand all</button>
            <button onClick={() => setExpandedDirectories(new Set())}>Collapse all</button>
          </div>
        )}
        <FileTreeList
          nodes={tree}
          expandedDirectories={expandedDirectories}
          onToggleDirectory={toggleDirectory}
          onOpenFile={openFile}
          selectedPath={selectedPath}
        />
      </div>

      <h3>Text preview</h3>
      {previewError && (
        <p className="error">
          [{previewError.code}] {previewError.message}
        </p>
      )}
      {!preview && !imagePreview && !previewError && (
        <p className="muted">Select a file to view its content.</p>
      )}
      {imagePreview && (
        <>
          <p className="muted mono">
            {imagePreview.path} @ {commit ? commit.slice(0, 12) : 'HEAD'}
          </p>
          <div className="image-preview">
            <img
              src={imagePreview.url}
              alt={imagePreview.path}
              onError={() => {
                setImagePreview(null)
                setPreviewError({
                  code: 'preview_failed',
                  message: `could not load ${imagePreview.path} (unsupported format, missing, or too large)`,
                })
              }}
            />
          </div>
        </>
      )}
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
