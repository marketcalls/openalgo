/**
 * Tab and Shift+Tab in the script editor, worked out as text in and text out.
 *
 * A text area hands Tab to the browser, which moves focus to the next control.
 * In a language where a block is its indentation that is the one key an author
 * cannot do without: every `if` needs a body indented under it, and typing four
 * spaces by hand on every line is how a body ends up with three.
 *
 * **Spaces, four of them, because that is the language's own answer.** A tab
 * character in leading whitespace is refused outright (OS1002, `language.md`
 * 3.10: the width of a tab is an editor setting, so a file whose meaning
 * depended on it would change meaning when somebody else opened it), and four
 * spaces is the formatter's output and what every example is written in. So Tab
 * never inserts a tab.
 *
 * **A selection is shifted by a whole level, line by line, and never re-aligned.**
 * Adding the same four spaces to every line keeps each line's indentation
 * relative to its neighbours exactly as it was, and in this language that
 * relation is the program: a body is whatever sits further in than its header.
 * Snapping each line to the next multiple of four instead would move a header on
 * two spaces and its body on four by different amounts, and could turn a valid
 * block into OS1010 with nothing on screen to say that Tab had done it.
 *
 * Pure so it can be tested without a browser, which cannot be asked what a key
 * press did to a text area. The panel applies the edit.
 */

/** One level of block: what the formatter writes and the examples use. */
export const INDENT = '    '

/** A replacement to make in the editor's text, and where the selection lands after it. */
export interface IndentEdit {
  /** The span of the current text that is replaced. */
  readonly from: number
  readonly to: number
  /** What replaces it. */
  readonly text: string
  /** The selection afterwards, as offsets into the edited text. */
  readonly selectionStart: number
  readonly selectionEnd: number
}

function lineStartOf(text: string, offset: number): number {
  return text.lastIndexOf('\n', offset - 1) + 1
}

function lineEndOf(text: string, offset: number): number {
  const at = text.indexOf('\n', offset)
  return at < 0 ? text.length : at
}

/** What one line's edit did: characters added (positive) or removed (negative) at `at`. */
interface LineChange {
  readonly at: number
  readonly delta: number
}

/**
 * Where an offset into the old text sits in the new one.
 *
 * An offset at the very start of a line that gained indentation stays put, so
 * a selection of whole lines grows to take in the spaces it was given and a
 * second Tab shifts the same lines again. An offset inside indentation that was
 * removed moves to where that indentation began.
 */
function moved(offset: number, changes: readonly LineChange[]): number {
  let shift = 0
  for (const change of changes) {
    if (change.at >= offset) break
    if (change.delta > 0) {
      shift += change.delta
    } else {
      const removed = -change.delta
      shift -= Math.min(removed, offset - change.at)
    }
  }
  return offset + shift
}

/**
 * Every line the selection touches, shifted one level in or out.
 *
 * A selection that ends at the very start of a line has not taken that line:
 * dragging over three whole lines leaves the end of the selection at the start
 * of the fourth, and indenting the fourth as well would be indenting a line
 * nobody chose. Null when nothing would change, so the caller does nothing.
 */
function shiftLines(text: string, start: number, end: number, inward: boolean): IndentEdit | null {
  const last = end > start && end === lineStartOf(text, end) ? end - 1 : end
  const from = lineStartOf(text, start)
  const to = lineEndOf(text, last)

  const changes: LineChange[] = []
  const lines = text.slice(from, to).split('\n')
  let at = from
  const out = lines.map((line) => {
    let next = line
    if (inward) {
      // An empty line is left empty. Indenting it would add trailing
      // whitespace and nothing else: a blank line carries no indentation in
      // this language, so the spaces would mean nothing and show up in a diff.
      if (line.length > 0) next = INDENT + line
    } else {
      const spaces = /^ */.exec(line)?.[0].length ?? 0
      next = line.slice(Math.min(spaces, INDENT.length))
    }
    if (next.length !== line.length) changes.push({ at, delta: next.length - line.length })
    at += line.length + 1
    return next
  })

  if (changes.length === 0) return null
  return {
    from,
    to,
    text: out.join('\n'),
    selectionStart: moved(start, changes),
    selectionEnd: moved(end, changes),
  }
}

/**
 * What Tab does.
 *
 * With nothing selected it types spaces up to the next level, so a caret part
 * way into a line lands on a column the formatter would agree with. With a
 * selection it indents every line the selection touches rather than replacing
 * the selected text with spaces, which is what a text box would do and is a
 * way to lose a word to a key that was meant to move it. Null for a selection
 * of nothing but empty lines, which have nothing to indent.
 */
export function indentEdit(text: string, start: number, end: number): IndentEdit | null {
  if (start === end) {
    const column = start - lineStartOf(text, start)
    const spaces = INDENT.slice(column % INDENT.length)
    return {
      from: start,
      to: end,
      text: spaces,
      selectionStart: start + spaces.length,
      selectionEnd: start + spaces.length,
    }
  }
  return shiftLines(text, start, end, true)
}

/**
 * What Shift+Tab does: every line the selection touches, or the caret's line,
 * one level out.
 *
 * Up to four spaces come off each line, fewer where a line has fewer, and a
 * line with none is left alone. Null when no line had any to give.
 */
export function outdentEdit(text: string, start: number, end: number): IndentEdit | null {
  return shiftLines(text, start, end, false)
}
