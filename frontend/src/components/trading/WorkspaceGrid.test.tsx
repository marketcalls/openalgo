import type { ComponentProps } from 'react'
import { useEffect } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LAYOUTS } from '@/lib/chart/layouts'
import { PreparedChartGrid } from '@/lib/trading/preparedGrid'
import type { TradingTerminal } from '@/lib/trading/terminal'
import { capturePresetWorkspace } from '@/lib/trading/workspaceGrid'
import { cleanup, render } from '@/test/test-utils'
import type { ChartPane } from './ChartPane'
import { WorkspaceGrid } from './WorkspaceGrid'

const fake = vi.hoisted(() => ({
  mounts: vi.fn(),
  props: new Map<string, ComponentProps<typeof ChartPane>>(),
}))
vi.mock('./ChartPane', () => ({
  ChartPane: (props: ComponentProps<typeof ChartPane>) => {
    fake.props.set(props.paneId, props)
    useEffect(() => {
      fake.mounts(props.paneId)
    }, [props.paneId])
    return <div data-testid={props.paneId} style={props.style} />
  },
}))
function grid() {
  return new PreparedChartGrid(
    capturePresetWorkspace(
      LAYOUTS[1],
      ['left', 'right'].map((id) => ({
        id,
        symbol: 'BHEL',
        exchange: 'NSE',
        interval: '5m',
        chartType: 'candlestick',
        chart: { version: 1 },
        settings: {},
        volume: true,
        magnet: 'weak',
        stay: true,
        comparisons: [],
        comparisonMode: 'price',
      })),
      'right',
      { crosshair: true, viewport: true, symbol: false, interval: false }
    )
  )
}
afterEach(() => {
  cleanup()
  fake.props.clear()
  fake.mounts.mockClear()
})

describe('staged workspace grid', () => {
  it('rejects replay callbacks from hidden or outgoing grid controls', () => {
    const owner = grid(),
      start = vi.fn()
    const props = { owner, apiKey: 'fixture', wsUrl: 'ws://fixture.invalid', onReplayStart: start }
    const view = render(<WorkspaceGrid {...props} active={false} />)
    const stale = fake.props.get('right')!.onReplayStart
    stale?.('right')
    expect(start).not.toHaveBeenCalled()
    view.rerender(<WorkspaceGrid {...props} active />)
    stale?.('right')
    expect(start).toHaveBeenCalledExactlyOnceWith('right')
    view.rerender(<WorkspaceGrid {...props} active transitionLocked />)
    stale?.('right')
    expect(start).toHaveBeenCalledOnce()
    owner.destroy()
  })

  it('publishes controls only for the selected pane in the active grid', () => {
    const owner = grid()
    const host = document.createElement('div')
    const props = { owner, apiKey: 'fixture', wsUrl: 'ws://fixture.invalid', toolbarHost: host }
    const view = render(<WorkspaceGrid {...props} active={false} focusedPaneId="right" />)
    expect(fake.props.get('right')).toMatchObject({ focused: false, toolbarHost: host })
    expect(fake.props.get('left')).toMatchObject({ focused: false, toolbarHost: host })
    view.rerender(<WorkspaceGrid {...props} active focusedPaneId="right" />)
    expect(fake.props.get('right')).toMatchObject({ focused: true, paneLabel: 'Chart 2' })
    expect(fake.props.get('left')).toMatchObject({ focused: false })
    view.rerender(<WorkspaceGrid {...props} active focusedPaneId="left" />)
    expect(fake.props.get('right')).toMatchObject({ focused: false })
    expect(fake.props.get('left')).toMatchObject({ focused: true })
    expect(fake.mounts).toHaveBeenCalledTimes(2)
    owner.destroy()
  })

  it('keeps staging measurable and inert, then publishes the same pane instances', () => {
    const owner = grid()
    const { container, rerender } = render(
      <WorkspaceGrid
        owner={owner}
        active={false}
        apiKey="fixture"
        wsUrl="ws://fixture.invalid"
        armed
      />
    )
    const element = container.firstElementChild as HTMLElement
    expect(element.style.display).not.toBe('none')
    expect(element.style.visibility).toBe('hidden')
    expect(element.hasAttribute('inert')).toBe(true)
    expect(fake.props.get('left')).toMatchObject({
      transitionLocked: true,
      armed: false,
      initialWorkspacePane: { magnet: 'weak', stay: true },
    })
    rerender(
      <WorkspaceGrid
        owner={owner}
        active
        apiKey="fixture"
        wsUrl="ws://fixture.invalid"
        armed={false}
      />
    )
    expect(container.firstElementChild).toBe(element)
    expect(element.hasAttribute('inert')).toBe(false)
    expect(element.style.visibility).not.toBe('hidden')
    expect(fake.mounts).toHaveBeenCalledTimes(2)
    expect(fake.props.get('left')).toMatchObject({ transitionLocked: false, armed: false })
    owner.destroy()
  })

  it('keeps staging callbacks out of the active registry while still collecting readiness', async () => {
    const owner = grid(),
      changed = vi.fn(),
      initialized = vi.fn()
    render(
      <WorkspaceGrid
        owner={owner}
        active={false}
        apiKey="fixture"
        wsUrl="ws://fixture.invalid"
        onTerminalChange={changed}
        onSymbolChange={changed}
        onObjectsChange={changed}
        onFocusPane={changed}
      />
    )
    void owner.ready.then(initialized)
    for (const id of ['left', 'right']) {
      const terminal = {
        setWorkspaceTransitionLocked: vi.fn(),
        setArmed: vi.fn(),
        destroy: vi.fn(),
      } as unknown as TradingTerminal
      const props = fake.props.get(id)!
      props.onTerminalChange?.(id, terminal)
      props.onSymbolChange?.(id, 'NSE:BHEL')
      props.onObjectsChange?.(id, null)
      props.onFocusPane?.(terminal, id)
      props.onInitialized?.(id, terminal)
    }
    await owner.ready
    expect(initialized).toHaveBeenCalledOnce()
    expect(changed).not.toHaveBeenCalled()
    owner.destroy()
  })
})
