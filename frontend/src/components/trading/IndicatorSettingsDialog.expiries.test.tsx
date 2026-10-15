/**
 * The OI Profile's expiry pick list in the settings dialog.
 *
 * The dialog carries its own copy of the indicator's rules for which
 * underlying and exchange a chart means, and the copy fell behind: it turned
 * M&M into "MM", never looked on MCX, and said "No expiries found" while the
 * lookup was still running. Found by driving /trading in a browser.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import type { IndicatorSettingsRequest } from '@/lib/trading/terminal'
import { render, screen } from '@/test/test-utils'
import { exchangesOf, IndicatorSettingsDialog, underlyingOf } from './IndicatorSettingsDialog'

describe('which underlying and exchange the picker asks about', () => {
  it('keeps & and - and strips a future or an option', () => {
    expect(underlyingOf('', 'M&M')).toBe('M&M')
    expect(underlyingOf('', 'BAJAJ-AUTO27OCT26FUT')).toBe('BAJAJ-AUTO')
    expect(underlyingOf('', 'NIFTY27OCT2625000CE')).toBe('NIFTY')
    expect(underlyingOf('', 'TMPV29SEP26320.5PE')).toBe('TMPV')
    expect(underlyingOf(' crudeoil ', 'NIFTY27OCT26FUT')).toBe('CRUDEOIL')
  })

  it('looks on every F&O exchange on Auto, and only on the chosen one otherwise', () => {
    expect(exchangesOf('auto', 'CRUDEOIL')).toEqual(['NFO', 'BFO', 'MCX'])
    expect(exchangesOf('', 'SENSEX')).toEqual(['BFO', 'NFO', 'MCX'])
    expect(exchangesOf('MCX', 'CRUDEOIL')).toEqual(['MCX'])
  })
})

describe('the expiry list', () => {
  const req: IndicatorSettingsRequest = {
    instanceId: 'oi-1',
    name: 'OI Profile',
    inputs: [
      {
        key: 'exchange',
        type: 'select',
        label: 'Exchange',
        options: [{ label: 'Auto', value: 'auto' }],
      },
      { key: 'expiries', type: 'number', label: 'Expiries To Combine' },
      { key: 'expiryDate', type: 'expiries', label: 'Expiry Used' },
    ],
    styleInputs: [],
    values: { exchange: 'auto', expiries: 1, expiryDate: '' },
  } as unknown as IndicatorSettingsRequest

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('says it is loading until the answer comes, then finds CRUDEOIL on MCX', async () => {
    const asked: string[] = []
    let release: () => void = () => {}
    const gate = new Promise<void>((r) => {
      release = r
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const exchange = new URL(url, 'http://x').searchParams.get('exchange') ?? ''
        asked.push(exchange)
        await gate
        const expiries = exchange === 'MCX' ? ['19-OCT-26', '17-NOV-26'] : []
        return { ok: true, json: async () => ({ expiries }) }
      })
    )
    render(
      <IndicatorSettingsDialog
        req={req}
        symbol="CRUDEOIL19OCT26FUT"
        onApply={vi.fn()}
        onDefaults={vi.fn(async () => null)}
        onClose={vi.fn()}
      />
    )
    expect(await screen.findByText('Loading expiries...')).toBeInTheDocument()
    expect(screen.queryByText('No expiries found')).not.toBeInTheDocument()
    release()
    expect(await screen.findByText('19 Oct')).toBeInTheDocument()
    expect(asked).toEqual(['NFO', 'BFO', 'MCX'])
  })

  it('says so when the lookup fails, rather than that there are none', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, json: async () => ({}) }))
    )
    render(
      <IndicatorSettingsDialog
        req={req}
        symbol="BHEL"
        onApply={vi.fn()}
        onDefaults={vi.fn(async () => null)}
        onClose={vi.fn()}
      />
    )
    expect(
      await screen.findByText('Could not load expiries. Close and reopen to try again.')
    ).toBeInTheDocument()
  })
})
