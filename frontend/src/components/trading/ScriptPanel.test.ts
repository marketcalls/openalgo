/**
 * The editor's layout invariant.
 *
 * The panel draws three columns that must stay in step: a gutter of line
 * numbers, a coloured layer, and a transparent text area over both. The gutter
 * draws exactly one row per line of source, because that is what a line number
 * is, so **nothing in the editor may wrap**.
 *
 * A wrapped line takes two rows of text and one row of gutter. The two columns
 * then have different heights, the same scroll offset moves each by a different
 * fraction of its own content, and the numbers slide away from the lines they
 * name. It does not look like a misalignment when it happens: it looks like the
 * file has been cut short, because the gutter runs out of numbers while the
 * text is still going. That is what shipped, and this is the check that would
 * have caught it.
 */

import { describe, expect, it } from 'vitest'
import { EDITOR_TEXT } from './ScriptPanel'

describe('the editor does not wrap', () => {
  it('holds the text to one row per line', () => {
    expect(EDITOR_TEXT).toContain('whitespace-pre')
  })

  it('is not the wrapping variant, which is the spelling that broke it', () => {
    // `whitespace-pre-wrap` contains `whitespace-pre`, so the assertion above
    // passes against the broken value on its own. This is the one that bites.
    expect(EDITOR_TEXT).not.toMatch(/whitespace-pre-wrap/)
    expect(EDITOR_TEXT).not.toMatch(/\bbreak-words\b/)
    expect(EDITOR_TEXT).not.toMatch(/\bbreak-all\b/)
  })

  it('keeps the metrics that make the three columns line up', () => {
    // A font, a size or a padding that differs between the layers puts the
    // caret a character away from its letter, and the drift grows along the
    // line. They live in one string so they cannot differ; this holds the
    // string to still carrying them.
    expect(EDITOR_TEXT).toContain('font-mono')
    expect(EDITOR_TEXT).toMatch(/text-\[12px\]/)
    expect(EDITOR_TEXT).toContain('px-2')
    expect(EDITOR_TEXT).toContain('py-2')
  })
})
