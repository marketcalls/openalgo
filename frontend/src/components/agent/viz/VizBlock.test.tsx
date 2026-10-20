/**
 * The kind switch, and the one rule that makes it safe to deploy out of step.
 *
 * A backend that learns a fourth kind has to be able to ship before every
 * browser has the client that draws it. The first test is that case: an
 * unrecognised kind renders **nothing at all**, and in particular renders no
 * message about it. An error where an answer should be is worse than a chart
 * that is not there, and the prose the model wrote beside it still stands.
 *
 * The delegation tests deliberately assert only that the branch was taken, not
 * what the renderer drew. Each renderer owns its own spec parsing and its own
 * "nothing to draw" text; asserting that here would be a second copy of their
 * contract, and a copy drifts.
 */

import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { AgentVizItem } from '@/lib/agent/viz'
import { OPENUI_VIZ, openUiSpec } from '@/lib/agent/viz'
import { VizBlock } from './VizBlock'

// The two live cards subscribe through the shared market data manager, which
// opens a WebSocket and fetches a CSRF token. Neither exists in jsdom, and
// neither is what this file is about.
vi.mock('@/lib/MarketDataManager', () => import('@/test/marketDataHarness'))

// The instrument card mounts the live-quote layer, which reaches the shared
// WebSocket manager and the market calendar. Neither exists in jsdom, and
// neither is what this file is about: it tests that a branch was taken.
vi.mock('@/hooks/useLiveQuote', () => ({
  useLiveQuote: () => ({
    data: {},
    isLive: false,
    isConnected: false,
    isLoading: false,
    isPaused: false,
    isFallbackMode: false,
    dataSource: 'none',
    refresh: async () => {},
  }),
}))

vi.mock('@/hooks/useMarketStatus', () => ({
  useMarketStatus: () => ({
    isMarketOpen: () => false,
    isAnyMarketOpen: () => false,
    isHolidayForExchange: () => false,
    getMarketStatus: () => null,
    timings: [],
    holidays: [],
    isLoading: false,
    error: null,
  }),
}))

function item(kind: string, spec: Record<string, unknown> = {}): AgentVizItem {
  return { kind, spec, title: 'A chart', source: 'history_service', at: 0 }
}

describe('VizBlock', () => {
  beforeAll(async () => {
    // The OpenUI branch is a lazy import, and resolving it for the first time
    // pulls in the whole component library. Warming the module cache here
    // keeps that cost out of a per-test timeout.
    await import('./OpenUiViz')
  }, 30000)

  it('renders nothing, and says nothing, for a kind it does not know', () => {
    for (const kind of ['sankey', '', 'CANDLES', 'openui ', 'live', 'live_quote']) {
      const { container } = render(<VizBlock item={item(kind, { anything: true })} />)
      expect(container).toBeEmptyDOMElement()
    }
  })

  it('draws OpenUI markup through the OpenUI renderer', async () => {
    render(
      <VizBlock
        item={{
          ...item(OPENUI_VIZ),
          spec: openUiSpec('root = Card([t])\nt = TextContent("Funds available")'),
        }}
      />
    )
    // Awaited, not immediate: the OpenUI runtime is the heaviest of the three
    // and is fetched only once a turn actually composes markup, so the block
    // arrives on the chunk rather than with the page.
    expect(await screen.findByText('Funds available')).toBeInTheDocument()
  })

  it('hands a candles frame to the candle renderer', () => {
    const { container } = render(
      <VizBlock
        item={item('candles', {
          symbol: 'INFY',
          exchange: 'NSE',
          interval: 'D',
          chart_type: 'candlestick',
          bars: [{ time: 1780444800, open: 1, high: 2, low: 1, close: 2 }],
          indicators: [],
        })}
      />
    )
    expect(container).not.toBeEmptyDOMElement()
  })

  it('hands an instrument frame to the instrument card', () => {
    render(
      <VizBlock
        item={item('instrument', {
          symbol: 'RELIANCE',
          exchange: 'NSE',
          currency: 'INR',
          quote: { ltp: 1302.5, prev_close: 1313.1 },
        })}
      />
    )
    expect(screen.getByText('RELIANCE')).toBeInTheDocument()
  })

  it('hands a live quotes frame to the live quotes card', () => {
    render(
      <VizBlock
        item={item('live_quotes', {
          mode: 'LTP',
          instruments: [
            {
              symbol: 'RELIANCE',
              exchange: 'NSE',
              calendar_exchange: 'NSE',
              seed: { ltp: 1302.5 },
            },
          ],
          subscribe: [{ symbol: 'RELIANCE', exchange: 'NSE' }],
          market: { known: false, exchanges: [] },
        })}
      />
    )
    expect(screen.getByText('RELIANCE')).toBeInTheDocument()
  })

  it('hands a live combo frame to the live combo card', () => {
    render(
      <VizBlock
        item={item('live_combo', {
          structure: 'straddle',
          label: 'NIFTY 08SEP26 23850 straddle',
          legs: [
            {
              symbol: 'NIFTY08SEP2623850CE',
              exchange: 'NFO',
              multiplier: 1,
              side: 'BUY',
              seed: { ltp: 120.5 },
            },
          ],
          formula: { kind: 'signed_sum', constant: null, per: 'unit', expression: '' },
          subscribe: [{ symbol: 'NIFTY08SEP2623850CE', exchange: 'NFO' }],
          market: { known: false, exchanges: [] },
        })}
      />
    )
    expect(screen.getByText('NIFTY 08SEP26 23850 straddle')).toBeInTheDocument()
  })

  it('hands a plotly frame to the plotly renderer', () => {
    const { container } = render(
      <VizBlock
        item={item('plotly', {
          engine: '2d',
          data: [{ type: 'bar', x: [1, 2], y: [3, 4] }],
          layout: {},
          config: {},
        })}
      />
    )
    expect(container).not.toBeEmptyDOMElement()
  })
})
