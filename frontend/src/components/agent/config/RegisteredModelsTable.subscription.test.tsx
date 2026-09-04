/**
 * Two rows that read GPT-5.4 and bill to different places.
 *
 * This is the case the whole ChatGPT subscription feature exists for. An
 * operator who registered both `openai/gpt-5.4` and `chatgpt/gpt-5.4` and took
 * the default display name for each has two entries in this table that look
 * alike, and only one of them spends API credits. Without the badge the sole
 * difference on screen is a five-character prefix inside a grey monospace line
 * that nobody reads as a billing path.
 *
 * The Key column matters for the same reason. A plan row has no `ag_secret`
 * entry, so `has_api_key` is false and the cell would read "No key stored",
 * which is exactly what a broken OpenAI row reads. Sourcing the fingerprint
 * from the subscription status is what keeps a working plan row from looking
 * misconfigured on the one screen whose job is telling the two apart.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentModel, ChatGptStatus } from '@/api/agent'
import { render, screen } from '@/test/test-utils'
import { RegisteredModelsTable } from './RegisteredModelsTable'

let models: AgentModel[] = []
let chatGptStatus: ChatGptStatus | null = null
let statusFails = false
const statusCalls = vi.fn()

vi.mock('@/api/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/agent')>()),
  listModels: async () => models,
  getChatGptStatus: async () => {
    statusCalls()
    if (statusFails) throw new Error('Not Found')
    return chatGptStatus as ChatGptStatus
  },
}))

function model(overrides: Partial<AgentModel> = {}): AgentModel {
  return {
    id: 1,
    provider_kind: 'openai',
    model_name: 'gpt-5.4',
    display_name: 'GPT-5.4',
    base_url: null,
    enabled: true,
    is_default: false,
    supports_reasoning: false,
    default_reasoning_effort: 'off',
    supports_vision: false,
    tools_unreliable: false,
    last_tested_at: null,
    last_test_ok: null,
    last_test_error: null,
    has_api_key: true,
    api_key_fingerprint: '...4321 sha256:aaaaaaaaaaaa',
    api_key_source: 'provider:openai',
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
    ...overrides,
  }
}

const PLAN_MODEL = model({
  id: 2,
  provider_kind: 'litellm',
  model_name: 'chatgpt/gpt-5.4',
  display_name: 'GPT-5.4',
  has_api_key: false,
  api_key_fingerprint: null,
  api_key_source: null,
})

function wrap(node: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  models = []
  statusFails = false
  statusCalls.mockReset()
  chatGptStatus = {
    authorised: true,
    fingerprint: '...9f2c sha256:0123456789ab',
    account_id: 'acct_1234',
    expiry: null,
    stored_in_database: true,
    token_dir: 'db/chatgpt_oauth',
    login: {
      state: 'authorised',
      user_code: '',
      verification_url: '',
      started_at: null,
      expires_at: null,
      message: '',
    },
  }
})

describe('RegisteredModelsTable and the two GPT-5.4 rows', () => {
  it('marks the plan row and leaves the API row unmarked', async () => {
    models = [model(), PLAN_MODEL]
    wrap(<RegisteredModelsTable />)

    // Both rows are there, and both are named GPT-5.4.
    expect(await screen.findAllByText('GPT-5.4')).toHaveLength(2)
    expect(screen.getByText('chatgpt/gpt-5.4')).toBeInTheDocument()
    expect(screen.getByText('gpt-5.4')).toBeInTheDocument()

    // Exactly one of them says where it bills.
    expect(screen.getAllByText('ChatGPT plan')).toHaveLength(1)
  })

  it('describes the plan row credential with the subscription fingerprint', async () => {
    models = [PLAN_MODEL]
    wrap(<RegisteredModelsTable />)

    expect(await screen.findByText('...9f2c sha256:0123456789ab')).toBeInTheDocument()
    expect(screen.getByText('your ChatGPT plan sign-in')).toBeInTheDocument()
    // The reading that made a working plan row look broken.
    expect(screen.queryByText('No key stored')).not.toBeInTheDocument()
  })

  it('says no plan is connected rather than claiming a missing key', async () => {
    models = [PLAN_MODEL]
    chatGptStatus = { ...(chatGptStatus as ChatGptStatus), authorised: false }
    wrap(<RegisteredModelsTable />)

    expect(await screen.findByText('No plan connected yet')).toBeInTheDocument()
    expect(screen.queryByText('No key stored')).not.toBeInTheDocument()
  })

  it('still renders the plan row when the subscription route is unavailable', async () => {
    models = [PLAN_MODEL]
    statusFails = true
    wrap(<RegisteredModelsTable />)

    expect(await screen.findByText('chatgpt/gpt-5.4')).toBeInTheDocument()
    expect(screen.getByText('ChatGPT plan')).toBeInTheDocument()
    expect(screen.getByText('No plan connected yet')).toBeInTheDocument()
  })

  // The route is new and an older server answers 404 for it, so a registry with
  // no plan row has no reason to ask.
  it('does not ask about a subscription when no plan row is registered', async () => {
    models = [model()]
    wrap(<RegisteredModelsTable />)

    expect(await screen.findByText('gpt-5.4')).toBeInTheDocument()
    expect(statusCalls).not.toHaveBeenCalled()
  })
})
