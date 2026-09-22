/**
 * Reading a strategy's inputs and declarations off its compiled program.
 *
 * Every test names the wrong implementation it catches. The one that matters
 * most is the last: sending back every field rather than only what was edited
 * makes this panel the authority on a script's defaults, and the first time the
 * two disagree is a run whose inputs the script never agreed to.
 */

import { describe, expect, it } from 'vitest'
import {
  declaredOf,
  defaultValueOf,
  inputsOf,
  settingsFromForm,
} from './backtestInputs'

const PROGRAM = {
  meta: {
    kind: 'strategy',
    strategy: {
      capital: 100000,
      currency: '',
      qty: 1,
      qtyType: 'units',
      product: 'intraday',
      fillOn: 'nextOpen',
      slippage: 0,
      commission: 0,
      commissionType: 'perTrade',
      pyramiding: 1,
      closeOnSessionEnd: false,
    },
  },
  inputs: [
    { key: 'atrLen', kind: 'number', label: 'ATR length', default: ['n', 10], min: 1, max: 200 },
    { key: 'factor', kind: 'number', label: 'Factor', default: ['n', 3], min: 0.01, max: 20 },
  ],
}

describe('reading the program', () => {
  it('reads every input with its label and bounds', () => {
    const found = inputsOf(PROGRAM)
    expect(found.map((one) => one.key)).toEqual(['atrLen', 'factor'])
    expect(found[0].label).toBe('ATR length')
    expect(found[0].min).toBe(1)
    expect(found[0].max).toBe(200)
  })

  it('reads a default out of the tagged pair the program writes', () => {
    // Catches the array read as a value. The program writes ["n", 10], so a
    // field taking the array itself shows "n,10" and sends nonsense back.
    expect(defaultValueOf(inputsOf(PROGRAM)[0])).toBe(10)
  })

  it('reads what the script declared about itself', () => {
    const declared = declaredOf(PROGRAM)
    expect(declared?.capital).toBe(100000)
    expect(declared?.qtyType).toBe('units')
    expect(declared?.commissionType).toBe('perTrade')
  })

  it('answers empty rather than throwing on a program it does not recognise', () => {
    // Catches a panel that takes the whole run down over a settings list. The
    // program is JSON off a compiler and a shape nobody expected is possible.
    expect(inputsOf(null)).toEqual([])
    expect(inputsOf({ inputs: 'not a list' })).toEqual([])
    expect(declaredOf({})).toBeNull()
  })
})

describe('what the form sends back', () => {
  const declarations = inputsOf(PROGRAM)

  it('sends only what was edited, so an untouched input keeps the script default', () => {
    // THE ONE THAT MATTERS. Sending every field makes this panel the authority
    // on defaults; the first divergence is a run whose inputs the script never
    // agreed to. An untouched field must be absent so the engine resolves the
    // declaration's own value.
    const sent = settingsFromForm(declarations, { atrLen: '14' })

    expect(sent).toEqual({ atrLen: { kind: 'number', value: 14 } })
    expect(sent.factor).toBeUndefined()
  })

  it('treats an emptied field as untouched rather than as zero', () => {
    // Catches '' coerced by Number to 0, which is a real value and inside some
    // ranges: the run would silently use zero where the trader cleared the box.
    expect(settingsFromForm(declarations, { atrLen: '' })).toEqual({})
  })

  it('refuses a value outside the bounds the script declared', () => {
    // Catches bounds treated as decoration. They are the script's own, and the
    // engine refuses a value past them before the first bar, so sending it
    // turns a typo into a refused run instead of a field that will not take it.
    expect(settingsFromForm(declarations, { atrLen: '0' })).toEqual({})
    expect(settingsFromForm(declarations, { atrLen: '500' })).toEqual({})
    expect(settingsFromForm(declarations, { atrLen: '200' })).toEqual({
      atrLen: { kind: 'number', value: 200 },
    })
  })

  it('drops a number that is not one rather than sending NaN', () => {
    expect(settingsFromForm(declarations, { atrLen: 'abc' })).toEqual({})
  })

  it('tags a value by the kind the declaration states', () => {
    const mixed = inputsOf({
      inputs: [
        { key: 'on', kind: 'bool', label: 'On', default: ['b', true] },
        { key: 'name', kind: 'string', label: 'Name', default: ['s', 'x'] },
      ],
    })
    expect(settingsFromForm(mixed, { on: 'true', name: 'hello' })).toEqual({
      on: { kind: 'bool', value: true },
      name: { kind: 'string', value: 'hello' },
    })
  })
})
