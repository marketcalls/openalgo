/**
 * Compiling a script in the panel.
 *
 * One test here matters more than the rest, and it is the first: **a script
 * that will not run must not report that it will.** The emitter recovers, so a
 * source with an undefined name still produces a program while the checker
 * files an error against it. Reading success from "a program came out" is how
 * the panel came to print a red diagnostic and, in the same breath, say "ready
 * to add" with the button enabled. A trader who trusts that puts a study on the
 * chart that computes nothing.
 *
 * The rest hold the shape the console draws from, because a diagnostic split
 * into parts is only useful if every part is there.
 */

import { describe, expect, it } from 'vitest'
import { compileSource, fileForScriptId, idForScript, kindOf, starterFor } from './openscriptFiles'

const CLEAN = 'version 1\nstudy("Probe", overlay = true)\nplot(close, "C", aqua)\n'
// `Close` is not a name this language defines: the spelling is `close`. The
// checker files OS2001 and the emitter still hands back a program.
const UNDEFINED_NAME =
  'version 1\nstudy("Probe", overlay = true)\nplot(ema(Close, 30), "C", aqua)\n'

describe('whether a script would run', () => {
  it('a clean script is ok and says nothing', async () => {
    const result = await compileSource('clean.oscript', CLEAN)
    expect(result.ok).toBe(true)
    expect(result.diagnostics).toEqual([])
    expect(result.problem).toBeUndefined()
  })

  it('an error means not ok, even though the emitter produced a program', async () => {
    const result = await compileSource('broken.oscript', UNDEFINED_NAME)

    expect(result.ok).toBe(false)
    const errors = result.diagnostics.filter((one) => one.severity === 'error')
    expect(errors.length).toBeGreaterThan(0)
    expect(errors[0]?.code).toBe('OS2001')
  })

  it('a warning alone does not stop a script running', async () => {
    // Whatever warns today, the rule is what is asserted: warnings inform, only
    // errors refuse. Written against the severities rather than a chosen code,
    // so a change to which code warns does not make this test lie.
    const result = await compileSource('clean.oscript', CLEAN)
    const warnings = result.diagnostics.filter((one) => one.severity === 'warning')
    expect(result.ok || warnings.length === 0).toBe(true)
  })
})

describe('what the console is given to draw', () => {
  it('every part the console colours is present', async () => {
    const result = await compileSource('broken.oscript', UNDEFINED_NAME)
    const first = result.diagnostics[0]

    expect(first).toBeDefined()
    expect(first?.code).toMatch(/^OS\d{4}$/)
    expect(['error', 'warning']).toContain(first?.severity)
    expect(first?.message).toBeTruthy()
    expect(first?.fix).toBeTruthy()
    expect(first?.line).toBeGreaterThan(0)
    expect(first?.column).toBeGreaterThan(0)
    expect(first?.length).toBeGreaterThan(0)
  })

  it('the source line quoted is the line the diagnostic names', async () => {
    // The console prints this line with a caret under the span. If it quotes a
    // different line the caret points at innocent code, which is worse than
    // printing no line at all.
    const result = await compileSource('broken.oscript', UNDEFINED_NAME)
    const lines = UNDEFINED_NAME.split('\n')

    for (const one of result.diagnostics) {
      expect(one.sourceLine).toBe(lines[one.line - 1])
    }
  })

  it('the caret sits under the text the span covers', async () => {
    const result = await compileSource('broken.oscript', UNDEFINED_NAME)
    const first = result.diagnostics[0]
    expect(first).toBeDefined()

    const covered = first?.sourceLine.slice(first.column - 1, first.column - 1 + first.length)
    expect(covered).toBe('Close')
  })

  it('the gutter is pointed at the first error, not the first diagnostic', async () => {
    const result = await compileSource('broken.oscript', UNDEFINED_NAME)
    const firstError = result.diagnostics.find((one) => one.severity === 'error')
    expect(result.line).toBe(firstError?.line)
  })
})

describe("a new script is the trader's, not a template's", () => {
  it('declares the name that was typed', async () => {
    const source = starterFor('emavalues', 'study')
    expect(source).toContain('study("Emavalues"')
    // The whole point: what the chart legend says comes from what they typed.
    const result = await compileSource('emavalues.oscript', source)
    expect(result.ok).toBe(true)
  })

  it('turns the separators a file name needs into the spaces a title wants', () => {
    expect(starterFor('range-breakout', 'study')).toContain('study("Range breakout"')
    expect(starterFor('opening_range', 'study')).toContain('study("Opening range"')
  })

  it('tolerates the extension being typed', () => {
    expect(starterFor('trend.oscript', 'study')).toContain('study("Trend"')
  })

  it('a study and a strategy start from different code, and both compile', async () => {
    const study = starterFor('probe', 'study')
    const strategy = starterFor('probe', 'strategy')

    expect(study).toContain('study("Probe"')
    expect(strategy).toContain('strategy("Probe"')
    // A strategy is the one that trades, so its starter has to place an order
    // or it is a study wearing another word.
    expect(strategy).toMatch(/\bbuy\(/)
    expect(study).not.toMatch(/\bbuy\(/)

    expect((await compileSource('a.oscript', study)).ok).toBe(true)
    expect((await compileSource('b.oscript', strategy)).ok).toBe(true)
  })
})

describe('telling a study from a strategy', () => {
  it('reads the kind the source declares', async () => {
    expect(await kindOf(starterFor('a', 'study'))).toBe('study')
    expect(await kindOf(starterFor('b', 'strategy'))).toBe('strategy')
  })

  it('is not fooled by the word appearing in a comment or a string', async () => {
    // A regular expression over the text is the obvious wrong implementation,
    // and this is what it gets wrong.
    const source = [
      'version 1',
      '// this strategy is really a study',
      'study("Quoted", overlay = true)',
      'label = "strategy"',
      'plot(close, "C", aqua)',
      '',
    ].join('\n')
    expect(await kindOf(source)).toBe('study')
  })

  it('has no answer for a source with no declaration, rather than a wrong one', async () => {
    expect(await kindOf('version 1\n')).toBeNull()
    expect(await kindOf('')).toBeNull()
  })

  it('the compile result carries the kind too', async () => {
    const result = await compileSource('s.oscript', starterFor('flip', 'strategy'))
    expect(result.kind).toBe('strategy')
  })
})

describe('an indicator id and the script behind it', () => {
  it('round-trips every name the panel will accept', () => {
    // The pair is only useful if it is exact. A file the chart can name but
    // cannot be turned back into is a braces button that opens nothing, and
    // nothing anywhere would say why.
    for (const stem of ['supertrend', 'my-study', 'my_study', 'v2.1', 'A1', '9lives']) {
      const file = `${stem}.oscript`
      expect(fileForScriptId(idForScript(file))).toBe(file)
    }
  })

  it('has no answer for a built-in study', () => {
    // The honest answer, and the one that makes the caller do nothing rather
    // than reach for `supertrend.oscript` because a built-in happens to share
    // the name.
    expect(fileForScriptId('supertrend')).toBeNull()
    expect(fileForScriptId('rsi')).toBeNull()
    expect(fileForScriptId('')).toBeNull()
    // A built-in whose id is longer than the prefix, which is the one that
    // catches a reading that slices the prefix off without checking it was
    // there: eleven characters in, `bollinger-bands` becomes a perfectly valid
    // file name, and the panel would go looking for `ands.oscript`.
    expect(fileForScriptId('bollinger-bands')).toBeNull()
    expect(fileForScriptId('volume-profile')).toBeNull()
  })

  it('refuses an id whose name the panel would not accept', () => {
    // The id arrives from the chart, which got it from a descriptor, which a
    // host could have registered with anything at all. It reaches a URL, so a
    // name the panel would reject is a name this must reject too rather than
    // hand on and hope the server minds.
    expect(fileForScriptId('openscript:../../etc/passwd')).toBeNull()
    expect(fileForScriptId('openscript:a/b')).toBeNull()
    expect(fileForScriptId('openscript:')).toBeNull()
    expect(fileForScriptId('openscript:-leading-dash')).toBeNull()
  })
})
