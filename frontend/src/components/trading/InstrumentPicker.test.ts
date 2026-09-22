/**
 * Which products a venue actually takes, and what happens when the venue changes.
 *
 * A product is not a preference: a cash venue settles in shares and takes
 * delivery or intraday, and a derivative venue carries a contract on margin and
 * takes normal or intraday. Offering the wrong one is a form that looks complete
 * and an order the broker rejects, after a signal has already been acted on.
 *
 * Each test names the wrong implementation it catches.
 */

import { describe, expect, it } from 'vitest'
import { productFor, productsOn } from './InstrumentPicker'

describe('the products a venue takes', () => {
  it('offers delivery on a cash venue and never normal', () => {
    for (const venue of ['NSE', 'BSE']) {
      expect(productsOn(venue)).toEqual(['MIS', 'CNC'])
    }
  })

  it('offers normal on a derivative venue and never delivery', () => {
    // Catches one list for every venue. NRML on a stock and CNC on a future are
    // both rejected at the broker, which is a signal acted on and an order that
    // never went.
    for (const venue of ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX', 'NCO']) {
      expect(productsOn(venue)).toEqual(['MIS', 'NRML'])
    }
  })

  it('reads a venue whatever case it arrives in', () => {
    expect(productsOn('mcx')).toEqual(['MIS', 'NRML'])
    expect(productsOn(' NFO ')).toEqual(['MIS', 'NRML'])
  })

  it('treats a venue it does not know as cash', () => {
    // The safer of the two to guess: a cash product on a venue that wanted a
    // margin one is refused at the broker and nothing has been carried
    // overnight on a contract nobody meant to carry.
    expect(productsOn('')).toEqual(['MIS', 'CNC'])
    expect(productsOn('SOMETHING')).toEqual(['MIS', 'CNC'])
  })
})

describe('moving a deployment between venues', () => {
  it('keeps a product the new venue still takes', () => {
    // MIS is taken everywhere, so a trader who chose intraday keeps it.
    expect(productFor('MCX', 'MIS')).toBe('MIS')
    expect(productFor('NSE', 'MIS')).toBe('MIS')
  })

  it('moves a product the new venue does not take', () => {
    // THE ONE THAT MATTERS. Switching a deployment from a stock to a future
    // left CNC in the box: the form read as complete and the order was refused.
    expect(productFor('MCX', 'CNC')).toBe('MIS')
    expect(productFor('NSE', 'NRML')).toBe('MIS')
  })

  it('answers something for an empty product rather than leaving it empty', () => {
    expect(productFor('NSE', '')).toBe('MIS')
    expect(productFor('NFO', '')).toBe('MIS')
  })

  it('reads a chosen product whatever case it arrives in', () => {
    expect(productFor('NSE', 'cnc')).toBe('CNC')
  })
})
