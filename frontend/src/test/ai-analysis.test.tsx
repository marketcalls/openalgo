// frontend/src/test/ai-analysis.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@/test/test-utils'
import { SignalBadge } from '@/components/ai-analysis/SignalBadge'
import { ConfidenceGauge } from '@/components/ai-analysis/ConfidenceGauge'
import { SubScoresChart } from '@/components/ai-analysis/SubScoresChart'
import { IndicatorTable } from '@/components/ai-analysis/IndicatorTable'
import { ScanResultsTable } from '@/components/ai-analysis/ScanResultsTable'

describe('SignalBadge', () => {
  it('renders BUY signal', () => {
    render(<SignalBadge signal="BUY" />)
    expect(screen.getByText('Buy')).toBeInTheDocument()
  })

  it('renders STRONG_SELL signal', () => {
    render(<SignalBadge signal="STRONG_SELL" />)
    expect(screen.getByText('Strong Sell')).toBeInTheDocument()
  })

  it('renders HOLD signal', () => {
    render(<SignalBadge signal="HOLD" />)
    expect(screen.getByText('Hold')).toBeInTheDocument()
  })
})

describe('ConfidenceGauge', () => {
  it('renders confidence value', () => {
    render(<ConfidenceGauge confidence={75.5} />)
    expect(screen.getByText('75.5%')).toBeInTheDocument()
  })

  it('renders zero confidence', () => {
    render(<ConfidenceGauge confidence={0} />)
    expect(screen.getByText('0%')).toBeInTheDocument()
  })
})

describe('SubScoresChart', () => {
  it('renders all sub-scores', () => {
    render(<SubScoresChart scores={{ rsi: 0.3, macd: -0.5, supertrend: 0.8 }} />)
    expect(screen.getByText('RSI')).toBeInTheDocument()
    expect(screen.getByText('MACD')).toBeInTheDocument()
    expect(screen.getByText('Supertrend')).toBeInTheDocument()
  })

  it('renders empty state', () => {
    render(<SubScoresChart scores={{}} />)
    expect(screen.getByText(/no signals/i)).toBeInTheDocument()
  })
})

describe('IndicatorTable', () => {
  it('renders indicator values', () => {
    render(<IndicatorTable indicators={{ rsi_14: 42.5, macd: 1.23 }} />)
    expect(screen.getByText('RSI (14)')).toBeInTheDocument()
    expect(screen.getByText('42.50')).toBeInTheDocument()
  })
})

describe('ScanResultsTable', () => {
  it('renders scan results', () => {
    render(
      <ScanResultsTable
        results={[
          { symbol: 'RELIANCE', signal: 'BUY', confidence: 75, score: 0.35, regime: 'TRENDING_UP', error: null },
          { symbol: 'SBIN', signal: 'SELL', confidence: 60, score: -0.28, regime: 'TRENDING_DOWN', error: null },
        ]}
      />,
    )
    expect(screen.getByText('RELIANCE')).toBeInTheDocument()
    expect(screen.getByText('SBIN')).toBeInTheDocument()
  })

  it('renders empty state', () => {
    render(<ScanResultsTable results={[]} />)
    expect(screen.getByText(/no results/i)).toBeInTheDocument()
  })
})
