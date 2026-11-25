// Mirrors the backend Pydantic models (spec section 3.1). Repository
// controlled strings are rendered as text everywhere; never as HTML.

export type Relationship =
  | 'extends'
  | 'split_from'
  | 'combines'
  | 'replicates'
  | 'validates'

export interface ParentRef {
  id: string
  commit: string
  relationship: Relationship
}

export interface ExperimentManifest {
  id: string
  title: string
  description: string
  parents: ParentRef[]
}

export interface Experiment {
  branch: string
  commit: string
  manifest: ExperimentManifest
}

export interface Edge {
  source: string
  target: string
  source_commit: string
  relationship: Relationship
}

export interface Graph {
  nodes: Experiment[]
  edges: Edge[]
}

export type FileKind = 'file' | 'symlink' | 'submodule'

export interface FileEntry {
  path: string
  size: number
  kind: FileKind
}

export interface FileListing {
  commit: string
  files: FileEntry[]
}

export interface TextFile {
  path: string
  commit: string
  content: string
}

export interface ApiError {
  code: string
  message: string
}
