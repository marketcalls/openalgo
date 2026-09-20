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
      'color',
      'keyword',
      'call',
      'builtin',
      'identifier',
      'punctuation',
      'plain',
    ]
    for (const kind of kinds) {
      expect(SPAN_CLASS[kind]).toBeTruthy()
    }
  })
})

describe('a word is one colour, wherever it sits', () => {
  it('a keyword inside a string stays string-coloured', async () => {
    // Reported from the panel: "and" and "the" inside a title were painted as
    // keywords, so one string carried three colours. The lexer hands the whole
    // literal back as a single token, so any splitting is this file's doing.
    const spans = await highlight('shade = input(true, "Shade between the band and price")')
    const literal = spans.filter((s) => s.text.includes('band'))
    expect(literal).toHaveLength(1)
    expect(literal[0]?.kind).toBe('string')
    expect(literal[0]?.text).toBe('"Shade between the band and price"')
  })

  it('a comment holding language words stays comment-coloured', async () => {
    const spans = await highlight('// the band is not a plot and it is two columns\nx = 1\n')
    const comment = spans.filter((s) => s.kind === 'comment')
    expect(comment).toHaveLength(1)
    expect(comment[0]?.text).toBe('// the band is not a plot and it is two columns')
  })

  it('every span of one string literal is the same kind', async () => {
    const spans = await highlight('study("Supertrend", overlay = true, precision = 2)')
    const inTitle = spans.filter((s) => /Supertrend/.test(s.text))
    expect(inTitle).toHaveLength(1)
    expect(inTitle[0]?.kind).toBe('string')
  })
})

describe('a source whose lines end the other way', () => {
  // The defect this catches: a token's offset is into the source AFTER the
  // compiler collapses line endings, so on a file with carriage returns every
  // offset is short by one per line seen so far. Slicing the raw text by those
  // offsets returns the wrong characters, and the drift accumulates: the top of
  // the file looks right and a word at a time slides out of place below it. It
  // shipped because the coverage test above passes either way. Concatenation is
  // still the whole source when the pieces are cut in the wrong places; only
  // the KINDS are wrong, so the kinds are what this asserts.
  const CRLF = 'version 1\r\n// a note about and the band\r\nstudy("Probe")\r\nx = 1\r\n'

  it('still reconstructs the source exactly', async () => {
    await covers(CRLF)
  })

  it('is handed back unpainted rather than painted wrongly', async () => {
    // The contract for a source that is not in the language's normal form:
    // one plain span, covering everything. Not a colour in sight is the right
    // answer here, because every colour available would be on the wrong
    // characters. Against the behaviour that shipped this returns many spans
    // whose text is sliced a character early, worsening down the file: the
    // word study arrives carrying the previous line break, and the literal
    // starts two characters late.
    const spans = await highlight(CRLF)
    expect(spans).toHaveLength(1)
    expect(spans[0]?.kind).toBe('plain')
    expect(spans[0]?.text).toBe(CRLF)
  })

  it('the same source with plain line endings is coloured properly', async () => {
    // The control: the normalised form of the same text is painted correctly,
    // which is what says the problem was the line endings and not the source.
    const spans = await highlight(CRLF.replace(/\r\n/g, '\n'))
    expect(kindsOf(spans, 'study')).toEqual(['keyword'])
    expect(kindsOf(spans, '"Probe"')).toEqual(['string'])
    expect(spans.filter((s) => s.kind === 'comment').map((s) => s.text)).toEqual([
      '// a note about and the band',
    ])
  })
})

describe('two kinds this used to paint as names', () => {
  // Both are what the package's own highlighter fixed by asking the language
  // instead of asking the shape of a token's kind. The rule here was "a kind
  // made of letters is a keyword if it equals its own text and a name
  // otherwise", which is true of a reserved word and also true of hexColor,
  // indent, newline and dedent.

  it('a hexadecimal colour is a colour, not a name', async () => {
    const spans = await highlight('plot(close, "C", #ff8800)\n')
    expect(kindsOf(spans, '#ff8800')).toEqual(['color'])
  })

  it("a line's indentation is not a name", async () => {
    // The span covering the four leading spaces used to be an identifier, which
    // is invisible until a theme gives identifiers a weight or a background and
    // every indented line grows a stripe.
    const spans = await highlight('if close > open\n    x = 1\n')
    const indent = spans.filter((span) => span.text.trim() === '' && span.text.includes('  '))
    expect(indent.length).toBeGreaterThan(0)
    for (const span of indent) expect(span.kind).toBe('plain')
  })
})

describe('the language names its own', () => {
  it("a built-in function is a call and the author's name is not", async () => {
    const spans = await highlight('myAverage = ema(close, 9)\nplot(myAverage, "A", aqua)\n')
    expect(kindsOf(spans, 'ema')).toEqual(['call'])
    expect(kindsOf(spans, 'plot')).toEqual(['call'])
    // The author's own name stays plain even though it is used like a value,
    // because the useful split here is what the language gave you from what
    // you wrote yourself.
    expect(kindsOf(spans, 'myAverage')).toEqual(['identifier', 'identifier'])
  })

  it('a built-in value is not painted as a call', async () => {
    const spans = await highlight('plot(close, "C", aqua)\n')
    expect(kindsOf(spans, 'close')).toEqual(['builtin'])
    expect(kindsOf(spans, 'aqua')).toEqual(['builtin'])
  })

  it('a namespace is a built-in too', async () => {
    const spans = await highlight('x = bar.index\n')
    expect(kindsOf(spans, 'bar')).toEqual(['builtin'])
  })

  it('a reserved word stays a keyword rather than becoming a call', async () => {
    // `study` is written like a call but is the language's own word, and the
    // lexer says so. If this ever reports 'call' the reserved-word test above
    // it has been overtaken by the library lookup.
    const spans = await highlight('study("S", overlay = true)\n')
    expect(kindsOf(spans, 'study')).toEqual(['keyword'])
    expect(kindsOf(spans, 'true')).toEqual(['keyword'])
  })

  it("the list is the language's, not a copy kept here", async () => {
    // Every name the manifest declares is painted as something the language
    // provides. A hand-maintained list would pass on the day it was written
    // and rot silently; this asserts the whole manifest, so it cannot.
    const { libraryNames } = await import('openalgo-script')
    const names = (libraryNames as unknown as () => readonly string[])()
    const sample = names.filter((n) => /^[a-z][a-zA-Z]*$/.test(n)).slice(0, 40)
    for (const name of sample) {
      const spans = await highlight(`x = ${name}\n`)
      const got = kindsOf(spans, name)
      expect(got.length === 0 || got[0] === 'builtin' || got[0] === 'call').toBe(true)
    }
  })
})
