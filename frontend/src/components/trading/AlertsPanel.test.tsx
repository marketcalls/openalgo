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

function viewOf(alerts: Alert[]) {
  const controller = {
    list: vi.fn(() => alerts.map((one) => ({ ...one }))),
    remove: vi.fn(),
    enable: vi.fn(),
    disable: vi.fn(),
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

  it('opens the editor on nothing in particular from New', async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn()
    const { view } = viewOf([])
    render(<AlertsPanel {...props} view={view} onEdit={onEdit} />)
    await user.click(screen.getByRole('button', { name: 'New' }))
    expect(onEdit).toHaveBeenCalledWith()
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

  it('says the log is the session’s rather than implying one was lost', async () => {
    const user = userEvent.setup()
    const { view } = viewOf([alert()])
    render(<AlertsPanel {...props} view={view} />)
    await user.click(screen.getByRole('tab', { name: /^Log/ }))
    expect(screen.getByText(/covers the current session/)).toBeInTheDocument()
  })
})
