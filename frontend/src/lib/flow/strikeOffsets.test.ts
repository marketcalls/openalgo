/**
 * The strike-offset list the editor offers.
 *
 * The list counts out to MAX_STRIKE_OFFSET, matched to the chain window the
 * strike picker beside it uses. The executor accepts further than that -
 * ITM1-ITM50 and OTM1-OTM50 - so the list being narrower than the contract is
 * deliberate, and the part that matters is that a leg already storing a
 * further offset stays visible. The dropdowns used to stop at ITM5 and OTM10
 * with no such fallback, and one of them offered only six values at all: Radix
 * shows an unmatched value as an empty trigger, and the next thing the author
 * picked silently replaced a strike they never chose.
 */

import { describe, expect, it } from 'vitest'
import { MAX_STRIKE_OFFSET, STRIKE_OFFSETS, strikeOffsetOptions } from './constants'
import { OFFSET_PATTERN } from './customLegs'

const values = () => STRIKE_OFFSETS.map((offset) => offset.value)

describe('the offered offsets', () => {
  it('counts out to the window, ATM first and both directions in full', () => {
    const expected = ['ATM']
    for (const kind of ['ITM', 'OTM']) {
      for (let n = 1; n <= MAX_STRIKE_OFFSET; n++) expected.push(`${kind}${n}`)
    }

    expect(values()).toEqual(expected)
  })

  it('stops where the strike picker stops', () => {
    /** OPTION_STRIKE_WINDOW in blueprints/flow.py. The two controls are
     * alternatives on the same leg, so offering an offset further out than the
     * strike list can show names a contract the panel cannot confirm. */
    expect(MAX_STRIKE_OFFSET).toBe(25)
    expect(values()).toContain('OTM25')
    expect(values()).toContain('ITM25')
    expect(values()).not.toContain('OTM26')
    expect(values()).not.toContain('ITM26')
  })

  it('offers nothing the executor would reject', () => {
    /** The two copies of the rule - this list and the pattern the editor
     * validates a typed offset with - have to agree, or the picker hands back
     * a value its own validator refuses. */
    for (const value of values()) {
      expect(OFFSET_PATTERN.test(value), `${value} is not a valid offset`).toBe(true)
    }
  })

  it('reaches further than the old list stopped', () => {
    /** The reported symptom: OTM12 was valid and unselectable. */
    expect(values()).toContain('OTM12')
    expect(values()).toContain('ITM8')
  })

  it('names each distance in words', () => {
    expect(STRIKE_OFFSETS.find((o) => o.value === 'OTM1')?.description).toBe(
      '1 strike Out of The Money'
    )
    expect(STRIKE_OFFSETS.find((o) => o.value === 'ITM2')?.description).toBe(
      '2 strikes In The Money'
    )
  })
})

describe('an offset the list does not carry', () => {
  it('is kept selectable rather than dropped', () => {
    const options = strikeOffsetOptions('OTM60')

    expect(options[0].value).toBe('OTM60')
    expect(options).toHaveLength(STRIKE_OFFSETS.length + 1)
  })

  it('keeps an offset past the window that the executor still accepts', () => {
    /** OTM40 is beyond the picker but inside OPTION_OFFSET_PATTERN, so it runs
     * exactly as stored. Blanking it here would lose a deliberate far strike. */
    expect(OFFSET_PATTERN.test('OTM40')).toBe(true)
    expect(strikeOffsetOptions('OTM40')[0].value).toBe('OTM40')
  })

  it('is shown as stored, not corrected', () => {
    /** Silently rewriting it would change what the workflow trades without
     * saying so; the author is shown the value and left to decide. */
    expect(strikeOffsetOptions('otm2')[0].label).toBe('otm2')
  })

  it('leaves the list alone when the value is already in it', () => {
    expect(strikeOffsetOptions('OTM2')).toBe(STRIKE_OFFSETS)
    expect(strikeOffsetOptions('ATM')).toBe(STRIKE_OFFSETS)
  })

  it('leaves the list alone when there is no value yet', () => {
    expect(strikeOffsetOptions('')).toBe(STRIKE_OFFSETS)
    expect(strikeOffsetOptions(undefined)).toBe(STRIKE_OFFSETS)
    expect(strikeOffsetOptions(null)).toBe(STRIKE_OFFSETS)
  })
})
