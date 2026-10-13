/**
 * The equity and drawdown charts build on the real charting engine.
 *
 * BacktestChart catches any error while building, so a wrong series type or
 * style key would leave an empty box and no message. A failed build destroys
 * the chart and its canvas, so a canvas still in place is the proof it drew.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@/test/test-utils'
import { BacktestChart } from './BacktestChart'

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

const points = [0, 1, 2, 3].map((minute) => ({
  time: Date.UTC(2026, 8, 15, 9, minute),
  equity: 100000 + [0, -500, 300, 800][minute],
  drawdown: [0, -500, -200, 0][minute],
}))

describe('BacktestChart on the real engine', () => {
  it.each(['equity', 'drawdown'] as const)('draws the %s curve', async (show) => {
    const { container } = render(<BacktestChart points={points} show={show} />)
    await waitFor(() => expect(container.querySelector('canvas')).not.toBeNull())
    // Still there after the build settled: the catch would have destroyed it.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(container.querySelector('canvas')).not.toBeNull()
  })
})
