import { describe, expect, it } from 'vitest'

import { buildFileTree, directoryPaths } from './fileTree'

describe('buildFileTree', () => {
  it('nests paths and sorts folders before files', () => {
    const tree = buildFileTree([
      { path: 'results/plot.png', size: 5, kind: 'file' },
      { path: 'README.md', size: 5, kind: 'file' },
      { path: 'src/main.py', size: 5, kind: 'file' },
      { path: 'src/lib/helpers.py', size: 5, kind: 'file' },
      { path: 'notes.txt', size: 5, kind: 'file' },
    ])

    expect(tree.map((node) => node.name)).toEqual(['results', 'src', 'notes.txt', 'README.md'])
    expect(tree[1]).toMatchObject({
      kind: 'directory',
      path: 'src',
      children: [
        { kind: 'directory', name: 'lib', path: 'src/lib' },
        { kind: 'file', name: 'main.py', entry: { path: 'src/main.py' } },
      ],
    })
    expect(directoryPaths(tree)).toEqual(['results', 'src', 'src/lib'])
  })
})
