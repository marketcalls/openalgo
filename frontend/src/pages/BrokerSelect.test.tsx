import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BrokerList } from '@/api/broker-config'
import { useAuthStore } from '@/stores/authStore'
import { useBrokerStore } from '@/stores/brokerStore'
import { brokerEntry, brokerList, saved } from '@/test/brokerList'
import { renderWithQuery } from '@/test/queryRender'
import { fireEvent, screen, waitFor, within } from '@/test/test-utils'
import BrokerSelect from './BrokerSelect'

// Select Broker is a card per broker, as in OpenAlgo Desktop. Keys are saved
// for many brokers; one broker is logged in at a time. "Login with" asks the
// server to start the sign-in and goes where it answers.

const realLocation = window.location
let assigned: string[] = []
let posts: { url: string; body: unknown }[] = []
let list: BrokerList
let listReads = 0

/** Where the server starts each broker's sign-in, by kind. */
function startFor(broker: string): string {
  const entry = list.brokers.find((b) => b.id === broker)
  if (entry?.sign_in === 'redirect') return `https://broker.example/${broker}/login?state=s`
  return `/${broker}/callback`
}

function serve(
  opts: {
    /** The server refuses the sign-in start with this message. */
    refuseStart?: string
    /** The start request never gets a reply. */
    loseStartReply?: boolean
    /** The server refuses to join the live session with this message. */
    refuseResume?: string
  } = {}
) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
      if (url === '/api/broker/list') {
        listReads += 1
        return json({ status: 'success', data: list })
      }
      if (url === '/auth/csrf-token') return json({ csrf_token: 'tok' })
      if (init?.method === 'POST') {
        const body = init.body ? JSON.parse(String(init.body)) : null
        posts.push({ url, body })
        if (url === '/auth/broker/login') {
          if (opts.loseStartReply) throw new TypeError('Failed to fetch')
          if (opts.refuseStart) return json({ status: 'error', message: opts.refuseStart }, 409)
          return json({ status: 'success', url: startFor(body.broker) })
        }
        if (url === '/auth/broker/resume') {
          if (opts.refuseResume) return json({ status: 'error', message: opts.refuseResume }, 409)
          return json({ status: 'success' })
        }
      }
      return json({}, 404)
    })
  )
}

function renderPage(path = '/broker') {
  // The router reads the address from the stand-in location.
  const url = new URL(path, 'http://127.0.0.1:5000')
  Object.assign(window.location, { pathname: url.pathname, search: url.search, hash: '' })
  return renderWithQuery(<BrokerSelect />)
}

const card = async (id: string) => within(await screen.findByTestId(`broker-card-${id}`))

beforeEach(() => {
  assigned = []
  posts = []
  listReads = 0
  useBrokerStore.getState().clearCapabilities()
  useAuthStore.setState({
    user: { username: 'trader', broker: null, isLoggedIn: true, loginTime: null },
    isAuthenticated: true,
  })
  list = brokerList([
    brokerEntry('zerodha', 'Zerodha', 'redirect'),
    brokerEntry('angel', 'Angel One', 'form'),
    brokerEntry('fivepaisaxts', '5 Paisa (XTS)', 'saved_keys'),
    brokerEntry('fyers', 'Fyers', 'redirect'),
  ])
  const loc = { ...realLocation, origin: 'http://127.0.0.1:5000', search: '' }
  Object.defineProperty(loc, 'href', {
    get: () => assigned[assigned.length - 1] ?? 'http://127.0.0.1:5000/broker',
    set: (v: string) => assigned.push(v),
  })
  Object.defineProperty(window, 'location', { configurable: true, value: loc })
})

afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: realLocation })
  vi.unstubAllGlobals()
})

describe('Select Broker cards', () => {
  it('shows one badge per broker, configured brokers first, with their exchanges', async () => {
    list = brokerList([
      brokerEntry('zerodha', 'Zerodha', 'redirect'),
      saved(brokerEntry('fyers', 'Fyers', 'redirect'), { api_key: 'APP***100' }),
      { ...saved(brokerEntry('angel', 'Angel One', 'form'), {}), active: true },
    ])
    serve()
    renderPage()
    const cards = await screen.findAllByTestId(/^broker-card-/)
    expect(cards.map((c) => c.dataset.testid)).toEqual([
      'broker-card-angel',
      'broker-card-fyers',
      'broker-card-zerodha',
    ])
    expect((await card('angel')).getByText('Active')).toBeInTheDocument()
    expect((await card('fyers')).getByText('Configured')).toBeInTheDocument()
    expect((await card('zerodha')).getByText('Not Configured')).toBeInTheDocument()
    expect(screen.getAllByText('Active')).toHaveLength(1)
    expect((await card('zerodha')).getByText('Exchanges: NSE, BSE, NFO')).toBeInTheDocument()
  })

  it('offers Configure for a broker without keys, opening its configuration', async () => {
    serve()
    renderPage()
    const link = (await card('zerodha')).getByRole('link', { name: 'Configure' })
    expect(link).toHaveAttribute('href', '/broker/config?broker=zerodha')
    expect((await card('zerodha')).queryByRole('button', { name: /login with/i })).toBeNull()
  })

  it('offers Edit keys on a configured broker and Broker Configuration in the header', async () => {
    list = brokerList([saved(brokerEntry('fyers', 'Fyers', 'redirect'), {})])
    serve()
    renderPage()
    expect((await card('fyers')).getByRole('link', { name: 'Edit Fyers keys' })).toHaveAttribute(
      'href',
      '/broker/config?broker=fyers'
    )
    expect(screen.getByRole('link', { name: /Broker Configuration/ })).toHaveAttribute(
      'href',
      '/broker/config'
    )
  })

  it('filters the cards by name', async () => {
    serve()
    renderPage()
    await card('zerodha')
    fireEvent.change(screen.getByRole('textbox', { name: 'Search brokers' }), {
      target: { value: 'ang' },
    })
    expect(screen.getAllByTestId(/^broker-card-/).map((c) => c.dataset.testid)).toEqual([
      'broker-card-angel',
    ])
    fireEvent.change(screen.getByRole('textbox', { name: 'Search brokers' }), {
      target: { value: 'nothing' },
    })
    expect(screen.getByText('No broker matches "nothing".')).toBeInTheDocument()
  })

  it('shows the data subscription note on a configured Zerodha card only', async () => {
    list = brokerList([
      saved(brokerEntry('zerodha', 'Zerodha', 'redirect'), {}),
      brokerEntry('dhan', 'Dhan', 'redirect'),
    ])
    serve()
    renderPage()
    expect(
      (await card('zerodha')).getByText(/Zerodha requires an active Kite Connect/)
    ).toBeInTheDocument()
    expect((await card('dhan')).queryByText(/Dhan requires/)).toBeNull()
  })
})

// A refused broker login comes back as /broker?error=<code>&broker=<id>.
// Only fixed sentences are shown: the address is built by whoever sent it.
describe('A login that came back refused', () => {
  it.each([
    ['login_not_started', /was not started from OpenAlgo, or it took longer than 10 minutes/],
    ['form_expired', /This login form has expired/],
    ['broker_unavailable', /Check its keys under Broker Configuration/],
    ['switch_refused', /so it stayed logged in\. Stop them first, then switch\./],
    ['account_mismatch', /a different account than the client ID saved for this broker/],
    ['signed_out', /Your OpenAlgo sign-in ended while this broker login was in progress/],
    ['login_failed', /The broker login did not complete/],
  ])("shows the %s sentence on that broker's card", async (code, sentence) => {
    list = brokerList([saved(brokerEntry('zerodha', 'Zerodha', 'redirect'), {})])
    serve()
    renderPage(`/broker?error=${code}&broker=zerodha`)
    expect(await (await card('zerodha')).findByText(sentence)).toBeInTheDocument()
  })

  it('never shows text from the address', async () => {
    list = brokerList([saved(brokerEntry('zerodha', 'Zerodha', 'redirect'), {})])
    serve()
    renderPage('/broker?error=%3Cb%3EINJECTED-TEXT%3C%2Fb%3E&broker=zerodha')
    expect(
      await (await card('zerodha')).findByText('The broker login did not complete. Try again.')
    ).toBeInTheDocument()
    expect(screen.queryByText(/INJECTED-TEXT/)).toBeNull()
  })

  it('shows it at the top when no listed broker is named', async () => {
    serve()
    renderPage('/broker?error=login_not_started&broker=nosuchbroker')
    const message = await screen.findByText(/was not started from OpenAlgo/)
    expect(message.closest('[data-testid^="broker-card-"]')).toBeNull()
  })
})

describe('Login with a broker', () => {
  it.each([
    ['zerodha', 'Zerodha', 'redirect', 'https://broker.example/zerodha/login?state=s'],
    ['angel', 'Angel One', 'form', '/angel/callback'],
    ['fivepaisaxts', '5 Paisa (XTS)', 'saved_keys', '/fivepaisaxts/callback'],
  ] as const)('asks the server to start %s and goes where it answers', async (id, name, signIn, to) => {
    list = brokerList([saved(brokerEntry(id, name, signIn), {})])
    serve()
    renderPage()
    fireEvent.click((await card(id)).getByRole('button', { name: `Login with ${name}` }))
    await waitFor(() => expect(assigned).toEqual([to]))
    expect(posts).toEqual([{ url: '/auth/broker/login', body: { broker: id } }])
  })

  it("shows the server's reason on the card when the start is refused", async () => {
    list = brokerList([saved(brokerEntry('fyers', 'Fyers', 'redirect'), {})])
    serve({ refuseStart: 'No API key is saved for Fyers.' })
    renderPage()
    fireEvent.click((await card('fyers')).getByRole('button', { name: 'Login with Fyers' }))
    expect(
      await (await card('fyers')).findByText('No API key is saved for Fyers.')
    ).toBeInTheDocument()
    expect(assigned).toEqual([])
  })
})

// One broker at a time: logging in to another is confirmed first, and the
// server ends the live session only when the new sign-in completes.
describe('Login while another broker is logged in', () => {
  beforeEach(() => {
    list = brokerList([
      { ...saved(brokerEntry('zerodha', 'Zerodha', 'redirect'), {}), active: true },
      saved(brokerEntry('fyers', 'Fyers', 'redirect'), {}),
    ])
  })

  it('asks first, and Cancel ends nothing and starts nothing', async () => {
    serve()
    renderPage()
    fireEvent.click((await card('fyers')).getByRole('button', { name: 'Login with Fyers' }))
    expect(await screen.findByText('End your Zerodha session?')).toBeInTheDocument()
    expect(
      screen.getByText(
        /Signing in to Fyers ends your Zerodha session. Open positions and orders stay with Zerodha./
      )
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByText('End your Zerodha session?')).toBeNull())
    expect(posts).toEqual([])
    expect(assigned).toEqual([])
  })

  it('starts the new sign-in without ending the live session', async () => {
    serve()
    renderPage()
    fireEvent.click((await card('fyers')).getByRole('button', { name: 'Login with Fyers' }))
    expect(await screen.findByText(/if it does not, Zerodha stays connected/)).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Log in to Fyers' }))
    await waitFor(() => expect(assigned).toEqual(['https://broker.example/fyers/login?state=s']))
    // Only the start: the server ends Zerodha's session when Fyers' sign-in completes.
    expect(posts.map((p) => p.url)).toEqual(['/auth/broker/login'])
  })

  it('offers the dashboard on the logged-in broker instead of a second login', async () => {
    serve()
    renderPage()
    expect(
      (await card('zerodha')).getByRole('button', { name: 'Open Dashboard' })
    ).toBeInTheDocument()
    expect((await card('zerodha')).queryByRole('button', { name: /login with/i })).toBeNull()
  })

  it('joins the live session from this browser before opening the dashboard', async () => {
    serve()
    renderPage()
    fireEvent.click((await card('zerodha')).getByRole('button', { name: 'Open Dashboard' }))
    await waitFor(() => expect(assigned).toEqual(['/dashboard']))
    expect(posts.map((p) => p.url)).toEqual(['/auth/broker/resume'])
  })

  it('says why on the card when the live session cannot be joined', async () => {
    serve({ refuseResume: 'Your Zerodha session has ended. Log in again.' })
    renderPage()
    fireEvent.click((await card('zerodha')).getByRole('button', { name: 'Open Dashboard' }))
    expect(
      await (await card('zerodha')).findByText('Your Zerodha session has ended. Log in again.')
    ).toBeInTheDocument()
    expect(assigned).toEqual([])
  })
})

// A sign-in to another broker whose reply is lost leaves the logged-in broker
// connected, and the page shows what the server holds rather than what it
// assumed.
describe('Switching truthfully', () => {
  it('keeps the logged-in broker when the reply is lost, and says so', async () => {
    list = brokerList([
      { ...saved(brokerEntry('zerodha', 'Zerodha', 'redirect'), {}), active: true },
      saved(brokerEntry('fivepaisaxts', '5 Paisa (XTS)', 'saved_keys'), {}),
    ])
    serve({ loseStartReply: true })
    renderPage()
    fireEvent.click(
      (await card('fivepaisaxts')).getByRole('button', { name: 'Login with 5 Paisa (XTS)' })
    )
    const confirm = await screen.findByRole('button', { name: 'Log in to 5 Paisa (XTS)' })
    const readsBefore = listReads
    fireEvent.click(confirm)
    expect(
      await (await card('fivepaisaxts')).findByText('Could not reach OpenAlgo. Try again.')
    ).toBeInTheDocument()
    expect(assigned).toEqual([])
    // Read again: the server still has Zerodha logged in.
    await waitFor(() => expect(listReads).toBeGreaterThan(readsBefore))
    expect((await card('zerodha')).getByText('Active')).toBeInTheDocument()
    expect(
      (await card('fivepaisaxts')).getByRole('button', { name: 'Login with 5 Paisa (XTS)' })
    ).toBeEnabled()
  })
})

// Switching is enforced: Live automation or unsettled orders on the
// logged-in broker refuse it, and the card says why instead of a confirm.
describe('A switch the server refuses', () => {
  it('names what still runs and offers no confirm', async () => {
    const why =
      'Zerodha still has 2 running Live strategies. They are not moved to another broker. First stop the strategies and protection, then switch. Nothing was changed.'
    list = {
      ...brokerList([
        { ...saved(brokerEntry('zerodha', 'Zerodha', 'redirect'), {}), active: true },
        saved(brokerEntry('fyers', 'Fyers', 'redirect'), {}),
      ]),
      switch_refusal: why,
    }
    serve()
    renderPage()
    fireEvent.click((await card('fyers')).getByRole('button', { name: 'Login with Fyers' }))
    expect(await (await card('fyers')).findByText(why)).toBeInTheDocument()
    expect(screen.queryByText('End your Zerodha session?')).toBeNull()
    expect(posts).toEqual([])
    expect(assigned).toEqual([])
  })
})
