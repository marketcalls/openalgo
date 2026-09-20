/**
 * Colouring an OpenScript source, using the compiler's own lexer.
 *
 * **Nothing here knows the language.** The tokens come from the same lexer the
 * compiler runs, which is step one of the same pipeline that produces the
 * program. A hand written regex highlighter is a second, worse implementation
 * of the language that drifts the first time a keyword is added and nobody
 * notices until a release: the word simply stops being coloured, and the
 * highlighter is the last place anyone looks.
 *
 * The kinds are read rather than listed, for the same reason. A token whose
 * `kind` is its own text is a reserved word, because that is how the lexer
 * spells one; a kind of `identifier` is a name; anything whose kind is not made
 * of letters is punctuation. So a word added to the language is coloured the
 * day it lexes, and this file does not change.
 *
 * Comments are the one thing the lexer does not hand back, because the parser
 * has no use for them. They are recovered from the gaps between tokens, which
 * is the only place they can be.
 */

/** What a span is drawn as. Kept small: a palette, not a syntax theme. */
export type SpanKind =
  | 'comment'
  | 'string'
  | 'number'
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
 * What one token is drawn as.
 *
 * A reserved word is a token whose kind is the word itself, which is how the
 * lexer spells one. A name the standard library provides is asked of the
 * language through `isLibraryName`, never of a list kept here: a list would be
 * right the day it was written and wrong at the next release, and a built-in
 * that quietly stopped being coloured is the last thing anybody would check.
 *
 * Whether such a name is a function or a value is decided by what follows it,
 * not by a second table. `plot` is always written `plot(`, `close` never is.
 * That keeps the distinction in the one place that cannot drift from the
 * language: the token stream.
 */
function kindOf(
  tokenKind: string,
  text: string,
  followedByCall: boolean,
  isLibrary: (name: string) => boolean,
  namespaces: ReadonlySet<string>
): SpanKind {
  if (tokenKind === 'stringLiteral') return 'string'
  if (tokenKind === 'numberLiteral') return 'number'
  if (tokenKind === 'identifier') {
    if (isLibrary(text)) return followedByCall ? 'call' : 'builtin'
    if (namespaces.has(text)) return 'builtin'
    return 'identifier'
  }
  if (/^[a-zA-Z]+$/.test(tokenKind)) return tokenKind === text ? 'keyword' : 'identifier'
  return 'punctuation'
}

/**
 * Splits trivia into its comment and its whitespace.
 *
 * A comment runs to the end of its line, and trivia between two tokens can hold
 * a comment, a newline and the indentation of the next line, in that order.
 */
function trivia(text: string, out: HighlightedSpan[]): void {
  let rest = text
  while (rest.length > 0) {
    const start = rest.indexOf('//')
    if (start === -1) {
      out.push({ text: rest, kind: 'plain' })
      return
    }
    if (start > 0) out.push({ text: rest.slice(0, start), kind: 'plain' })
    const end = rest.indexOf('\n', start)
    if (end === -1) {
      out.push({ text: rest.slice(start), kind: 'comment' })
      return
    }
    out.push({ text: rest.slice(start, end), kind: 'comment' })
    rest = rest.slice(end)
    // The newline and anything after it go round again, so a comment on one
    // line does not swallow the line below it.
    const nextComment = rest.indexOf('//')
    if (nextComment === -1) {
      out.push({ text: rest, kind: 'plain' })
      return
    }
    out.push({ text: rest.slice(0, nextComment), kind: 'plain' })
    rest = rest.slice(nextComment)
  }
}

/**
 * The source as coloured spans, in order, covering every character exactly once.
 *
 * Covering every character is what lets the result be drawn under a transparent
 * text area and line up with it: a span dropped anywhere shifts every character
 * after it, and the caret stops sitting where the letters are.
 */
export async function highlight(source: string): Promise<HighlightedSpan[]> {
  if (source.length === 0) return []
  if (source.length > LIMIT) return [{ text: source, kind: 'plain' }]

  let tokens: { kind: string; span: { offset: number; length: number }; text: string }[]
  try {
    const { sourceFile, lex, DiagnosticBag, normaliseSource } = await import('openalgo-script')

    // **A token's offset is into the normalised source, not the text handed
    // in.** The compiler collapses line endings before it lexes, so on a file
    // with carriage returns every offset is short by one per line seen so far
    // and the drift accumulates. Slicing the raw text by those offsets returns
    // the wrong characters, and the damage is subtle rather than obvious: the
    // colours stay plausible near the top of the file and slide a word at a
    // time from there, which reads as a highlighter that cannot tell a comment
    // from code rather than as an off-by-one.
    //
    // Colouring the normalised text instead would break the one property this
    // module owes its caller, which is that the spans reconstruct what was
    // passed in exactly. So a source that is not already normalised is handed
    // back unpainted, and the editor keeps its text normalised so that never
    // happens in practice.
    if (normaliseSource(source) !== source) return [{ text: source, kind: 'plain' }]

    const file = sourceFile('editor.oscript', source)
    // A source that does not lex still colours as far as it got: the bag
    // collects the complaints and the tokens before them are still tokens.
    tokens = lex(file, new DiagnosticBag()) as never
  } catch {
    return [{ text: source, kind: 'plain' }]
  }

  const { isLibraryName, NAMESPACES } = await import('openalgo-script')
  const namespaces: ReadonlySet<string> = new Set(NAMESPACES as readonly string[])

  const spans: HighlightedSpan[] = []
  let at = 0
  for (const [index, token] of tokens.entries()) {
    // The next token decides whether a library name is a call or a value.
    // `newline` tokens carry no text, so the very next entry is the one to ask.
    const followedByCall = tokens[index + 1]?.kind === '('
    const { offset, length } = token.span
    if (offset > at) trivia(source.slice(at, offset), spans)
    if (length > 0) {
      spans.push({
        text: source.slice(offset, offset + length),
        kind: kindOf(token.kind, token.text, followedByCall, isLibraryName, namespaces),
      })
      at = offset + length
    } else if (offset > at) {
      at = offset
    }
  }
  if (at < source.length) trivia(source.slice(at), spans)
  return spans
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
  keyword: 'oscript-keyword',
  call: 'oscript-call',
  builtin: 'oscript-builtin',
  identifier: 'oscript-identifier',
  punctuation: 'oscript-punctuation',
  plain: 'oscript-plain',
}
