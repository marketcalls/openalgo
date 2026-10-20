import type { Alert } from 'openalgo-charts'
import { describe, expect, it, vi } from 'vitest'
import { AUTO_TITLE_PAYLOAD } from '@/lib/trading/alertsModel'
import type { AlertsHandle } from '@/lib/trading/terminal'
import { render, screen, userEvent } from '@/test/test-utils'
import { AlertsDialog } from './AlertsDialog'

const existing = (patch: Partial<Alert> = {}): Alert =>
  ({
    id: 'a1',
    source: { kind: 'price', price: 1266.8 },
    condition: 'crossing',
    policy: 'onBarClose',
    repeat: 'once',
    state: 'armed',
    title: 'RELIANCE crossing 1266.8',
    cooldownSeconds: 0,
    scope: { symbol: 'RELIANCE', exchange: 'NSE', interval: '1h' },
    payload: AUTO_TITLE_PAYLOAD,
    ...patch,
  }) as Alert

function handleOf(alerts: Alert[], editAlertId?: string) {
  const controller = {
    list: vi.fn(() => alerts.map((one) => ({ ...one }))),
    add: vi.fn((input) => ({ ...input, id: 'new' })),
    update: vi.fn((id, patch) => ({ ...patch, id })),
    remove: vi.fn(),
  }
  const handle = {
    alerts: controller,
    chart: {
      indicators: () => [],
      primaryBars: () => [{ close: 1246.5 }],
      timezone: () => 'Asia/Kolkata',
    },
    drawings: null,
    symbol: 'RELIANCE',
    at: { tick: 0.05, refPrice: 1246.5 },
    ...(editAlertId ? { editAlertId } : {}),
  } as unknown as AlertsHandle
  return { handle, controller }
}

const noop = () => {}

describe('the alert editor', () => {
  it('opens on the alert it was sent to, not on a list', () => {
    const { handle } = handleOf([existing()], 'a1')
    render(<AlertsDialog handle={handle} onClose={noop} />)
    expect(screen.getByText('Edit alert')).toBeInTheDocument()
    expect(screen.getByLabelText('Value')).toHaveValue('1266.8')
  })

  it('creates rather than edits when it was sent no alert', () => {
    const { handle } = handleOf([existing()])
    render(<AlertsDialog handle={handle} onClose={noop} />)
    expect(screen.getByText('Create alert')).toBeInTheDocument()
  })

  it('saves an edit onto the alert it opened, and adds nothing', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const { handle, controller } = handleOf([existing()], 'a1')
    render(<AlertsDialog handle={handle} onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(controller.update).toHaveBeenCalledWith('a1', expect.anything())
    expect(controller.add).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('leaves a name we wrote blank, so a later drag can still rewrite it', () => {
    // The field shows the generated name as its placeholder, so nothing looks
    // missing. Filling it in would make the name the trader's the moment they
    // pressed Save, and freeze it to a price the line may since have left.
    const { handle } = handleOf([existing()], 'a1')
    render(<AlertsDialog handle={handle} onClose={noop} />)
    const name = screen.getByLabelText('Alert name')
    expect(name).toHaveValue('')
    expect(name).toHaveAttribute('placeholder', 'RELIANCE crossing 1266.8')
  })

  it('keeps a name the trader typed exactly as they typed it', () => {
    const { handle } = handleOf([existing({ title: 'Cover the short', payload: undefined })], 'a1')
    render(<AlertsDialog handle={handle} onClose={noop} />)
    expect(screen.getByLabelText('Alert name')).toHaveValue('Cover the short')
  })

  it('carries the mark through a save, so the name still follows the price', async () => {
    const user = userEvent.setup()
    const { handle, controller } = handleOf([existing()], 'a1')
    render(<AlertsDialog handle={handle} onClose={noop} />)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(controller.update.mock.calls[0][1]).toMatchObject({ payload: { autoTitle: true } })
  })
})
