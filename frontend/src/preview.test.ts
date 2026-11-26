import { describe, expect, it } from 'vitest'

import { isImagePath } from './api'

describe('isImagePath', () => {
  it('recognizes raster formats case-insensitively', () => {
    expect(isImagePath('results/plot.png')).toBe(true)
    expect(isImagePath('PHOTO.JPG')).toBe(true)
    expect(isImagePath('a/b/c.jpeg')).toBe(true)
    expect(isImagePath('anim.gif')).toBe(true)
    expect(isImagePath('modern.webp')).toBe(true)
  })

  it('never treats SVG or non-images as inline images', () => {
    expect(isImagePath('vector.svg')).toBe(false)
    expect(isImagePath('plot.png.txt')).toBe(false)
    expect(isImagePath('README.md')).toBe(false)
    expect(isImagePath('data.csv')).toBe(false)
  })
})
