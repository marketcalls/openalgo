/**
 * The subscription panel's state machine, and what each state puts on screen.
 *
 * The machine is the part worth pinning. Four of its states are reachable only
 * through a device-code sign-in against OpenAI, which no test may start, so the
 * reading of the status object is where the behaviour actually lives and where
 * it can be checked without a network.
 *
 * Two rules here are security rules rather than presentation ones, and both are
 * asserted rather than assumed:
 *
 * - **No token is ever rendered.** What a connected panel shows is a
 *   fingerprint, exactly as an API key row does. The test feeds a status object
 *   carrying a refresh-token-shaped string in a field the panel does not read
 *   and asserts it never reaches the document.
 * - **A pending sign-in outranks an existing authorisation.** An operator
 *   moving this instance to a different ChatGPT account is still connected to
 *   the old one while they do it, and the code on screen is the only thing they
 *   can act on, so it must not be hidden behind a Connected view.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChatGptLogin, ChatGptStatus } from '@/api/agent'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import {
  ChatGptSubscriptionPanel,
  chatGptPanelState,
  secondsRemaining,
} from './ChatGptSubscriptionPanel'

/** What the mocked status route answers, or the error it throws. */
let statusAnswer: ChatGptStatus | null = null
let statusFails = false
const startLogin = vi.fn()
const cancelLogin = vi.fn()
const removeSession = vi.fn()

vi.mock('@/api/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/agent')>()),
  getChatGptStatus: async () => {
    if (statusFails) throw new Error('Not Found')
    return statusAnswer as ChatGptStatus
  },
  startChatGptLogin: (force: boolean) => startLogin(force),
  cancelChatGptLogin: () => cancelLogin(),
  removeChatGptSession: () => removeSession(),
}))

function login(overrides: Partial<ChatGptLogin> = {}): ChatGptLogin {
  return {
    state: 'idle',
    user_code: '',
    verification_url: '',
    started_at: null,
    expires_at: null,
    message: '',
    ...overrides,
  }
}

function status(overrides: Partial<ChatGptStatus> = {}): ChatGptStatus {
  return {
    authorised: false,
    fingerprint: '...????',
    account_id: null,
    expiry: null,
    stored_in_database: false,
    token_dir: 'D:/openalgo/db/chatgpt_oauth',
    login: login(),
    ...overrides,
  }
}

function wrap(node: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  statusAnswer = status()
  statusFails = false
  startLogin.mockReset()
  cancelLogin.mockReset()
  removeSession.mockReset()
})

describe('chatGptPanelState', () => {
  it('is loading until the first answer, and unavailable when there is none', () => {
    expect(chatGptPanelState({ status: undefined, isError: false })).toBe('loading')
    expect(chatGptPanelState({ status: undefined, isError: true })).toBe('unavailable')
  })

  it('reads no plan and no sign-in as disconnected', () => {
    expect(chatGptPanelState({ status: status(), isError: false })).toBe('disconnected')
    expect(
      chatGptPanelState({
        status: status({ login: login({ state: 'cancelled' }) }),
        isError: false,
      })
    ).toBe('disconnected')
  })

  it('reads a stored credential as connected', () => {
    expect(chatGptPanelState({ status: status({ authorised: true }), isError: false })).toBe(
      'connected'
    )
  })

  // The ordering rule. A forced re-sign-in happens while the old credential is
  // still valid, so authorised is true and a code is outstanding at the same
  // time. Showing Connected then would hide the only thing the operator can act
  // on.
  it('puts a pending sign-in ahead of an existing authorisation', () => {
    const pending = status({ authorised: true, login: login({ state: 'pending' }) })
    expect(chatGptPanelState({ status: pending, isError: false })).toBe('connecting')
  })

  it('separates a code that ran out from a sign-in that failed', () => {
    expect(
      chatGptPanelState({ status: status({ login: login({ state: 'expired' }) }), isError: false })
    ).toBe('expired')
    expect(
      chatGptPanelState({ status: status({ login: login({ state: 'failed' }) }), isError: false })
    ).toBe('failed')
  })

  // A terminal state left over from a previous attempt says nothing about a
  // plan that is connected now.
  it('reads a connected plan as connected whatever the last sign-in ended as', () => {
    const after = status({ authorised: true, login: login({ state: 'failed' }) })
    expect(chatGptPanelState({ status: after, isError: false })).toBe('connected')
  })
})

describe('secondsRemaining', () => {
  it('counts down in whole seconds and never below zero', () => {
    const at = login({ expires_at: 1_800_000_900 })
    expect(secondsRemaining(at, 1_800_000_000_000)).toBe(900)
    expect(secondsRemaining(at, 1_800_000_899_400)).toBe(1)
    expect(secondsRemaining(at, 1_800_001_000_000)).toBe(0)
  })

  it('is unknown rather than zero when the snapshot names no deadline', () => {
    expect(secondsRemaining(login(), Date.now())).toBeNull()
    expect(
      secondsRemaining(login({ expires_at: Number.NaN as unknown as number }), Date.now())
    ).toBeNull()
  })
})

describe('ChatGptSubscriptionPanel', () => {
  it('offers one Connect when no plan is attached', async () => {
    wrap(<ChatGptSubscriptionPanel />)

    expect(await screen.findByRole('button', { name: /Connect ChatGPT plan/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Disconnect/ })).not.toBeInTheDocument()
    // There is no key to type, and there never can be one.
    expect(screen.queryByLabelText(/API key/i)).not.toBeInTheDocument()
  })

  it('shows the code, the link, the deadline and a way out while it waits', async () => {
    startLogin.mockResolvedValue(
      login({
        state: 'pending',
        user_code: 'ABCD-EFGH',
        verification_url: 'https://example.invalid/device',
        started_at: Date.now() / 1000,
        expires_at: Date.now() / 1000 + 900,
      })
    )
    wrap(<ChatGptSubscriptionPanel />)

    await userEvent.click(await screen.findByRole('button', { name: /Connect ChatGPT plan/ }))

    expect(await screen.findByText('ABCD-EFGH')).toBeInTheDocument()
    expect(startLogin).toHaveBeenCalledWith(false)

    const link = screen.getByRole('link', { name: /Open the sign-in page/ })
    expect(link).toHaveAttribute('href', 'https://example.invalid/device')
    // A new tab, and never with an opener onto this page.
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))

    // Fifteen minutes, said honestly rather than left for the operator to find
    // out when the code stops working.
    expect(screen.getByText(/Expires in 1[45]:/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Cancel sign-in/ })).toBeInTheDocument()
  })

  it('stops a sign-in and goes back to offering one', async () => {
    startLogin.mockResolvedValue(
      login({ state: 'pending', user_code: 'WXYZ-1234', expires_at: Date.now() / 1000 + 900 })
    )
    cancelLogin.mockImplementation(async () => {
      statusAnswer = status({ login: login({ state: 'cancelled', message: 'Sign-in cancelled.' }) })
      return { data: statusAnswer.login, stopped: true }
    })
    wrap(<ChatGptSubscriptionPanel />)

    await userEvent.click(await screen.findByRole('button', { name: /Connect ChatGPT plan/ }))
    await screen.findByText('WXYZ-1234')

    await userEvent.click(screen.getByRole('button', { name: /Cancel sign-in/ }))

    expect(cancelLogin).toHaveBeenCalled()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Connect ChatGPT plan/ })).toBeInTheDocument()
    })
    expect(screen.queryByText('WXYZ-1234')).not.toBeInTheDocument()
  })

  it('shows a fingerprint and never a token once a plan is attached', async () => {
    statusAnswer = {
      ...status({
        authorised: true,
        fingerprint: '...9f2c sha256:0123456789ab',
        account_id: 'acct_1234',
        expiry: 1_800_000_000,
        stored_in_database: true,
      }),
      // A field the panel does not read, standing in for anything a future
      // route might accidentally include. It must not reach the screen.
      ...({ refresh_token: 'rt_live_do_not_render_me' } as Record<string, unknown>),
    } as ChatGptStatus

    const { container } = wrap(<ChatGptSubscriptionPanel />)

    expect(await screen.findByText('...9f2c sha256:0123456789ab')).toBeInTheDocument()
    expect(screen.getByText('acct_1234')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Disconnect/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Sign in again/ })).toBeInTheDocument()
    expect(container.textContent).not.toContain('rt_live_do_not_render_me')
  })

  it('says what expired and offers the retry, without calling it a failure', async () => {
    statusAnswer = status({
      login: login({ state: 'expired', message: 'The device code expired.' }),
    })
    wrap(<ChatGptSubscriptionPanel />)

    expect(await screen.findByText(/was not entered in time/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Try connecting again/ })).toBeInTheDocument()
  })

  it('repeats the provider own reason when a sign-in fails', async () => {
    statusAnswer = status({
      login: login({ state: 'failed', message: 'access_denied: the request was refused' }),
    })
    wrap(<ChatGptSubscriptionPanel />)

    expect(await screen.findByText(/access_denied: the request was refused/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Try connecting again/ })).toBeInTheDocument()
  })

  // The state this panel is in on every server that has not shipped the routes
  // yet, and on any install whose LiteLLM predates the provider. It has to say
  // so rather than sit on a spinner or offer a Connect that cannot work.
  it('says so plainly when the server cannot answer for a plan', async () => {
    statusFails = true
    wrap(<ChatGptSubscriptionPanel />)

    expect(await screen.findByText(/cannot answer for a ChatGPT plan yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Connect ChatGPT plan/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Try again/ })).toBeInTheDocument()
  })

  it('asks before disconnecting, and says the models are left alone', async () => {
    statusAnswer = status({ authorised: true, fingerprint: '...9f2c sha256:0123456789ab' })
    wrap(<ChatGptSubscriptionPanel />)

    await userEvent.click(await screen.findByRole('button', { name: /Disconnect/ }))

    expect(await screen.findByText('Disconnect the ChatGPT plan')).toBeInTheDocument()
    expect(screen.getByText(/stays in the registry/)).toBeInTheDocument()
    // Nothing is removed until the operator confirms it.
    expect(removeSession).not.toHaveBeenCalled()
  })

  it('reports a refused sign-in against the panel rather than swallowing it', async () => {
    startLogin.mockRejectedValue(new Error('litellm is too old for the chatgpt provider'))
    wrap(<ChatGptSubscriptionPanel />)

    await userEvent.click(await screen.findByRole('button', { name: /Connect ChatGPT plan/ }))

    expect(
      await screen.findByText(/litellm is too old for the chatgpt provider/)
    ).toBeInTheDocument()
  })
})
