import type { FileEntry } from './types'

export interface FileTreeDirectory {
  kind: 'directory'
  name: string
  path: string
  children: FileTreeNode[]
}

export interface FileTreeFile {
  kind: 'file'
  name: string
  entry: FileEntry
}

export type FileTreeNode = FileTreeDirectory | FileTreeFile

interface MutableDirectory {
  name: string
  path: string
  directories: Map<string, MutableDirectory>
  files: FileEntry[]
}

function makeDirectory(name: string, path: string): MutableDirectory {
  return { name, path, directories: new Map(), files: [] }
}

/** Build a deterministic directory hierarchy from the API's flat Git tree listing. */
export function buildFileTree(entries: FileEntry[]): FileTreeNode[] {
  const root = makeDirectory('', '')

  for (const entry of entries) {
    const segments = entry.path.split('/')
    const filename = segments.pop()
    if (!filename) continue

    let directory = root
    for (const segment of segments) {
      const path = directory.path ? `${directory.path}/${segment}` : segment
      let child = directory.directories.get(segment)
      if (!child) {
        child = makeDirectory(segment, path)
        directory.directories.set(segment, child)
      }
      directory = child
    }
    directory.files.push(entry)
  }

  const toNodes = (directory: MutableDirectory): FileTreeNode[] => {
    const directories: FileTreeDirectory[] = [...directory.directories.values()]
      .sort((left, right) => left.name.localeCompare(right.name))
      .map((child) => ({
        kind: 'directory',
        name: child.name,
        path: child.path,
        children: toNodes(child),
      }))
    const files: FileTreeFile[] = [...directory.files]
      .sort((left, right) => left.path.localeCompare(right.path))
      .map((entry) => ({ kind: 'file', name: entry.path.split('/').at(-1) ?? entry.path, entry }))
    return [...directories, ...files]
  }

  return toNodes(root)
}

export function directoryPaths(nodes: FileTreeNode[]): string[] {
  return nodes.flatMap((node) =>
    node.kind === 'directory' ? [node.path, ...directoryPaths(node.children)] : [],
  )
}
