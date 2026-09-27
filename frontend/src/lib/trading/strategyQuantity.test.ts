/**
 * Where the order size comes from, held against real compiled programs.
 *
 * The distinction this module rests on is only visible in a real program, so
 * the first block compiles the three forms rather than hand-writing what the
 * compiler is assumed to emit. A hand-written fixture here would agree with
 * whatever this module believed on the day it was written, which is exactly how
 * the settings encoding went wrong.
 */

import { describe, expect, it } from 'vitest'
import { quantityNote, quantityOf, unitsFor } from './strategyQuantity'

async function compile(source: string) {
  const { sourceFile, lex, parseTokens, check, emit, DiagnosticBag } = await import(
    'openalgo-script'
  )
  const bag = new DiagnosticBag()
  const handle = sourceFile('probe.oscript', source)
  const checked = check(handle, parseTokens(handle, lex(handle, bag), bag), bag)
  const program = emit(handle, checked, bag, {}).program
  if (program === undefined) {
    throw new Error(bag.ordered().map((one) => `${one.code} ${one.message}`).join('; '))
  }
  return program
}

describe('reading a real compiled program', () => {
  it('reads a written number as stated, which no host may change', async () => {
    const quantity = quantityOf(await compile('//@version=1\nstrategy("a", qty = 5)\nbuy()\n'))

    expect(quantity).toEqual({ kind: 'stated', units: 5 })
    expect(unitsFor(quantity, { anything: '99' })).toBe(5)
  })

  it('reads a quantity wired to an input as the trader own', async () => {
    // THE DISTINCTION THE WHOLE MODULE RESTS ON. A program writes a declaration
    // field either as a value or as a reference to one input, and that is the
    // only thing separating a size the author fixed from one they handed over.
    // Reading the reference as an opaque object would make every script's size
    // unknown, and reading it as a number would make it stated: both answer
    // "you may not change this" for a script that said you may.
    const quantity = quantityOf(
      await compile('//@version=1\nq = input(3, "Quantity", min = 1)\nstrategy("a", qty = q)\nbuy()\n')
    )

    expect(quantity.kind).toBe('input')
    if (quantity.kind !== 'input') return
    expect(quantity.key).toBe('q')
    expect(quantity.units).toBe(3)
  })

  it('reads a script that says nothing as stated at the language default', async () => {
    // Indistinguishable from a written qty = 1 in the compiled program, which is
    // why the note says so rather than this guessing.
    expect(quantityOf(await compile('//@version=1\nstrategy("a")\nbuy()\n'))).toEqual({
      kind: 'stated',
      units: 1,
    })
  })

  it('answers unknown for a study, which declares no size at all', async () => {
    expect(quantityOf(await compile('//@version=1\nstudy("a")\nplot(close)\n')).kind).toBe('unknown')
  })
})

describe('what a run will send', () => {
  const fromInput = { kind: 'input', key: 'q', units: 3 } as const

  it('uses what the trader typed for an input driven size', () => {
    expect(unitsFor(fromInput, { q: '10' })).toBe(10)
  })

  it('falls back to the declared default on an empty or unreadable box', () => {
    // Catches '' coerced to 0, which would send an order for nothing, and 'abc'
    // reaching the engine as NaN.
    expect(unitsFor(fromInput, { q: '' })).toBe(3)
    expect(unitsFor(fromInput, { q: '   ' })).toBe(3)
    expect(unitsFor(fromInput, { q: 'abc' })).toBe(3)
    expect(unitsFor(fromInput, {})).toBe(3)
  })

  it('ignores the form entirely for a stated size', () => {
    // THE RULE. A stated quantity is the author's decision about how much money
    // to spend per order. A form that could reach it would make this panel the
    // authority on that, and a stale box would trade a size nobody chose.
    expect(unitsFor({ kind: 'stated', units: 2 }, { q: '500', qty: '500' })).toBe(2)
  })

  it('answers nothing rather than a number it does not have', () => {
    expect(unitsFor({ kind: 'unknown' }, { q: '5' })).toBeNull()
  })
})

describe('what the trader is told', () => {
  it('names the one line that makes a fixed size settable', () => {
    // A script that says nothing trades one unit all day. Saying only "the
    // script sets this" leaves the trader with no way forward.
    expect(quantityNote({ kind: 'stated', units: 1 })).toContain('input(1, "Quantity", min = 1)')
  })

  it('says the size is the trader own when it comes from an input', () => {
    expect(quantityNote({ kind: 'input', key: 'q', units: 3 })).toMatch(/you choose/i)
  })

  it('never puts a code or a field name in front of a trader', () => {
    for (const quantity of [
      { kind: 'stated', units: 1 } as const,
      { kind: 'stated', units: 7 } as const,
      { kind: 'input', key: 'q', units: 3 } as const,
      { kind: 'unknown' } as const,
    ]) {
      const note = quantityNote(quantity)
      expect(note).not.toMatch(/OS\d{4}|meta\.|qtyType|undefined|null/)
      expect(note.endsWith('.')).toBe(true)
    }
  })
})
