import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AlertChannel, AlertChannelList } from '@/api/alerts'
import { renderWithQuery } from '@/test/queryRender'
import { fireEvent, screen, waitFor } from '@/test/test-utils'
import AlertsIndex from './AlertsIndex'

// The /alerts page: one card per channel and one routing grid. The server
// decides what is ready and why; the page renders it and sends changes.

const api = vi.hoisted(() => ({
  list: vi.fn(),
  update: vi.fn(),
  saveWebhook: vi.fn(),
  forgetWebhook: vi.fn(),
  sendTest: vi.fn(),
}))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))

vi.mock('@/api/alerts', async (original) => ({
  ...(await original<typeof import('@/api/alerts')>()),
  alertsApi: api,
}))
vi.mock('@/utils/toast', () => ({ showToast: toast }))

const ALL = ['orders_placed', 'gtt_orders']

function channel(name: AlertChannel['name'], overrides: Partial<AlertChannel> = {}): AlertChannel {
  const label = { telegram: 'Telegram', whatsapp: 'WhatsApp', slack: 'Slack', discord: 'Discord' }[
    name
  ]
  return {
    name,
    label,
    setup_path: `/${name}`,
    uses_webhook: name === 'slack' || name === 'discord',
    enabled: true,
    categories: ALL,
    status: { configured: true, ready: true, detail: `${label} is ready.` },
    ...overrides,
  }
}

function listing(channels: AlertChannel[]): AlertChannelList {
  return {
    categories: [
      { id: 'orders_placed', label: 'Orders placed', description: 'New orders.' },
      { id: 'gtt_orders', label: 'GTT orders', description: 'GTT events.' },
    ],
    channels,
  }
}

beforeEach(() => {
  for (const fn of [...Object.values(api), ...Object.values(toast)]) fn.mockReset()
  api.list.mockResolvedValue(
    listing([
      channel('telegram'),
      channel('whatsapp', {
        status: { configured: true, ready: false, detail: 'The paired device is not connected.' },
      }),
      channel('slack', {
        enabled: false,
        status: { configured: false, ready: false, detail: 'No webhook is saved yet.' },
      }),
      channel('discord', { categories: ['gtt_orders'] }),
    ])
  )
})

afterEach(() => {
  window.history.pushState({}, '', '/')
})

describe('Alerts page', () => {
  it('shows every channel with what the server said about it', async () => {
    renderWithQuery(<AlertsIndex />)

    expect(await screen.findByText('Telegram is ready.')).toBeInTheDocument()
    expect(screen.getByText('The paired device is not connected.')).toBeInTheDocument()
    expect(screen.getByText('No webhook is saved yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Set up Slack/ })).toHaveAttribute('href', '/slack')
    expect(screen.getByRole('link', { name: /Open Telegram settings/ })).toHaveAttribute(
      'href',
      '/telegram'
    )
  })

  it('cannot switch Slack on before a webhook is saved', async () => {
    renderWithQuery(<AlertsIndex />)

    expect(await screen.findByRole('switch', { name: 'Send alerts to Slack' })).toBeDisabled()
    expect(screen.getByRole('switch', { name: 'Send alerts to Telegram' })).toBeEnabled()
  })

  it('switches a channel off and shows what the server saved', async () => {
    api.update.mockResolvedValue(channel('telegram', { enabled: false }))
    renderWithQuery(<AlertsIndex />)

    fireEvent.click(await screen.findByRole('switch', { name: 'Send alerts to Telegram' }))

    await waitFor(() => expect(api.update).toHaveBeenCalledWith('telegram', { enabled: false }))
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Send alerts to Telegram' })).not.toBeChecked()
    )
  })

  it('routes one group to one channel from the grid', async () => {
    api.update.mockResolvedValue(channel('discord', { categories: ALL }))
    renderWithQuery(<AlertsIndex />)

    const box = await screen.findByRole('checkbox', { name: 'Orders placed on Discord' })
    expect(box).not.toBeChecked()
    fireEvent.click(box)

    await waitFor(() =>
      expect(api.update).toHaveBeenCalledWith('discord', {
        categories: ['gtt_orders', 'orders_placed'],
      })
    )
  })

  it('lets a channel that is off be routed, ready for when it is on', async () => {
    renderWithQuery(<AlertsIndex />)

    expect(await screen.findByRole('checkbox', { name: 'GTT orders on Slack' })).toBeEnabled()
  })

  it("locks a channel's routing row while one of its saves is running", async () => {
    // Each save sends the whole list of groups. A second tick made while the
    // first saved would be built from the old list and undo the first.
    let finish: (value: AlertChannel) => void = () => {}
    api.update.mockReturnValue(
      new Promise<AlertChannel>((resolve) => {
        finish = resolve
      })
    )
    renderWithQuery(<AlertsIndex />)

    fireEvent.click(await screen.findByRole('checkbox', { name: 'Orders placed on Discord' }))

    const other = screen.getByRole('checkbox', { name: 'GTT orders on Discord' })
    await waitFor(() => expect(other).toBeDisabled())
    expect(screen.getByRole('checkbox', { name: 'GTT orders on Telegram' })).toBeEnabled()
    finish(channel('discord', { categories: ALL }))
    await waitFor(() => expect(other).toBeEnabled())
    expect(api.update).toHaveBeenCalledTimes(1)
  })

  it('keeps a test pending while another action finishes', async () => {
    let finishTest: (value: string) => void = () => {}
    api.sendTest.mockReturnValue(
      new Promise<string>((resolve) => {
        finishTest = resolve
      })
    )
    api.update.mockResolvedValue(channel('discord', { enabled: false }))
    renderWithQuery(<AlertsIndex />)

    await screen.findByText('Telegram is ready.')
    const telegramTest = screen.getAllByRole('button', { name: /Send test/ })[0]
    fireEvent.click(telegramTest)
    await waitFor(() => expect(telegramTest).toBeDisabled())
    fireEvent.click(screen.getByRole('switch', { name: 'Send alerts to Discord' }))
    await waitFor(() => expect(api.update).toHaveBeenCalled())
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Send alerts to Discord' })).not.toBeChecked()
    )

    expect(telegramTest).toBeDisabled()
    finishTest('Test message sent to Telegram.')
    await waitFor(() => expect(telegramTest).toBeEnabled())
  })

  it('offers a test only where an alert would arrive', async () => {
    renderWithQuery(<AlertsIndex />)

    await screen.findByText('Telegram is ready.')
    const tests = screen.getAllByRole('button', { name: /Send test/ })
    expect(tests.map((button) => (button as HTMLButtonElement).disabled)).toEqual([
      false, // Telegram: on and ready
      true, // WhatsApp: on, not connected
      true, // Slack: off
      false, // Discord: on and ready
    ])
  })

  it("shows the server's own sentence when a test fails", async () => {
    const { AxiosError } = await import('axios')
    api.sendTest.mockRejectedValue(
      new AxiosError('Request failed', '409', undefined, undefined, {
        data: { status: 'error', message: 'Discord no longer accepts this webhook.' },
        status: 409,
        statusText: 'Conflict',
        headers: {},
        config: {} as never,
      })
    )
    renderWithQuery(<AlertsIndex />)

    await screen.findByText('Telegram is ready.')
    fireEvent.click(screen.getAllByRole('button', { name: /Send test/ })[3])

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('Discord no longer accepts this webhook.')
    )
  })
})
