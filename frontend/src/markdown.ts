import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

// Repository-controlled markdown is untrusted input. Defense in depth:
// 1. markdown-it is configured with html: false, so raw HTML in the source
//    is escaped rather than passed through.
// 2. The rendered HTML is sanitized with DOMPurify; images and style
//    attributes/tags are forbidden entirely (no external resource loading,
//    per the spec), and only safe link protocols survive (DOMPurify blocks
//    javascript: etc.; markdown-it already validates schemes).
// 3. External links open in a new tab with noopener.
const md = new MarkdownIt({ html: false, linkify: true, breaks: false })

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

/** Render untrusted markdown source to sanitized HTML safe for inline display. */
export function renderMarkdown(source: string): string {
  return DOMPurify.sanitize(md.render(source), {
    FORBID_TAGS: ['img', 'style'],
    FORBID_ATTR: ['style'],
  })
}

/** Whether a committed path is treated as markdown in the preview panel. */
export function isMarkdownPath(path: string): boolean {
  return /\.(md|markdown)$/i.test(path)
}
