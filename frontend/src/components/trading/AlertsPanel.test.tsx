import type { Alert } from 'openalgo-charts'
import { describe, expect, it, vi } from 'vitest'
import type { AlertFire, AlertsView } from '@/lib/trading/terminal'
import { render, screen, userEvent, within } from '@/test/test-utils'
import { AlertsPanel } from './AlertsPanel'

const alert = (patch: Partial<Alert> = {}): Alert =>
  ({
    id: 'a1',
    source: { kind: 'price', price: 1243.4, paneIndex: 0 },
    condition: 'crossingUp',
    policy: 'onBarClose',
    repeat: 'once',
    state: 'armed',
    title: 'RELIANCE crossing up 1243.4',
    cooldownSeconds: 0,
    scope: { symbol: 'RELIANCE', exchange: 'NSE', interval: '5m' },
    ...patch,
  }) as Alert

function viewOf(
  alerts: Alert[],
  availability: Record<string, { available: boolean; reason?: string }> = {}
) {
  const controller = {
    list: vi.fn(() => alerts.map((one) => ({ ...one }))),
    remove: vi.fn(),
    enable: vi.fn(),
    disable: vi.fn(),
    availability: vi.fn((id: string) => availability[id] ?? { available: true }),
  }
  return {
    view: {
      alerts: controller,
      chart: { timezone: () => 'Asia/Kolkata' },
    } as unknown as AlertsView,
    controller,
  }
}

const fire = (patch: Partial<AlertFire> = {}): AlertFire => ({
  key: 'a1-1',
  alertId: 'a1',
  title: 'RELIANCE crossing up 1243.4',
  message: 'Crossed on the close',
  symbol: 'RELIANCE',
  exchange: 'NSE',
  firedAt: 1_700_000_000,
  ...patch,
})

const props = {
  log: [] as readonly AlertFire[],
  paneLabel: 'Pane 1 · RELIANCE',
  onEdit: () => {},
  onClearLog: () => {},
  revision: 0,
}

describe('the alert list on the rail', () => {
  it('shows what each alert is waiting for, not just its name', () => {
    // The name is fixed when the alert is made and a drag moves the price
    // without touching it, so the row reads the level off the alert itself.
    const { view } = viewOf([
      alert({ title: 'Renamed by hand', source: { kind: 'price', price: 1290.55, paneIndex: 0 } }),
    ])
    render(<AlertsPanel {...props} view={view} />)
    expect(screen.getByText('Crossing up 1290.55')).toBeInTheDocument()
  })

  it('prefers the trader’s own message over the condition', () => {
    const { view } = viewOf([alert({ message: 'Take the second lot off' })])
    render(<AlertsPanel {...props} view={view} />)
    expect(screen.getByText('Take the second lot off')).toBeInTheDocument()
    expect(screen.queryByText(/Crossing up/)).not.toBeInTheDocument()
  })

  it('says Active rather than the engine’s state name', () => {
    // Reported as reading "armed", which is not a word a trader uses about an
    // alert they have just set.
    const { view } = viewOf([alert()])
    render(<AlertsPanel {...props} view={view} />)
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.queryByText('armed')).not.toBeInTheDocument()
  })

  // Named so the two orders disagree: by state the armed Zebra leads, by name
  // the stopped Apple does. A pair that sorts the same either way would let a
  // sort control that did nothing at all pass both of the tests below.
  const disagreeing = () => [
    alert({ id: 'off', title: 'Apple stopped', state: 'disabled' }),
    alert({ id: 'on', title: 'Zebra watching', state: 'armed' }),
  ]
  const titlesOnScreen = () =>
    screen.getAllByText(/Apple stopped|Zebra watching/).map((node) => node.textContent)

  it('puts the alerts still watching above the ones that are not', () => {
    const { view } = viewOf(disagreeing())
    render(<AlertsPanel {...props} view={view} />)
    expect(titlesOnScreen()).toEqual(['Zebra watching', 'Apple stopped'])
  })

  it('sorts by name when asked, which reverses that order', async () => {
    const user = userEvent.setup()
    const { view } = viewOf(disagreeing())
    render(<AlertsPanel {...props} view={view} />)
    await user.selectOptions(screen.getByLabelText('Sort alerts'), 'name')
    expect(titlesOnScreen()).toEqual(['Apple stopped', 'Zebra watching'])
  })

  it('sorts by what fired most recently, which is a third order again', async () => {
    const user = userEvent.setup()
    const { view } = viewOf([
      alert({ id: 'old', title: 'Apple stopped', state: 'disabled', lastTriggeredAt: 200 }),
      alert({ id: 'new', title: 'Zebra watching', state: 'armed', lastTriggeredAt: 100 }),
    ])
    render(<AlertsPanel {...props} view={view} />)
    await user.selectOptions(screen.getByLabelText('Sort alerts'), 'recent')
    expect(titlesOnScreen()).toEqual(['Apple stopped', 'Zebra watching'])
  })

  it('searches the message and the symbol, not only the name', async () => {
    const user = userEvent.setup()
    const { view } = viewOf([
      alert({ id: 'a', title: 'One', message: 'sell the strangle' }),
      alert({ id: 'b', title: 'Two', message: 'nothing to do' }),
    ])
    render(<AlertsPanel {...props} view={view} />)
    await user.type(screen.getByLabelText('Search alerts'), 'strangle')
    expect(screen.getByText('sell the strangle')).toBeInTheDocument()
    expect(screen.queryByText('nothing to do')).not.toBeInTheDocument()
  })

  it('stops an alert that is running and starts one that is not', async () => {
    const user = userEvent.setup()
    const { view, controller } = viewOf([alert({ title: 'Watching' })])
    render(<AlertsPanel {...props} view={view} />)
    await user.click(screen.getByLabelText('Stop Watching'))
    expect(controller.disable).toHaveBeenCalledWith('a1')
    expect(controller.enable).not.toHaveBeenCalled()
  })

  it('offers Start on a stopped alert', async () => {
    const user = userEvent.setup()
    const { view, controller } = viewOf([alert({ title: 'Stopped', state: 'disabled' })])
    render(<AlertsPanel {...props} view={view} />)
    await user.click(screen.getByLabelText('Start Stopped'))
    expect(controller.enable).toHaveBeenCalledWith('a1')
  })

  it('opens the editor on the row that was clicked', async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn()
    const { view } = viewOf([alert({ id: 'pick-me', title: 'Pick me' })])
    render(<AlertsPanel {...props} view={view} onEdit={onEdit} />)
    await user.click(screen.getByLabelText('Edit Pick me'))
    expect(onEdit).toHaveBeenCalledWith('pick-me')
  })

  it('offers no way to create an alert, because the chart is where that happens', async () => {
    // An alert is made where the price is, by right-clicking the chart at it. A
    // button here would open the form on the last close and ask the trader to
    // type a number they could have pointed at.
    const { view } = viewOf([alert()])
    render(<AlertsPanel {...props} view={view} />)
    expect(screen.queryByRole('button', { name: 'New' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /create/i })).not.toBeInTheDocument()
  })

  it('says where an alert comes from when there are none', async () => {
    // The empty state is the one place a trader is actually looking for the way
    // in, so it names the gesture rather than describing what an alert is.
    const { view } = viewOf([])
    render(<AlertsPanel {...props} view={view} />)
    expect(
      screen.getByText(/Right-click the chart at a price to set one there and then/)
    ).toBeInTheDocument()
  })

  it('waits rather than claiming there are no alerts before a chart is ready', () => {
    render(<AlertsPanel {...props} view={null} />)
    expect(screen.queryByText(/No alerts on this chart yet/)).not.toBeInTheDocument()
  })

  it('distinguishes an empty list from a search that matched nothing', async () => {
    const user = userEvent.setup()
    const { view } = viewOf([alert({ title: 'Something' })])
    render(<AlertsPanel {...props} view={view} />)
    await user.type(screen.getByLabelText('Search alerts'), 'zzz')
    expect(screen.getByText('No alert matches that search.')).toBeInTheDocument()
  })
})

describe('the log of what has fired', () => {
  it('counts the firings on its tab', () => {
    const { view } = viewOf([alert()])
    render(<AlertsPanel {...props} view={view} log={[fire(), fire({ key: 'a1-2' })]} />)
    const tab = screen.getByRole('tab', { name: /^Log/ })
    expect(within(tab).getByText('2')).toBeInTheDocument()
  })

  it('says why an alert that reads Active is not watching right now', async () => {
    // Since charts 2.5.0 an alert stays visible on other timeframes but is
    // evaluated only on the one it was made on. Without the reason the row
    // reads Active on a chart where nothing can fire, which looks like a bug in
    // the alert rather than a fact about the chart.
    const { view } = viewOf([alert()], {
      a1: { available: false, reason: 'Paused: created on 5m' },
    })
    render(<AlertsPanel {...props} view={view} />)
    expect(screen.getByText('Paused: created on 5m')).toBeInTheDocument()
  })

  it('says nothing extra about an alert that is watching', async () => {
    // With a reason attached, because the engine may describe an alert it is
    // still evaluating. `available` is the field that decides whether the
    // trader needs telling; printing any reason it finds would put a warning
    // on a row where nothing is wrong.
    const { view } = viewOf([alert()], {
      a1: { available: true, reason: 'Evaluating on 5m' },
    })
    render(<AlertsPanel {...props} view={view} />)
    expect(screen.queryByText('Evaluating on 5m')).not.toBeInTheDocument()
  })

  it('does not repeat itself on an alert that is already stopped', async () => {
    // A stopped alert says so in its own state. A second line saying it is not
    // watching reads as two different problems.
    const { view } = viewOf([alert({ state: 'disabled' })], {
      a1: { available: false, reason: 'Paused: created on 5m' },
    })
    render(<AlertsPanel {...props} view={view} />)
    expect(screen.queryByText('Paused: created on 5m')).not.toBeInTheDocument()
  })

  it('renders the list when the engine cannot answer about availability', async () => {
    const { view } = viewOf([alert()])
    ;(view.alerts as unknown as { availability: () => never }).availability = () => {
      throw new Error('mid-teardown')
    }
    render(<AlertsPanel {...props} view={view} />)
    expect(screen.getByText('RELIANCE crossing up 1243.4')).toBeInTheDocument()
  })

  it('shows the newest firing first', async () => {
    const user = userEvent.setup()
    const { view } = viewOf([alert()])
    render(
      <AlertsPanel
        {...props}
        view={view}
        log={[fire({ key: '1', title: 'First' }), fire({ key: '2', title: 'Second' })]}
      />
    )
    await user.click(screen.getByRole('tab', { name: /^Log/ }))
    const titles = screen.getAllByText(/^First$|^Second$/).map((node) => node.textContent)
    expect(titles).toEqual(['Second', 'First'])
  })

  it('carries the price that met the condition', async () => {
    const user = userEvent.setup()
    const { view } = viewOf([alert()])
    render(<AlertsPanel {...props} view={view} log={[fire({ price: 1243.45 })]} />)
    await user.click(screen.getByRole('tab', { name: /^Log/ }))
    expect(screen.getByText('at 1243.45')).toBeInTheDocument()
  })

  it('clears the log from the tab that shows it', async () => {
    const user = userEvent.setup()
    const onClearLog = vi.fn()
    const { view } = viewOf([alert()])
    render(<AlertsPanel {...props} view={view} log={[fire()]} onClearLog={onClearLog} />)
    await user.click(screen.getByRole('tab', { name: /^Log/ }))
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(onClearLog).toHaveBeenCalled()
  })

  it('offers nothing to clear on the tab that is not the log', async () => {
    // It empties the list on screen, so on the alerts tab it would be an
    // action pointing at something the trader is not looking at.
    const { view } = viewOf([alert()])
    render(<AlertsPanel {...props} view={view} log={[fire()]} />)
    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument()
  })

  it('shows Clear greyed rather than absent when nothing has fired', async () => {
    // Hidden until there is something to clear, a trader looking for it finds
    // an empty panel and no sign the action exists at all.
    const user = userEvent.setup()
    const { view } = viewOf([alert()])
    render(<AlertsPanel {...props} view={view} />)
    await user.click(screen.getByRole('tab', { name: /^Log/ }))
    expect(screen.getByRole('button', { name: 'Clear' })).toBeDisabled()
  })

  it('says an alert only fires while the chart is open, and that firings are kept', async () => {
    // Both halves matter and they are easy to confuse. The limit is on when an
    // alert can fire, not on how long the record of it survives, and an empty
    // Log tab that implies the second would have a trader believe the platform
    // threw their history away.
    const user = userEvent.setup()
    const { view } = viewOf([alert()])
    render(<AlertsPanel {...props} view={view} />)
    await user.click(screen.getByRole('tab', { name: /^Log/ }))

    const empty = screen.getByText(/Nothing has fired yet/)
    expect(empty).toHaveTextContent(/only fires while/i)
    expect(empty).toHaveTextContent(/kept here afterwards/i)
  })

  it('shows which channels took a firing', async () => {
    const user = userEvent.setup()
    const { view } = viewOf([alert()])
    render(
      <AlertsPanel
        {...props}
        view={view}
        log={[
          {
            key: 'log-1',
            alertId: 'a1',
            title: 'RELIANCE crossing 1264.7',
            message: 'crossed 1264.70',
            symbol: 'RELIANCE',
            exchange: 'NSE',
            firedAt: 1_758_441_600,
            delivered: ['sound', 'telegram'],
          },
        ]}
      />
    )
    await user.click(screen.getByRole('tab', { name: /^Log/ }))

    expect(screen.getByText('sound')).toBeInTheDocument()
    expect(screen.getByText('telegram')).toBeInTheDocument()
  })

  it('shows no channel at all for a firing that reached nobody', async () => {
    // The absence is the answer. A "none" badge reads like a delivery failure
    // on an alert the trader deliberately left silent.
    const user = userEvent.setup()
    const { view } = viewOf([alert()])
    render(
      <AlertsPanel
        {...props}
        view={view}
        log={[
          {
            key: 'log-1',
            alertId: 'a1',
            title: 'RELIANCE crossing 1264.7',
            message: '',
            symbol: 'RELIANCE',
            exchange: 'NSE',
            firedAt: 1_758_441_600,
            delivered: [],
          },
        ]}
      />
    )
    await user.click(screen.getByRole('tab', { name: /^Log/ }))

    expect(screen.getByText('RELIANCE crossing 1264.7')).toBeInTheDocument()
    expect(screen.queryByText(/none/i)).not.toBeInTheDocument()
  })
})
