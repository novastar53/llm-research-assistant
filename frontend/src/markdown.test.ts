// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import { isMarkdownPath, renderMarkdown } from './markdown'

describe('renderMarkdown (untrusted repository content)', () => {
  it('renders basic markdown structure', () => {
    const html = renderMarkdown('# Title\n\nSome **bold** text.\n\n- a\n- b\n')
    expect(html).toContain('<h1>Title</h1>')
    expect(html).toContain('<strong>bold</strong>')
    expect(html).toContain('<li>a</li>')
  })

  it('renders tables and fenced code blocks', () => {
    const html = renderMarkdown('| x | y |\n| --- | --- |\n| 1 | 2 |\n\n```python\npass\n```')
    expect(html).toContain('<table>')
    expect(html).toContain('<code class="language-python">')
  })

  it('escapes raw HTML in the source', () => {
    const html = renderMarkdown('<script>alert("x")</script>')
    expect(html).not.toContain('<script>') // no live tag...
    expect(html).toContain('&lt;script&gt;') // ...only escaped literal text
  })

  it('escapes markup with event-handler attributes', () => {
    const html = renderMarkdown('<img src="x" onerror="alert(1)">')
    expect(html).not.toContain('<img') // no live element, so no handler can fire
    expect(html).toContain('&lt;img')
  })

  it('refuses unsafe link protocols', () => {
    const html = renderMarkdown('[click me](javascript:alert(1))')
    expect(html).not.toContain('href="javascript:') // markdown-it drops the unsafe href
  })

  it('strips images entirely (no external resource loading)', () => {
    const html = renderMarkdown('![alt](https://example.com/tracker.png)')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('example.com')
  })

  it('marks safe external links with noopener and a new tab target', () => {
    const html = renderMarkdown('[docs](https://example.com/docs)')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('target="_blank"')
  })
})

describe('isMarkdownPath', () => {
  it('recognizes markdown extensions case-insensitively', () => {
    expect(isMarkdownPath('README.md')).toBe(true)
    expect(isMarkdownPath('results/notes.MARKDOWN')).toBe(true)
    expect(isMarkdownPath('src/train.py')).toBe(false)
    expect(isMarkdownPath('report.mdown.txt')).toBe(false)
  })
})
