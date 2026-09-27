/**
 * The Multi-Leg node's manual leg builder.
 *
 * The load-bearing behaviour here is that every control writes something the
 * leg can actually store. The leg records *what* it trades - an expiry, a
 * strike - never how the author picked it, so any control that first selects a
 * "mode" and only later a value has an intermediate state that cannot be
 * persisted. An earlier expiry control worked exactly that way: choosing
 * "Exact date" before typing a date serialized neither `expiry` nor
 * `expiryType`, the leg parsed straight back to "same as node", and the choice
 * appeared to do nothing at all.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { OptionStrikesResponse } from '@/api/flow'

const getOptionStrikes = vi.fn<() => Promise<OptionStrikesResponse>>()

vi.mock('@/api/flow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/flow')>()
  return { ...actual, getOptionStrikes: () => getOptionStrikes() }
})

const { CustomLegsFields } = await import('./CustomLegsFields')

const LISTING: OptionStrikesResponse = {
  underlying: 'NIFTY',
  exchange: 'NFO',
  expiry: '25AUG26',
  expiries: ['25AUG26', '01SEP26', '29SEP26'],
  resolved: {
    current_week: '25AUG26',
    next_week: '01SEP26',
    current_month: '25AUG26',
    next_month: '29SEP26',
  },
  optionType: 'CE',
  strikes: [
    { strike: 24150, symbol: 'NIFTY25AUG2624150CE', label: 'ITM1' },
    { strike: 24200, symbol: 'NIFTY25AUG2624200CE', label: 'ATM' },
    { strike: 24250, symbol: 'NIFTY25AUG2624250CE', label: 'OTM1' },
  ],
  atm: 24200,
  underlyingLtp: 24219.05,
  underlyingSymbol: 'NIFTY',
}

/** The last legs array the builder wrote back to the node. */
let saved: unknown[] = []

function Harness({ initial }: { initial?: unknown[] }) {
  const [legs, setLegs] = useState<unknown[]>(
    initial ?? [
      { strikeMode: 'OFFSET', offset: 'ATM', optionType: 'CE', action: 'BUY', quantity: 1 },
    ]
  )
  return (
    <CustomLegsFields
      value={legs}
      onChange={(next) => {
        saved = next
        setLegs(next)
      }}
      commonPriceType="MARKET"
      commonProduct="MIS"
      commonExpiryType="current_week"
      commonAction="SELL"
      commonQuantity={1}
      strangleWidth="OTM2"
      underlying="NIFTY"
    />
  )
}

async function mount(initial?: unknown[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <Harness initial={initial} />
    </QueryClientProvider>
  )
  return user
}

/** Open a Radix select by its accessible name and choose an option. */
async function choose(user: ReturnType<typeof userEvent.setup>, label: string, option: RegExp) {
  await user.click(screen.getByLabelText(label))
  await user.click(await screen.findByRole('option', { name: option }))
}

beforeEach(() => {
  saved = []
  getOptionStrikes.mockReset()
  getOptionStrikes.mockResolvedValue(LISTING)
})

describe('the expiry control', () => {
  it('lists the expiries the exchange lists, and nothing else', async () => {
    /** A plain date list, the way the Strategy Builder's leg row reads. No
     * mode step and no "same as node" entry: the control shows the date this
     * leg will trade, whatever decided it. */
    const user = await mount()
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    await user.click(screen.getByLabelText('Expiry'))
    const options = await screen.findAllByRole('option')

    expect(options.map((option) => option.textContent)).toEqual(['25AUG26', '01SEP26', '29SEP26'])
  })

  it('shows the node expiry for a leg that has none of its own', async () => {
    /** Truthful either way: this leg does trade 25AUG26 today. */
    await mount()
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    expect(screen.getByLabelText('Expiry').textContent).toContain('25AUG26')
  })

  it('picking a date stores it on the leg', async () => {
    /** The regression this control was rebuilt for: the previous mode-then-value
     * version stored nothing and reverted to the node expiry. */
    const user = await mount()
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    await choose(user, 'Expiry', /^01SEP26$/)

    expect((saved[0] as { expiry?: string }).expiry).toBe('01SEP26')
    await waitFor(() => expect(screen.getByLabelText('Expiry').textContent).toContain('01SEP26'))
  })

  it('leaves an untouched leg following the node so a scheduled basket rolls', async () => {
    /** A Flow workflow runs over and over. If every leg were pinned on sight,
     * the basket would keep trying to trade a contract that has expired. */
    await mount()
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    expect((saved as unknown[]).length).toBe(0)
    expect(screen.getByText(/rolls to the next expiry/)).toBeTruthy()
  })

  it('says nothing about rolling once a date is pinned', async () => {
    const user = await mount()
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    await choose(user, 'Expiry', /^29SEP26$/)

    await waitFor(() => expect(screen.queryByText(/rolls to the next expiry/)).toBeNull())
  })

  it('shows the resolved date for a leg carrying a relative expiry', async () => {
    /** Import and the JSON format still allow one; the panel has to render it
     * as the contract it currently means rather than blank. */
    await mount([
      { offset: 'ATM', expiryType: 'next_month', optionType: 'CE', action: 'BUY', quantity: 1 },
    ])
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    expect(screen.getByLabelText('Expiry').textContent).toContain('29SEP26')
  })

  it('keeps a stored date that the contract no longer lists', async () => {
    /** Dropping it would silently move an older workflow onto another expiry. */
    const user = await mount([
      { offset: 'ATM', expiry: '30JUL26', optionType: 'CE', action: 'BUY', quantity: 1 },
    ])
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    await user.click(screen.getByLabelText('Expiry'))
    expect(await screen.findByRole('option', { name: '30JUL26' })).toBeTruthy()
  })

  it('falls back to a text field for a {{variable}} expiry', async () => {
    await mount([
      {
        offset: 'ATM',
        expiry: '{{webhook.expiry}}',
        optionType: 'CE',
        action: 'BUY',
        quantity: 1,
      },
    ])

    expect(await screen.findByLabelText('Expiry date')).toBeTruthy()
  })
})

describe('the strike control', () => {
  it('lists listed strikes with their moneyness', async () => {
    const user = await mount()
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    await choose(user, 'Strike mode', /^Strike$/)
    await user.click(screen.getByLabelText('Strike price'))

    const listbox = await screen.findByRole('listbox')
    expect(within(listbox).getByText('24150')).toBeTruthy()
    expect(within(listbox).getByText('ITM1')).toBeTruthy()
    expect(within(listbox).getByText('ATM')).toBeTruthy()
  })

  it('seeds ATM when switching to an absolute strike', async () => {
    /** An empty strike is not a contract, and it serializes to 0 - a leg that
     * reads back as deliberately pinned to strike zero. */
    const user = await mount()
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    await choose(user, 'Strike mode', /^Strike$/)

    expect((saved[0] as { strike?: number }).strike).toBe(24200)
  })

  it('shows the contract a pinned strike resolves to', async () => {
    await mount([
      {
        strikeMode: 'STRIKE',
        strike: 24200,
        optionType: 'CE',
        action: 'BUY',
        quantity: 1,
      },
    ])

    expect(await screen.findByText('NIFTY25AUG2624200CE')).toBeTruthy()
  })

  it('shows no contract for an offset leg', async () => {
    /** It re-resolves every run, so naming today's contract would be a promise
     * the next run does not keep. */
    await mount()
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    expect(screen.queryByText('NIFTY25AUG2624200CE')).toBeNull()
  })
})

describe('product and price type', () => {
  it('show what the leg will use rather than naming the inheritance', async () => {
    /** These read "Same (MIS)" and a truncated "Same (MARK", which said neither
     * what was inherited nor from where. */
    await mount()

    expect(screen.getByLabelText('Product').textContent).toBe('MIS')
    expect(screen.getByLabelText('Price type').textContent).toBe('Market')
  })

  it('leave an untouched leg following the node', async () => {
    /** Nothing is written until the author actually chooses, so changing the
     * node's product still carries to every leg that has not overridden it. */
    await mount()

    expect((saved as unknown[]).length).toBe(0)
  })

  it('pin the leg once a value is chosen', async () => {
    const user = await mount()
    await choose(user, 'Product', /^NRML$/)

    expect((saved[0] as { product?: string }).product).toBe('NRML')
  })

  it('show a leg its own value when it has one', async () => {
    await mount([
      {
        offset: 'ATM',
        optionType: 'CE',
        action: 'BUY',
        quantity: 1,
        product: 'NRML',
        priceType: 'LIMIT',
        price: 10,
      },
    ])

    expect(screen.getByLabelText('Product').textContent).toBe('NRML')
    expect(screen.getByLabelText('Price type').textContent).toBe('Limit')
  })

  it('reveal the price field for a price type that needs one', async () => {
    const user = await mount()
    await choose(user, 'Price type', /^Limit$/)

    expect(await screen.findByLabelText('Price', { exact: true })).toBeTruthy()
  })
})

describe('when the contract lookup fails', () => {
  it('still lets the leg be edited by hand', async () => {
    /** No API key, no broker session, or an underlying the master contract does
     * not carry. The workflow has to stay editable. */
    getOptionStrikes.mockRejectedValue(new Error('no api key'))
    await mount()

    expect(await screen.findByText(/Listed contracts unavailable/)).toBeTruthy()
    expect(screen.getByLabelText('Expiry')).toBeTruthy()
  })
})

describe('a leg naming a strike the picker does not list', () => {
  it('shows a far offset instead of an empty control', async () => {
    /** The reported import bug: the executor accepts OTM1-OTM50, the dropdown
     * stopped at OTM10, and a generated workflow reaching for a far strike
     * came up blank - so the next value picked silently replaced it. */
    await mount([
      { strikeMode: 'OFFSET', offset: 'OTM12', optionType: 'PE', action: 'SELL', quantity: 1 },
    ])
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    expect(screen.getByLabelText('Strike offset').textContent).toContain('OTM12')
  })

  it('offers the far offsets to pick in the first place', async () => {
    const user = await mount()
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    await user.click(screen.getByLabelText('Strike offset'))
    const offered = (await screen.findAllByRole('option')).map((o) => o.textContent)

    expect(offered).toContain('OTM12')
    expect(offered).toContain('OTM25')
    expect(offered).toContain('ITM8')
    expect(offered).not.toContain('OTM26')
  })

  it('keeps an offset outside the contract visible rather than dropping it', async () => {
    /** Hand-written or from an older build. Shown as stored so the author can
     * see and correct it, the way parseCustomLegs carries unknown values. */
    await mount([
      { strikeMode: 'OFFSET', offset: 'OTM60', optionType: 'CE', action: 'BUY', quantity: 1 },
    ])
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    expect(screen.getByLabelText('Strike offset').textContent).toContain('OTM60')
  })

  it('keeps a strike outside the chain window selectable', async () => {
    /** The chain arrives as a window around ATM, so a leg pinned far out of
     * the money has no row of its own - the same failure, and the same fix the
     * expiry control already had for a date the contract no longer lists. */
    await mount([
      { strikeMode: 'STRIKE', strike: 21000, optionType: 'PE', action: 'SELL', quantity: 1 },
    ])
    await waitFor(() => expect(screen.getByText(/ATM 24200/)).toBeTruthy())

    expect(screen.getByLabelText('Strike price').textContent).toContain('21000')
  })
})
