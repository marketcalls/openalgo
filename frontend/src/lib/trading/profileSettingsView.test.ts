import { describe, expect, it } from 'vitest'
import { profileSettingsView } from './profileSettingsView'
import type { ChartSettingsRequest } from './terminal'

const base: ChartSettingsRequest = {
  tabs: [
    {
      id: 'price',
      label: 'Price',
      inputs: [
        { key: 'symbol.bodyVisible', type: 'boolean', label: 'Body', group: 'Candles' },
        { key: 'symbol.precision', type: 'select', label: 'Precision', group: 'Values' },
      ],
    },
    {
      id: 'axes',
      label: 'Axes',
      inputs: [{ key: 'axes.timezone', type: 'select', label: 'Timezone' }],
    },
  ],
  values: { 'symbol.bodyVisible': false, 'symbol.precision': -1, 'axes.timezone': 'Asia/Kolkata' },
  defaults: { 'symbol.bodyVisible': true, 'symbol.precision': -1, 'axes.timezone': 'Asia/Kolkata' },
}

describe('profile settings view', () => {
  it('replaces candles only in Price and keeps precision and other tabs', () => {
    const req = profileSettingsView(base, 'session-volume-profile', {})
    expect(req.tabs[0].inputs.some((i) => i.key === 'symbol.bodyVisible')).toBe(false)
    expect(req.tabs[0].inputs.some((i) => i.key === 'symbol.precision')).toBe(true)
    expect(req.tabs[0].inputs.some((i) => i.key.startsWith('profiles.svp.'))).toBe(true)
    expect(req.tabs[1]).toEqual(base.tabs[1])
    // Hidden candle geometry must not make an untouched profile look modified.
    expect(req.values['symbol.bodyVisible']).toBeUndefined()
    expect(req.defaults['symbol.bodyVisible']).toBeUndefined()
    expect(req.values).toEqual(req.defaults)
  })
  it('keeps another profile type out of the form and its reset patch', () => {
    const req = profileSettingsView(base, 'tpo', { 'profiles.svp.widthPercent': 25 })
    expect(Object.keys(req.values).some((k) => k.startsWith('profiles.svp.'))).toBe(false)
    expect(Object.keys(req.defaults).some((k) => k.startsWith('profiles.svp.'))).toBe(false)
    expect(req.tabs[0].inputs.some((i) => i.key.startsWith('profiles.tpo.'))).toBe(true)
  })
  it('leaves the engine schema intact for ordinary chart types', () => {
    expect(profileSettingsView(base, 'candlestick', {})).toBe(base)
    expect(profileSettingsView(base, 'line', {})).toBe(base)
  })
})
