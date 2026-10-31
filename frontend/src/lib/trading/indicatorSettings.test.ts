import { describe, expect, it, vi } from 'vitest'
import {
  applyIndicatorSettings,
  buildIndicatorSettingsRequest,
  indicatorDefaultsFor,
  toField,
} from './indicatorSettings'

describe('indicatorSettings', () => {
  it('toField maps indicator field properties correctly', () => {
    const field = toField({
      key: 'length',
      type: 'number',
      label: 'Length',
      group: 'Settings',
    })
    expect(field).toEqual({
      key: 'length',
      type: 'number',
      label: 'Length',
      group: 'Settings',
      tooltip: undefined,
      options: undefined,
      min: undefined,
      max: undefined,
      step: undefined,
      visibleWhen: undefined,
    })
  })

  it('buildIndicatorSettingsRequest returns null when instance is not found', async () => {
    const mockChart = {
      indicators: () => [],
    }
    const result = await buildIndicatorSettingsRequest(mockChart, 'nonexistent')
    expect(result).toBeNull()
  })

  it('buildIndicatorSettingsRequest builds request for registered indicator', async () => {
    // RSI is a built-in indicator
    await import('openalgo-charts/indicators')
    const mockInst = {
      id: 'rsi-1',
      name: 'Relative Strength Index (14, close)',
      indicatorId: 'rsi',
      settings: () => ({ length: 14, source: 'close' }),
      barSource: () => 'chart' as const,
      setSettings: vi.fn(),
      setBarSource: vi.fn(),
    }
    const mockChart = {
      indicators: () => [mockInst],
    }
    const result = await buildIndicatorSettingsRequest(mockChart, 'rsi-1')
    expect(result).not.toBeNull()
    expect(result?.instanceId).toBe('rsi-1')
    expect(result?.name).toBe('Relative Strength Index (14, close)')
    expect(result?.values).toEqual({ length: 14, source: 'close' })
    expect(result?.inputs.length).toBeGreaterThan(0)
    expect(result?.styleInputs.length).toBeGreaterThan(0)
  })

  it('indicatorDefaultsFor returns descriptor defaults', async () => {
    await import('openalgo-charts/indicators')
    const mockInst = {
      id: 'rsi-1',
      name: 'RSI',
      indicatorId: 'rsi',
      settings: () => ({}),
      barSource: () => 'chart' as const,
    }
    const mockChart = {
      indicators: () => [mockInst],
    }
    const defaults = await indicatorDefaultsFor(mockChart, 'rsi-1')
    expect(defaults).not.toBeNull()
    expect(defaults?.length).toBe(14)
  })

  it('applyIndicatorSettings updates settings and barSource', () => {
    const setSettings = vi.fn()
    const setBarSource = vi.fn()
    const mockInst = {
      id: 'rsi-1',
      name: 'RSI',
      indicatorId: 'rsi',
      settings: () => ({ length: 14 }),
      barSource: () => 'chart' as const,
      setSettings,
      setBarSource,
    }
    const mockChart = {
      indicators: () => [mockInst],
    }
    applyIndicatorSettings(mockChart, 'rsi-1', { length: 21 }, 'underlying')
    expect(setBarSource).toHaveBeenCalledWith('underlying')
    expect(setSettings).toHaveBeenCalledWith({ length: 21 })
  })
})
