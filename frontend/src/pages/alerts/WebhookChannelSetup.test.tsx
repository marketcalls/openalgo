import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AlertChannel, AlertChannelList } from '@/api/alerts'
import { renderWithQuery } from '@/test/queryRender'
import { fireEvent, screen, waitFor } from '@/test/test-utils'
import WebhookChannelSetup from './WebhookChannelSetup'

// The /slack and /discord pages: save, test and remove a webhook. A saved
// webhook URL is a secret, so the page never has it to show.

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

const URL = 'https://hooks.slack.com/services/T1/B2/secret'

function slack(saved: boolean): AlertChannel {
  return {
    name: 'slack',
    label: 'Slack',
    setup_path: '/slack',
    uses_webhook: true,
    enabled: saved,
    categories: ['orders_placed'],
    status: {
      configured: saved,
      ready: saved,
      detail: saved ? 'Webhook saved.' : 'No webhook is saved yet.',
    },
  }
}

function listing(channel: AlertChannel): AlertChannelList {
  return { categories: [], channels: [channel] }
}

beforeEach(() => {
  for (const fn of [...Object.values(api), ...Object.values(toast)]) fn.mockReset()
})

describe.each([
  ['slack', 'Slack', 'https://hooks.slack.com/services/...', /api\.slack\.com\/apps/],
  ['discord', 'Discord', 'https://discord.com/api/webhooks/...', /Copy Webhook URL/],
] as const)('%s setup page', (name, label, placeholder, step) => {
  it('shows where its webhook comes from and what one looks like', async () => {
    api.list.mockResolvedValue(listing({ ...slack(false), name, label, setup_path: `/${name}` }))
    renderWithQuery(<WebhookChannelSetup channel={name} />)

    expect(await screen.findByRole('heading', { name: `${label} alerts` })).toBeInTheDocument()
    expect(screen.getByText(step)).toBeInTheDocument()
    expect(screen.getByLabelText('Webhook URL')).toHaveAttribute('placeholder', placeholder)
  })
})

describe('Slack setup page', () => {
  it('explains where a webhook comes from and masks the field', async () => {
    api.list.mockResolvedValue(listing(slack(false)))
    renderWithQuery(<WebhookChannelSetup channel="slack" />)

    expect(await screen.findByText(/api\.slack\.com\/apps/)).toBeInTheDocument()
    expect(screen.getByLabelText('Webhook URL')).toHaveAttribute('type', 'password')
    expect(screen.queryByRole('button', { name: /Remove webhook/ })).not.toBeInTheDocument()
  })

  it('saves a webhook, clears the field and turns the channel on', async () => {
    api.list.mockResolvedValue(listing(slack(false)))
    api.saveWebhook.mockResolvedValue(slack(true))
    renderWithQuery(<WebhookChannelSetup channel="slack" />)

    const field = await screen.findByLabelText('Webhook URL')
    fireEvent.change(field, { target: { value: URL } })
    fireEvent.click(screen.getByRole('button', { name: /Save webhook/ }))

    await waitFor(() => expect(api.saveWebhook).toHaveBeenCalledWith('slack', URL))
    await waitFor(() => expect(field).toHaveValue(''))
    expect(await screen.findByText('On')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('secret')
  })

  it("shows the server's sentence when a URL is refused", async () => {
    const { AxiosError } = await import('axios')
    api.list.mockResolvedValue(listing(slack(false)))
    api.saveWebhook.mockRejectedValue(
      new AxiosError('Request failed', '400', undefined, undefined, {
        data: { status: 'error', message: 'That is not a Slack webhook URL.' },
        status: 400,
        statusText: 'Bad Request',
        headers: {},
        config: {} as never,
      })
    )
    renderWithQuery(<WebhookChannelSetup channel="slack" />)

    fireEvent.change(await screen.findByLabelText('Webhook URL'), {
      target: { value: 'https://example.com' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Save webhook/ }))

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('That is not a Slack webhook URL.')
    )
  })

  it('removes a saved webhook only after the trader confirms', async () => {
    api.list.mockResolvedValue(listing(slack(true)))
    api.forgetWebhook.mockResolvedValue(slack(false))
    renderWithQuery(<WebhookChannelSetup channel="slack" />)

    fireEvent.click(await screen.findByRole('button', { name: /Remove webhook/ }))
    expect(api.forgetWebhook).not.toHaveBeenCalled()
    fireEvent.click(await screen.findByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(api.forgetWebhook).toHaveBeenCalledWith('slack'))
  })

  it('sends a test through the saved webhook', async () => {
    api.list.mockResolvedValue(listing(slack(true)))
    api.sendTest.mockResolvedValue('Message sent to Slack.')
    renderWithQuery(<WebhookChannelSetup channel="slack" />)

    fireEvent.click(await screen.findByRole('button', { name: /Send test/ }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Message sent to Slack.'))
  })
})
