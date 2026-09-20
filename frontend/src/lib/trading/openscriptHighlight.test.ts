/**
 * The editor's syntax colouring.
 *
 * One property matters more than which colour anything gets: **the spans must
 * reconstruct the source exactly**. They are painted underneath a text area
 * whose own text is transparent, so a single dropped or duplicated character
 * shifts every glyph after it and the caret stops sitting on the letter it
 * belongs to. That is a maddening bug to diagnose from a screenshot and a
 * one-line assertion to catch, so it is asserted on every shape below rather
 * than in one case.
 *
 * The colours themselves are asserted thinly and deliberately. What a keyword
 * is painted is a taste decision that should be free to change; what must not
 * change is that the lexer decides which word is a keyword, because the whole
 * point of driving this from the compiler is that it cannot drift from the
 * language.
 */

import { describe, expect, it } from 'vitest'
import { highlight, SPAN_CLASS, type SpanKind } from './openscriptHighlight'

/** The assertion that has to hold for every input, whatever it contains. */
async function covers(source: string): Promise<void> {
  const spans = await highlight(source)
  expect(spans.map((span) => span.text).join('')).toBe(source)
}

function kindsOf(spans: { text: string; kind: SpanKind }[], text: string): SpanKind[] {
  return spans.filter((span) => span.text === text).map((span) => span.kind)
}

describe('the spans reconstruct the source', () => {
  const shapes: [string, string][] = [
    ['empty', ''],
    ['one word', 'close'],
    ['a whole study', 'version 1\nstudy("S", overlay = true)\nplot(close, "C", aqua)\n'],
    ['a trailing comment', 'a = 1 // why\n'],
    ['a comment on its own line', '// a note\nb = 2\n'],
    ['two comments', '// one\n// two\nc = 3\n'],
    ['a comment with no newline after it', 'd = 4 // end'],
    ['slashes inside a string', 'e = "http://not a comment"\n'],
    ['indentation', 'if close > open\n    f = 1\n'],
    ['blank lines between statements', 'g = 1\n\n\nh = 2\n'],
    ['windows line endings', 'i = 1\r\nj = 2\r\n'],
    ['a tab', '\tk = 1\n'],
    ['unicode in a string', 'l = "a b c"\n'],
    ['text that does not lex', 'm = @@@ !\n'],
    ['an unterminated string', 'n = "open\n'],
    ['only whitespace', '   \n\n  '],
    ['only a comment', '// nothing else'],
  ]

  for (const [name, source] of shapes) {
    it(name, async () => {
      await covers(source)
    })
  }
})

describe('the lexer decides what a keyword is', () => {
  it('a reserved word and a name are told apart', async () => {
    // `study` is the language's own word and `myLength` is the author's. If
    // this ever inverts, the highlighter has stopped reading the lexer and
    // started guessing, which is the failure this file exists to prevent.
    const spans = await highlight('study("S")\nmyLength = 3\n')
    expect(kindsOf(spans, 'study')).toEqual(['keyword'])
    expect(kindsOf(spans, 'myLength')).toEqual(['identifier'])
  })

  it('a string, a number and punctuation are each their own kind', async () => {
    const spans = await highlight('plot(close, "C")\n')
    expect(kindsOf(spans, '"C"')).toEqual(['string'])
    expect(kindsOf(spans, '(')).toEqual(['punctuation'])

    const numbers = await highlight('x = 42\n')
    expect(kindsOf(numbers, '42')).toEqual(['number'])
  })

  it('a comment is a comment and the code after it is not', async () => {
    const spans = await highlight('a = 1 // note\nb = 2\n')
    expect(kindsOf(spans, '// note')).toEqual(['comment'])
    // The line below the comment must survive as code. A comment that ran to
    // the end of the source rather than the end of its line would grey out the
    // rest of the file, which is the obvious way to write this wrong.
    expect(kindsOf(spans, 'b')).toEqual(['identifier'])
  })

  it('what looks like a comment inside a string is left alone', async () => {
    const spans = await highlight('a = "// not a note"\n')
    expect(spans.some((span) => span.kind === 'comment')).toBe(false)
  })
})

describe('it stays out of the way when it cannot help', () => {
  it('a source past the size limit is returned whole and unpainted', async () => {
    const huge = `x = 1\n`.repeat(20000)
    const spans = await highlight(huge)
    expect(spans).toHaveLength(1)
    expect(spans[0]?.kind).toBe('plain')
    expect(spans[0]?.text).toBe(huge)
  })

  it('every kind has a class, so a span can never render unstyled', () => {
    const kinds: SpanKind[] = [
      'comment',
      'string',
      'number',
      'keyword',
      'identifier',
      'punctuation',
      'plain',
    ]
    for (const kind of kinds) {
      expect(SPAN_CLASS[kind]).toBeTruthy()
    }
  })
})
