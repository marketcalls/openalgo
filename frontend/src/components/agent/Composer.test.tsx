/**
 * The prefill end of the composer, the one thing it must never do, and the
 * files it can now carry.
 *
 * A Buy or Sell control on an instrument card writes a request into this box.
 * That is the entire mechanism, and it is a safety property rather than a
 * convenience: every order in this product pauses at a human approval gate, so
 * a control wired to an order tool would be the one path around it. The first
 * test here is that `onSend` is not called. If a future change makes a prefill
 * submit, it fails before anything reaches a broker.
 *
 * The second is smaller and still worth pinning: a prefill must not throw away
 * a half-written message. Losing what somebody was typing because they clicked
 * a button beside the answer is the kind of thing nobody reports and everybody
 * remembers.
 *
 * The attachment tests below pin the two halves of the vision gate, and the
 * second half is the one that matters: a model whose `supports_vision` column
 * is false but which LiteLLM knows can see must still accept a file, because
 * that is what the run will do. Reading the column alone would disable
 * attaching on every model configured on a real instance.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentModel, CatalogModel } from '@/api/agent'
import { prefillComposer, useComposerPrefill } from '@/lib/agent/composer'
import { act, fireEvent, render, renderHook, screen, userEvent } from '@/test/test-utils'
import { Composer } from './Composer'

const REQUEST = 'Buy 1 share of RELIANCE on NSE at market.'

/** What `GET /agent/api/models` answers with for this test. */
let models: AgentModel[] = []
/** What `GET /agent/api/catalog/models` answers with for this test. */
let catalog: CatalogModel[] = []

vi.mock('@/api/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/agent')>()),
  listModels: async () => models,
  listCatalogModels: async () => ({ available: true, provider: null, data: catalog }),
}))

/**
 * A configured model row.
 *
 * `supports_vision` defaults to false because that is what the column holds on
 * a real instance: it is an operator checkbox nobody ticks, and the resolution
 * that matters happens against LiteLLM's catalogue.
 */
function model(overrides: Partial<AgentModel> = {}): AgentModel {
  return {
    id: 1,
    provider_kind: 'openai',
    model_name: 'gpt-4o',
    display_name: 'GPT-4o',
    base_url: null,
    enabled: true,
    is_default: true,
    supports_reasoning: false,
    default_reasoning_effort: 'off',
    supports_vision: false,
    tools_unreliable: false,
    last_tested_at: null,
    last_test_ok: true,
    last_test_error: null,
    has_api_key: true,
    api_key_fingerprint: null,
    api_key_source: 'provider:openai',
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

/** One catalogue entry, which is LiteLLM's own opinion about that model. */
function entry(overrides: Partial<CatalogModel> = {}): CatalogModel {
  return {
    id: 'gpt-4o',
    provider: 'openai',
    qualified_id: 'openai/gpt-4o',
    catalog_key: 'gpt-4o',
    mode: 'chat',
    max_input_tokens: 128000,
    max_output_tokens: 16384,
    input_price_per_million: 2.5,
    output_price_per_million: 10,
    supports_function_calling: true,
    supports_vision: true,
    supports_reasoning: false,
    in_catalog: true,
    is_chat: true,
    ...overrides,
  }
}

function renderComposer(node: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

function box(): HTMLTextAreaElement {
  return screen.getByLabelText('Message the agent') as HTMLTextAreaElement
}

function picker(): HTMLInputElement {
  return screen.getByLabelText('Choose files to attach') as HTMLInputElement
}

beforeEach(() => {
  models = [model()]
  catalog = [entry()]
})

describe('Composer prefill', () => {
  it('fills the box and sends nothing', () => {
    const onSend = vi.fn()
    renderComposer(<Composer onSend={onSend} onStop={vi.fn()} running={false} />)

    act(() => {
      expect(prefillComposer(REQUEST)).toBe(true)
    })

    expect(box().value).toBe(REQUEST)
    expect(onSend).not.toHaveBeenCalled()
    // The send button is now live, because that is the operator's action and
    // theirs alone.
    expect(screen.getByRole('button', { name: 'Send the message' })).toBeEnabled()
  })

  it('keeps what the operator was already writing', async () => {
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)
    await userEvent.type(box(), 'is this a good entry')

    act(() => {
      prefillComposer(REQUEST)
    })

    expect(box().value).toBe(`is this a good entry\n${REQUEST}`)
  })

  it('reports that nothing received it when no composer is mounted', () => {
    expect(prefillComposer(REQUEST)).toBe(false)
  })
})

/**
 * The chart panel mounts this same composer and is offered no order tools at
 * all, so a Buy on an answer's instrument card there would write a sentence the
 * surface can only refuse. "There is a box" is therefore not the question the
 * card is asking, and these pin the difference.
 */
describe('order controls follow the surface, not the box', () => {
  it('withholds them from a composer whose surface cannot order', () => {
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} canOrder={false} />)
    expect(renderHook(() => useComposerPrefill()).result.current).toBe(false)
  })

  it('still takes a prefill there, because a chip is not an order', () => {
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} canOrder={false} />)
    act(() => {
      expect(prefillComposer('Analyse the RELIANCE D chart.')).toBe(true)
    })
    expect(box().value).toBe('Analyse the RELIANCE D chart.')
  })

  it('offers them on a composer that can', () => {
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)
    expect(renderHook(() => useComposerPrefill()).result.current).toBe(true)
  })
})

describe('attachments', () => {
  it('takes a picked file and lets it be taken off again', async () => {
    const user = userEvent.setup()
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)

    await user.upload(picker(), new File(['abcde'], 'book.csv', { type: 'text/csv' }))

    expect(await screen.findByText('book.csv')).toBeInTheDocument()
    // The size, and the cap it is measured against, both shown from the first
    // file rather than only once it is nearly full.
    expect(screen.getByText('5 B')).toBeInTheDocument()
    expect(screen.getByText('5 B of 8.0 MB')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove book.csv' }))
    expect(screen.queryByText('book.csv')).not.toBeInTheDocument()
  })

  it('takes a pasted screenshot, which is how one actually arrives', async () => {
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)

    fireEvent.paste(box(), {
      clipboardData: {
        files: [new File(['png bytes'], 'shot.png', { type: 'image/png' })],
        types: ['Files'],
      },
    })

    expect(await screen.findByText('shot.png')).toBeInTheDocument()
    // Pasting a file must not also drop its name into the message.
    expect(box().value).toBe('')
  })

  it('refuses a file over the per-file cap in the browser, and says which', async () => {
    const user = userEvent.setup()
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)

    const huge = new File(['x'], 'dump.png', { type: 'image/png' })
    Object.defineProperty(huge, 'size', { value: 4_000_001 })
    await user.upload(picker(), huge)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'dump.png is 4.0 MB, over the 4.0 MB limit for one file.'
    )
    expect(screen.queryByText('dump.png')).not.toBeInTheDocument()
  })

  it('sends the files with the message and then clears them', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    renderComposer(<Composer onSend={onSend} onStop={vi.fn()} running={false} />)

    await user.upload(picker(), new File(['abc'], 'note.txt', { type: 'text/plain' }))
    await screen.findByText('note.txt')
    await user.type(box(), 'what is in this file')
    await user.click(screen.getByRole('button', { name: 'Send the message' }))

    expect(onSend).toHaveBeenCalledTimes(1)
    const [text, turn] = onSend.mock.calls[0]
    expect(text).toBe('what is in this file')
    expect(turn.attachments).toHaveLength(1)
    expect(turn.attachments[0].name).toBe('note.txt')
    expect(turn.attachments[0].dataUrl.startsWith('data:')).toBe(true)
    expect(turn.webSearch).toBe(true)
    expect(screen.queryByText('note.txt')).not.toBeInTheDocument()
  })
})

/**
 * The vision gate.
 *
 * `supports_vision` on the row is an operator checkbox and the run does not
 * trust it: `providers.vision_capable` lets LiteLLM decide for any model it
 * carries metadata for. Both directions are pinned here because both have been
 * wrong in production for the other capability.
 */
describe('attaching follows what the model can actually read', () => {
  it('is offered when the catalogue says the model can see, whatever the column says', async () => {
    const user = userEvent.setup()
    models = [model({ supports_vision: false })]
    catalog = [entry({ supports_vision: true })]
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)

    await user.click(screen.getByRole('button', { name: 'Add to this message' }))
    const item = await screen.findByRole('menuitem', { name: 'Attach files' })
    expect(item).not.toHaveAttribute('aria-disabled', 'true')
    expect(screen.queryByText(/cannot read images/)).not.toBeInTheDocument()
  })

  it('is withheld with the reason when the model cannot see', async () => {
    const user = userEvent.setup()
    models = [model({ display_name: 'GPT-3.5 Turbo', model_name: 'gpt-3.5-turbo' })]
    catalog = [entry({ id: 'gpt-3.5-turbo', catalog_key: 'gpt-3.5-turbo', supports_vision: false })]
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)

    await user.click(screen.getByRole('button', { name: 'Add to this message' }))

    expect(
      await screen.findByText(
        'GPT-3.5 Turbo cannot read images. Pick a model that supports vision to attach a file.'
      )
    ).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Attach files' })).toHaveAttribute(
      'aria-disabled',
      'true'
    )
  })

  it('falls back to the operator checkbox for a model the catalogue never heard of', async () => {
    const user = userEvent.setup()
    models = [model({ model_name: 'llama-vision', supports_vision: true })]
    catalog = []
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)

    await user.click(screen.getByRole('button', { name: 'Add to this message' }))
    const item = await screen.findByRole('menuitem', { name: 'Attach files' })
    expect(item).not.toHaveAttribute('aria-disabled', 'true')
  })
})

describe('the "+" menu', () => {
  it('offers a chart screenshot only where there is a chart', async () => {
    const user = userEvent.setup()
    renderComposer(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)

    await user.click(screen.getByRole('button', { name: 'Add to this message' }))
    expect(await screen.findByRole('menuitem', { name: 'Attach files' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Attach chart screenshot' })).toBeNull()
  })

  it('attaches the capture the surface hands back', async () => {
    const user = userEvent.setup()
    const capture = vi.fn().mockResolvedValue(
      new File(['png'], 'RELIANCE-D-2026-09-04-11-00.png', {
        type: 'image/png',
      })
    )
    renderComposer(
      <Composer onSend={vi.fn()} onStop={vi.fn()} running={false} onCaptureChart={capture} />
    )

    await user.click(screen.getByRole('button', { name: 'Add to this message' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Attach chart screenshot' }))

    expect(capture).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('RELIANCE-D-2026-09-04-11-00.png')).toBeInTheDocument()
  })

  it('carries the web search switch into the turn', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    renderComposer(<Composer onSend={onSend} onStop={vi.fn()} running={false} />)

    await user.click(screen.getByRole('button', { name: 'Add to this message' }))
    await user.click(await screen.findByRole('menuitemcheckbox', { name: 'Web search' }))

    await user.type(box(), 'what happened to the nifty today')
    await user.click(screen.getByRole('button', { name: 'Send the message' }))

    expect(onSend.mock.calls[0][1].webSearch).toBe(false)
  })
})
