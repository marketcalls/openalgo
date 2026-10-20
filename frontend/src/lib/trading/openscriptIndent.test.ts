/**
 * Tab and Shift+Tab in the script editor.
 *
 * The rule that matters most is the one that is easiest to get subtly wrong:
 * **shifting a block must not change what it means.** In this language a body
 * is whatever sits further in than its header, so an indent that moved two
 * lines by different amounts could turn a working `if` into OS1010. The last
 * group compiles the result to prove the program is untouched.
 */

import { describe, expect, it } from 'vitest'
import { compileSource, starterFor } from './openscriptFiles'
import { INDENT, type IndentEdit, indentEdit, outdentEdit } from './openscriptIndent'

/** The text after an edit, as the editor would hold it. */
function applied(text: string, edit: IndentEdit | null): string {
  if (edit === null) return text
  return text.slice(0, edit.from) + edit.text + text.slice(edit.to)
}

/** A text with `|` marking a caret, or `[` and `]` marking a selection. */
function marked(spec: string): { text: string; start: number; end: number } {
  if (spec.includes('|')) {
    const at = spec.indexOf('|')
    return { text: spec.replace('|', ''), start: at, end: at }
  }
  const start = spec.indexOf('[')
  const end = spec.indexOf(']') - 1
  return { text: spec.replace('[', '').replace(']', ''), start, end }
}

/** The edited text with the resulting selection marked the same way. */
function pressed(spec: string, key: 'tab' | 'shift-tab'): string {
  const { text, start, end } = marked(spec)
  const edit = key === 'tab' ? indentEdit(text, start, end) : outdentEdit(text, start, end)
  const next = applied(text, edit)
  const from = edit?.selectionStart ?? start
  const to = edit?.selectionEnd ?? end
  if (from === to) return `${next.slice(0, from)}|${next.slice(from)}`
  return `${next.slice(0, from)}[${next.slice(from, to)}]${next.slice(to)}`
}

describe('Tab with nothing selected', () => {
  it('types spaces, never a tab character, which the language refuses', () => {
    const edit = indentEdit('if x', 0, 0)
    expect(edit?.text).toBe(INDENT)
    expect(edit?.text).not.toContain('\t')
  })

  it('indents by the four spaces the formatter writes', () => {
    expect(INDENT).toBe('    ')
    expect(pressed('|plot(x)', 'tab')).toBe('    |plot(x)')
  })

  it('fills to the next level from part way into a line', () => {
    expect(pressed('ab|c', 'tab')).toBe('ab  |c')
    expect(pressed('    x|', 'tab')).toBe('    x   |')
    expect(pressed('        |y', 'tab')).toBe('            |y')
  })

  it('counts the column from the start of its own line', () => {
    expect(pressed('first line\nab|c', 'tab')).toBe('first line\nab  |c')
  })
})

describe('Tab with a selection', () => {
  it('indents every line it touches rather than replacing the selected text', () => {
    expect(pressed('[a\nb]\nc', 'tab')).toBe('[    a\n    b]\nc')
  })

  it('indents the whole line when the selection is inside one line', () => {
    // A text box would replace the word with spaces. A key meant to move a
    // line should not be able to delete a word from it.
    expect(pressed('x = [close]', 'tab')).toBe('    x = [close]')
  })

  it('leaves a line the selection only reaches the start of', () => {
    // Dragging over two whole lines ends the selection at the start of the
    // third. Indenting that one too would be indenting a line nobody chose.
    expect(pressed('[a\nb\n]c', 'tab')).toBe('[    a\n    b\n]c')
  })

  it('leaves empty lines empty', () => {
    expect(pressed('[a\n\nb]', 'tab')).toBe('[    a\n\n    b]')
  })

  it('shifts every line by the same amount, keeping odd indentation as it was', () => {
    expect(pressed('[x\n  y\n      z]', 'tab')).toBe('[    x\n      y\n          z]')
  })

  it('does nothing to a selection of nothing but empty lines', () => {
    expect(indentEdit('\n\n', 0, 2)).toBeNull()
  })
})

describe('Shift+Tab', () => {
  it('takes one level off the line the caret is on', () => {
    expect(pressed('        x|', 'shift-tab')).toBe('    x|')
  })

  it('takes what there is when a line has less than a level', () => {
    expect(pressed('  x|', 'shift-tab')).toBe('x|')
  })

  it('takes a level off every line a selection touches', () => {
    expect(pressed('[    a\n        b]\nc', 'shift-tab')).toBe('[a\n    b]\nc')
  })

  it('does nothing when no line has any indentation to give', () => {
    expect(outdentEdit('a\nb', 0, 3)).toBeNull()
    expect(outdentEdit('x', 1, 1)).toBeNull()
  })

  it('moves a caret sitting inside the removed spaces to where they began', () => {
    expect(pressed('  |  x', 'shift-tab')).toBe('|x')
  })

  it('undoes what Tab did to the same selection', () => {
    const source = 'a = 1\nif a > 0\n    plot(a)\n'
    const edit = indentEdit(source, 0, source.length - 1)
    const indented = applied(source, edit)
    const back = outdentEdit(indented, edit?.selectionStart ?? 0, edit?.selectionEnd ?? 0)
    expect(applied(indented, back)).toBe(source)
  })
})

describe('a shifted block means what it meant', () => {
  // The strategy starter, because it is what a trader begins from and it has
  // two blocks with a blank line between them.
  const SOURCE = starterFor('shift', 'strategy')

  it('the starter compiles as it is, or the rest of this proves nothing', async () => {
    expect(SOURCE).toContain('if crossUp(fast, slow)\n    buy(qty = 1)')
    expect((await compileSource('shift.oscript', SOURCE)).ok).toBe(true)
  })

  it('both blocks indented and taken back out compile to the same script', async () => {
    const start = SOURCE.indexOf('if crossUp')
    const end = SOURCE.length - 1
    const edit = indentEdit(SOURCE, start, end)
    const indented = applied(SOURCE, edit)
    // Indented as a whole, each header sits one level in with its body still
    // one level further in again, and the blank line between them stays blank.
    expect(indented).toContain('    if crossUp(fast, slow)\n        buy(qty = 1)\n\n    if')
    const back = applied(
      indented,
      outdentEdit(indented, edit?.selectionStart ?? 0, edit?.selectionEnd ?? 0)
    )
    expect(back).toBe(SOURCE)
    expect((await compileSource('shift.oscript', back)).ok).toBe(true)
  })

  it('a body indented with Tab from column zero compiles', async () => {
    const unindented = SOURCE.replace('    buy(qty = 1)', 'buy(qty = 1)')
    expect((await compileSource('shift.oscript', unindented)).ok).toBe(false)
    const line = unindented.indexOf('buy(qty')
    const fixed = applied(unindented, indentEdit(unindented, line, line))
    expect(fixed).toBe(SOURCE)
    expect((await compileSource('shift.oscript', fixed)).ok).toBe(true)
  })
})
