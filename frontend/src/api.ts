import type { ApiError, Experiment, FileListing, Graph, TextFile } from './types'

export class ApiClientError extends Error {
  constructor(
    public status: number,
    public body: ApiError,
  ) {
    super(body.message)
    this.name = 'ApiClientError'
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiClientError) return error.body
  if (error instanceof Error) return { code: 'network_error', message: error.message }
  return { code: 'unknown_error', message: String(error) }
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  if (!response.ok) {
    let body: ApiError = { code: 'http_error', message: response.statusText }
    try {
      const parsed = (await response.json()) as { error?: ApiError }
      if (parsed?.error) body = parsed.error
    } catch {
      // keep the fallback body
    }
    throw new ApiClientError(response.status, body)
  }
  return (await response.json()) as T
}

function revisionQuery(commit: string | null | undefined): string {
  return commit ? `commit=${encodeURIComponent(commit)}` : ''
}

function withQuery(base: string, params: string[]): string {
  const query = params.filter(Boolean).join('&')
  return query ? `${base}?${query}` : base
}

export const api = {
  graph: (signal?: AbortSignal): Promise<Graph> => getJson('/api/graph', signal),
  experiment: (id: string, signal?: AbortSignal): Promise<Experiment> =>
    getJson(`/api/experiments/${encodeURIComponent(id)}`, signal),
  files: (id: string, commit: string | null, signal?: AbortSignal): Promise<FileListing> =>
    getJson(
      withQuery(`/api/experiments/${encodeURIComponent(id)}/files`, [revisionQuery(commit)]),
      signal,
    ),
  file: (
    id: string,
    path: string,
    commit: string | null,
    signal?: AbortSignal,
  ): Promise<TextFile> =>
    getJson(
      withQuery(`/api/experiments/${encodeURIComponent(id)}/file`, [
        revisionQuery(commit),
        `path=${encodeURIComponent(path)}`,
      ]),
      signal,
    ),
  /** Same-origin URL serving a committed raster image inline. */
  rawFileUrl: (id: string, path: string, commit: string | null): string =>
    withQuery(`/api/experiments/${encodeURIComponent(id)}/file/raw`, [
      revisionQuery(commit),
      `path=${encodeURIComponent(path)}`,
    ]),
}

/** Raster formats the backend serves inline (SVG is never served). */
const IMAGE_PATTERN = /\.(png|jpe?g|gif|webp)$/i

export function isImagePath(path: string): boolean {
  return IMAGE_PATTERN.test(path)
}

export { toApiError }
