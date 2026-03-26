// frontend/src/test/advanced-signals-panel.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@/test/test-utils'
import { AdvancedSignalsPanel } from '@/components/ai-analysis/AdvancedSignalsPanel'

const mockAdvanced = {
  smc: { smc_fvg_bullish: true, smc_bos_bearish: true },
  candlestick: ['doji', 'engulfing_bull', 'hammer'],
  cpr: { pivot: 2450.5, r1: 2465.0, s1: 2435.0 },
  fibonacci: { long: 1, short: 0 },
  harmonic: { bullish: 1, bearish: 0 },
  divergence: { rsi_bullish: 0, rsi_bearish: 1 },
  volume: { exhaustion: 1, vwap_bb_confluence: 0 },
  ml_confidence: { buy: 72.5, sell: 28.3 },
}

describe('AdvancedSignalsPanel', () => {
  it('renders SMC alerts', () => {
    render(<AdvancedSignalsPanel signals={mockAdvanced} />)
    expect(screen.getByText(/FVG Bullish/i)).toBeInTheDocument()
    expect(screen.getByText(/BOS Bearish/i)).toBeInTheDocument()
  })

  it('renders candlestick patterns', () => {
    render(<AdvancedSignalsPanel signals={mockAdvanced} />)
    expect(screen.getByText(/doji/i)).toBeInTheDocument()
    expect(screen.getByText(/hammer/i)).toBeInTheDocument()
  })

  it('renders harmonic detection', () => {
    render(<AdvancedSignalsPanel signals={mockAdvanced} />)
    expect(screen.getByText(/Harmonic/i)).toBeInTheDocument()
  })

  it('renders empty state', () => {
    const empty = {
      smc: {}, candlestick: [], cpr: {},
      fibonacci: { long: 0, short: 0 }, harmonic: { bullish: 0, bearish: 0 },
      divergence: { rsi_bullish: 0, rsi_bearish: 0 },
      volume: { exhaustion: 0, vwap_bb_confluence: 0 },
      ml_confidence: { buy: 0, sell: 0 },
    }
    render(<AdvancedSignalsPanel signals={empty} />)
    expect(screen.getByText(/no patterns/i)).toBeInTheDocument()
  })
})
