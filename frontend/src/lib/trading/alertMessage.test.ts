/**
 * Placeholders in an alert's message.
 *
 * The failure worth testing for is not a crash. It is a message that arrives on
 * a locked phone reading "RELIANCE crossed  on ", because a placeholder was
 * replaced with nothing: a sentence with holes reads as a fault in the alert,
 * and the trader has no way to tell it from one.
 */
import { describe, expect, it } from 'vitest'
import { ALERT_PLACEHOLDERS, fillAlertMessage } from './alertMessage'

const FACTS = {
  ticker: 'RELIANCE',
  exchange: 'NSE',
  interval: '1h',
  open: 1260.4,
  high: 1267.05,
  low: 1259.2,
  close: 1266.1,
  volume: 1_234_567.4,
  price: 1264.7,
  time: 1_758_441_600,
  digits: 2,
}

/** A fixed instant, so the text is the same in a test as it is in a terminal. */
const NOW = Date.UTC(2026, 8, 21, 6, 30)

describe('filling an alert message', () => {
  it('fills the instrument and the timeframe', () => {
    expect(fillAlertMessage('{{ticker}} on {{interval}}', FACTS, NOW)).toBe('RELIANCE on 1h')
  })

  it('fills the value that met the condition', () => {
    expect(fillAlertMessage('crossed {{price}}', FACTS, NOW)).toBe('crossed 1264.70')
  })

  it('writes a price at the instrument precision, not the number precision', () => {
    // A column where one price reads 1264.7 and the next 1266.10 looks like two
    // different instruments.
    expect(fillAlertMessage('{{price}} {{close}}', FACTS, NOW)).toBe('1264.70 1266.10')
  })

  it('writes a volume as a count rather than a price', () => {
    // Two decimals on a volume claims it was measured more finely than it was.
    expect(fillAlertMessage('{{volume}}', FACTS, NOW)).toBe('1234567')
  })

  it('fills every placeholder it advertises', () => {
    // The list the editor shows and the list this fills are the same list, or
    // the editor offers a placeholder that prints itself.
    for (const one of ALERT_PLACEHOLDERS) {
      const filled = fillAlertMessage(`{{${one.name}}}`, FACTS, NOW)
      expect(filled, `${one.name} was not filled`).not.toBe(`{{${one.name}}}`)
    }
  })

  it('tolerates the spacing a trader leaves inside the braces', () => {
    expect(fillAlertMessage('{{ ticker }}', FACTS, NOW)).toBe('RELIANCE')
  })

  it('is case insensitive about the name', () => {
    expect(fillAlertMessage('{{Ticker}} {{CLOSE}}', FACTS, NOW)).toBe('RELIANCE 1266.10')
  })

  it('leaves a placeholder it does not know exactly as it was typed', () => {
    // The mistake is a typo, and the text says so. Blanking it produces a
    // sentence with a hole that reads as a broken alert.
    expect(fillAlertMessage('crossed {{closs}}', FACTS, NOW)).toBe('crossed {{closs}}')
  })

  it('leaves a known placeholder standing when the chart has no value for it', () => {
    // A bar with no volume is not a bar with zero volume, and zero is a reading
    // somebody would act on.
    const noVolume = { ...FACTS, volume: null }
    expect(fillAlertMessage('vol {{volume}}', noVolume, NOW)).toBe('vol {{volume}}')
  })

  it('leaves text with no placeholders untouched', () => {
    expect(fillAlertMessage('take the second lot off', FACTS, NOW)).toBe('take the second lot off')
    expect(fillAlertMessage('', FACTS, NOW)).toBe('')
  })

  it('never re-reads what it just wrote', () => {
    // A value that happened to contain braces must not become a placeholder.
    const odd = { ...FACTS, ticker: '{{close}}' }
    expect(fillAlertMessage('{{ticker}}', odd, NOW)).toBe('{{close}}')
  })

  it('writes the delivery time and the bar time as different things', () => {
    const filled = fillAlertMessage('{{time}} | {{timenow}}', FACTS, NOW)
    const [bar, delivered] = filled.split(' | ')
    expect(bar).not.toBe(delivered)
    expect(delivered).toContain('2026-09-21')
  })

  it('fills nothing from an empty fact set rather than printing undefined', () => {
    expect(fillAlertMessage('{{ticker}} {{close}}', {}, NOW)).toBe('{{ticker}} {{close}}')
  })
})
