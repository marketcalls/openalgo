/**
 * Colouring an OpenScript source, using the language's own highlighter.
 *
 * **Nothing here knows the language.** The pieces come from
 * `openalgo-script/editor`, which is the compiler wearing a different hat: the
 * real lexer produces the tokens, and what each one is painted as is decided by
 * the language's own tables of reserved words, operator marks and library names.
 * A word added to the language is coloured the day it lexes, and this file does
 * not change.
 *
 * This used to be a reading of the token stream done here, and it was right
 * about most of it and quietly wrong about the rest. A reserved word was "a
 * token whose kind is its own text", which is true and is also true of every
 * punctuation mark; the test that a kind is made of letters passed for
 * `hexColor`, `indent`, `newline` and `dedent`, so a colour literal and a line's
 * leading spaces were both painted as identifiers. Comments were recovered here
 * too, by scanning the gaps between tokens for a comment marker. None of that
 * was unreasonable and all of it was a second implementation of the language
 * kept in step by attention.
 *
 * What is still ours is the palette: which of the language's eleven kinds share
 * a colour in this product, and whether a library name written with a bracket
 * after it is painted differently from one read as a value. Those are design
 * decisions about this editor, not facts about the language, which is exactly
 * the line the package draws.
 */

/** What a span is drawn as. Kept small: a palette, not a syntax theme. */
export type SpanKind =
  | 'comment'
  | 'string'
  | 'number'
  /** A hexadecimal colour literal, which the language has and most do not. */
  | 'color'
  | 'keyword'
  /** A name the standard library provides and calls: `plot`, `ema`, `input`. */
  | 'call'
  /** A name the standard library provides as a value: `close`, `aqua`, `math`. */
  | 'builtin'
  | 'identifier'
  | 'punctuation'
  | 'plain'

export interface HighlightedSpan {
  text: string
  kind: SpanKind
}

/**
 * Above this, the source is drawn unhighlighted.
 *
 * Lexing is fast and rebuilding thousands of coloured spans on every keystroke
 * is not. A study is a few hundred lines; a file this size is not one somebody
 * is typing into, and a panel that stutters while you write is worse than one
 * that is monochrome.
 */
const LIMIT = 64 * 1024

/**
 * The language's eleven kinds, as this product's palette.
 *
 * Ten of the eleven map straight across. `builtin` is the one that does not,
 * because this editor paints a library call differently from a library value,
 * and the language has no opinion about that: `plot` and `close` are both names
 * the manifest holds. Which of the two a name is is decided below by what
 * follows it, which is the one question this file still asks of the token
 * stream and the only one it can answer without knowing the language.
 */
const PALETTE: Record<string, SpanKind> = {
  keyword: 'keyword',
  builtin: 'builtin',
  name: 'identifier',
  number: 'number',
  string: 'string',
  color: 'color',
  comment: 'comment',
  // The language tells an operator from a bracket; this palette does not, and a
  // panel with two greys in it reads as a panel that could not decide.
  operator: 'punctuation',
  punctuation: 'punctuation',
  whitespace: 'plain',
  // Not "wrong": a character the language does not have, a region somebody
  // pasted as a block comment, a continuation backslash. The compiler's own
  // diagnostics are what say whether any of it is a mistake, and painting it red
  // here would be this file having a second opinion about the language.
  unknown: 'plain',
}

/**
 * The source as coloured spans, in order, covering every character exactly once.
 *
 * Covering every character is what lets the result be drawn under a transparent
 * text area and line up with it: a span dropped anywhere shifts every character
 * after it, and the caret stops sitting where the letters are. The package
 * guarantees it of the pieces it returns, over every script in its own
 * repository and a corpus of malformed ones, so this file keeps the property
 * rather than having to establish it.
 */
export async function highlight(source: string): Promise<HighlightedSpan[]> {
  if (source.length === 0) return []
  if (source.length > LIMIT) return [{ text: source, kind: 'plain' }]

  try {
    const { normaliseSource } = await import('openalgo-script')

    // **Every offset the package produces indexes the normalised source**, not
    // the text handed in: the compiler drops a byte order mark and collapses
    // line endings before it lexes. The pieces carry their own text, so nothing
    // here indexes anything, but their texts then concatenate to the normalised
    // source rather than to what the caller passed, and this module's one
    // promise to its caller is that they reconstruct the source exactly.
    //
    // So a source that is not already in that form is handed back unpainted, and
    // the editor keeps its text normalised so that never happens in practice.
    // The alternative, painting the normalised text, drops the carriage returns
    // out of the panel while leaving them in the file.
    if (normaliseSource(source) !== source) return [{ text: source, kind: 'plain' }]

    const { highlight: pieces } = await import('openalgo-script/editor')
    const held = pieces(source)

    return held.map((piece, index) => ({
      text: piece.text,
      kind:
        piece.kind === 'builtin' && opensCall(held, index)
          ? 'call'
          : (PALETTE[piece.kind] ?? 'plain'),
    }))
  } catch {
    // A source the package refuses to read is still a source somebody is
    // looking at. Unpainted is the honest answer and it never loses a
    // character.
    return [{ text: source, kind: 'plain' }]
  }
}

/** Whether the next piece that is not a space opens an argument list. */
function opensCall(pieces: readonly { kind: string; text: string }[], index: number): boolean {
  for (let at = index + 1; at < pieces.length; at += 1) {
    const next = pieces[at]
    if (next === undefined) return false
    if (next.kind === 'whitespace') continue
    return next.text === '('
  }
  return false
}

/**
 * The class each kind is drawn with.
 *
 * The colours are CSS variables in `index.css` rather than utilities here,
 * because the operator picks the app's accent from six hues and a keyword
 * painted in a fixed one would vanish under a theme and shout under another.
 * Keeping them in the stylesheet also means retuning the palette is one edit
 * instead of a sweep through a component.
 */
export const SPAN_CLASS: Record<SpanKind, string> = {
  comment: 'oscript-comment',
  string: 'oscript-string',
  number: 'oscript-number',
  color: 'oscript-color',
  keyword: 'oscript-keyword',
  call: 'oscript-call',
  builtin: 'oscript-builtin',
  identifier: 'oscript-identifier',
  punctuation: 'oscript-punctuation',
  plain: 'oscript-plain',
}
