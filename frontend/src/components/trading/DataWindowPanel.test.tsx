import { type Bar, createChart } from 'openalgo-charts'
import { Profiler } from 'react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@/test/test-utils'
import { DataWindowPanel } from './DataWindowPanel'

const bar = (time: number, close: number): Bar => ({
  time,
  open: close - 1,
  high: close + 2,
  low: close - 3,
  close,
  volume: 1000 + close,
})
const T = Date.UTC(2026, 9, 1, 3, 45) / 1000

beforeAll(async () => {
  await import('openalgo-charts/indicators')
})
beforeEach(() => {
  const context = new Proxy(
    {
      measureText: (text: string) => ({ width: text.length * 7 }),
      createLinearGradient: () => ({ addColorStop() {} }),
      getImageData: () => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) }),
    },
    { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) }
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D
  )
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function chart(closes: number[]) {
  const made = createChart(document.createElement('div'), {
    shortcuts: false,
    timeNavigator: false,
    raf: {
      schedule: (cb) => {
        cb()
        return 1
      },
      cancel() {},
    },
  })
  made.applySize(800, 600)
  made.setDataContext({ symbol: 'SBIN', exchange: 'NSE', interval: '5m' })
  made.addSeries('candlestick').setData(closes.map((close, i) => bar(T + i * 300, close)))
  return made
}

const value = (key: string) =>
  Number(
    document
      .querySelector(`[data-key="${key}"] .oac-data-window__value`)
      ?.textContent?.replace(/,/g, '')
  )

describe('data window panel', () => {
  it('reads the bar and every study for the chart it is given', async () => {
    const live = chart([100, 101, 102, 103, 104, 105])
    const sma = live.addIndicator('sma', { length: 3 })
    render(<DataWindowPanel chart={live} paneLabel="Pane 1 · NSE:SBIN" />)
    expect(screen.getByRole('complementary', { name: 'Data window' })).toBeVisible()
    expect(screen.getByText('NSE:SBIN')).toBeVisible()
    // With no crosshair the latest bar is read.
    expect(value('close')).toBe(105)
    expect(value('volume')).toBe(1105)
    await vi.waitFor(() =>
      expect(document.querySelector(`[data-key^="${sma.id}:"]`)).not.toBeNull()
    )
    live.destroy()
  })

  it('follows the crosshair without a React render, and moves to a rebuilt chart', async () => {
    const first = chart([100, 101, 102])
    const renders = vi.fn()
    const panel = (target: ReturnType<typeof chart>) => (
      <Profiler id="data" onRender={renders}>
        <DataWindowPanel chart={target} paneLabel="Pane 1" />
      </Profiler>
    )
    const view = render(panel(first))
    const before = renders.mock.calls.length
    first.emit('crosshair:readout', { index: 0, point: { x: 1, y: 1 }, time: T })
    await vi.waitFor(() => expect(value('close')).toBe(100))
    first.emit('crosshair:readout', { index: 1, point: { x: 2, y: 1 }, time: T + 300 })
    await vi.waitFor(() => expect(value('close')).toBe(101))
    expect(renders).toHaveBeenCalledTimes(before)

    const second = chart([200, 201])
    view.rerender(panel(second))
    expect(value('close')).toBe(201)
    first.destroy()
    second.destroy()
    // The panel empties with its chart rather than showing a dead one.
    expect(document.querySelector('[data-data-window]')?.textContent).toBe('')
  })

  it('asks for a chart when the pane has none', () => {
    render(<DataWindowPanel chart={null} paneLabel="Pane 2" />)
    expect(screen.getByText('Load a chart in this pane to read its values here.')).toBeVisible()
  })
})
