/**
 * What happens when an alert fires, beyond the toast.
 *
 * Two things are worth pinning here and neither is a crash. The first is the
 * defaults: sound and the desktop notification on, the two outbound channels
 * off, because a chart alert quietly joining somebody's order-flow feed is not a
 * decision to make on their behalf. The second is that one channel refusing
 * cannot stop the next: a stopped Telegram bot has nothing to do with whether a
 * WhatsApp device is paired.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_DELIVERY, deliverAlert, deliveryOf } from './alertDelivery'

const NOTICE = { title: 'RELIANCE crossing 1264.7', body: 'Crossed on the close', tag: 'a1' }

function context(onProblem = vi.fn()) {
  return { apiKey: 'k', username: 'trader', onProblem }
}

/** A fetch that answers each path with an ok flag, a body status and a reason. */
function fetchWith(
  answers: Record<string, { ok: boolean; status?: string; message?: string }>
) {
  const calls: { url: string; body: Record<string, unknown> }[] = []
  const impl = vi.fn(async (url: string, init?: RequestInit) => {
    const answer = answers[url] ?? { ok: true }
    calls.push({ url, body: JSON.parse(String(init?.body ?? '{}')) })
    return {
      ok: answer.ok,
      json: async () => ({
        ...(answer.status ? { status: answer.status } : {}),
        ...(answer.message ? { message: answer.message } : {}),
      }),
    } as Response
  })
  vi.stubGlobal('fetch', impl)
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('what an alert does by default', () => {
  it('makes a sound and shows a notification, and sends nothing outward', () => {
    expect(DEFAULT_DELIVERY).toEqual({
      sound: true,
      notify: true,
      telegram: false,
      whatsapp: false,
    })
  })

  it('reads an alert stored before delivery was a choice as the default', () => {
    expect(deliveryOf(undefined)).toEqual(DEFAULT_DELIVERY)
    expect(deliveryOf({})).toEqual(DEFAULT_DELIVERY)
    expect(deliveryOf({ autoTitle: true })).toEqual(DEFAULT_DELIVERY)
  })

  it('reads what the trader chose', () => {
    const chosen = { deliver: { sound: false, notify: false, telegram: true, whatsapp: false } }
    expect(deliveryOf(chosen)).toEqual({
      sound: false,
      notify: false,
      telegram: true,
      whatsapp: false,
    })
  })

  it('fills a half-written delivery from the default rather than refusing it', () => {
    // A record from an older release, or one a hand edited.
    expect(deliveryOf({ deliver: { telegram: true } })).toEqual({
      sound: true,
      notify: true,
      telegram: true,
      whatsapp: false,
    })
  })

  it('reads a delivery that is not an object as the default', () => {
    expect(deliveryOf({ deliver: 'yes' })).toEqual(DEFAULT_DELIVERY)
    expect(deliveryOf({ deliver: null })).toEqual(DEFAULT_DELIVERY)
  })
})

describe('sending the message outward', () => {
  const OFF = { sound: false, notify: false, telegram: false, whatsapp: false }

  it('sends nothing at all when nothing outward was asked for', async () => {
    const calls = fetchWith({})
    await deliverAlert(OFF, NOTICE, context())
    expect(calls).toEqual([])
  })

  it('sends to Telegram with the name and the key the API needs', async () => {
    const calls = fetchWith({})
    await deliverAlert({ ...OFF, telegram: true }, NOTICE, context())
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url).toBe('/api/v1/telegram/notify')
    expect(calls[0]?.body).toMatchObject({ apikey: 'k', username: 'trader' })
    expect(String(calls[0]?.body.message)).toContain('RELIANCE crossing 1264.7')
    expect(String(calls[0]?.body.message)).toContain('Crossed on the close')
  })

  it('sends to WhatsApp on its own path', async () => {
    const calls = fetchWith({})
    await deliverAlert({ ...OFF, whatsapp: true }, NOTICE, context())
    expect(calls[0]?.url).toBe('/api/v1/whatsapp/notify')
  })

  it('does not repeat the title when the message says nothing more', async () => {
    const calls = fetchWith({})
    const same = { ...NOTICE, body: NOTICE.title }
    await deliverAlert({ ...OFF, telegram: true }, same, context())
    expect(calls[0]?.body.message).toBe(NOTICE.title)
  })

  it('still sends to WhatsApp when Telegram refused', async () => {
    // The failure this exists for: a stopped bot silently costing the trader
    // the channel that was working.
    const calls = fetchWith({ '/api/v1/telegram/notify': { ok: false } })
    const onProblem = vi.fn()
    await deliverAlert({ ...OFF, telegram: true, whatsapp: true }, NOTICE, context(onProblem))
    expect(calls.map((c) => c.url)).toEqual(['/api/v1/telegram/notify', '/api/v1/whatsapp/notify'])
    expect(onProblem).toHaveBeenCalledTimes(1)
  })

  it('names which channel failed, in words a trader can act on', async () => {
    const calls = fetchWith({ '/api/v1/telegram/notify': { ok: false } })
    const onProblem = vi.fn()
    await deliverAlert({ ...OFF, telegram: true }, NOTICE, context(onProblem))
    expect(calls).toHaveLength(1)
    const said = String(onProblem.mock.calls[0]?.[0])
    expect(said).toContain('Telegram')
    expect(said).not.toMatch(/\b[45]\d\d\b/)
  })

  it('treats a 200 carrying an error status as a failure', async () => {
    // The API answers a refused send with 200 and status error, which is the
    // shape that looks like success to anything checking res.ok alone.
    const onProblem = vi.fn()
    fetchWith({ '/api/v1/whatsapp/notify': { ok: true, status: 'error' } })
    await deliverAlert({ ...OFF, whatsapp: true }, NOTICE, context(onProblem))
    expect(onProblem).toHaveBeenCalledTimes(1)
  })

  it('reports a network failure rather than throwing out of the alert', async () => {
    const onProblem = vi.fn()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('offline')
      })
    )
    await expect(
      deliverAlert({ ...OFF, telegram: true }, NOTICE, context(onProblem))
    ).resolves.toEqual([])
    expect(onProblem).toHaveBeenCalledTimes(1)
  })
})

describe('what it reports back for the log', () => {
  const OFF = { sound: false, notify: false, telegram: false, whatsapp: false }

  it('names the channels that accepted the message', async () => {
    fetchWith({})
    const accepted = await deliverAlert(
      { ...OFF, telegram: true, whatsapp: true },
      NOTICE,
      context()
    )
    expect(accepted).toEqual(['telegram', 'whatsapp'])
  })

  it('leaves out a channel that refused, rather than reporting it sent', async () => {
    // This is the field the log stores. A row claiming Telegram took a message
    // it refused is worse than a row saying nothing went out: it is the exact
    // question somebody opens the log to answer.
    fetchWith({ '/api/v1/telegram/notify': { ok: false } })
    const accepted = await deliverAlert(
      { ...OFF, telegram: true, whatsapp: true },
      NOTICE,
      context()
    )
    expect(accepted).toEqual(['whatsapp'])
  })

  it('names nothing when nothing was asked for', async () => {
    fetchWith({})
    expect(await deliverAlert(OFF, NOTICE, context())).toEqual([])
  })
})

describe('why a send failed', () => {
  const OFF = { sound: false, notify: false, telegram: false, whatsapp: false }
  const NOTICE = { title: 'BHEL crossed 250', body: '', tag: 'a1' }
  const context = (onProblem: (m: string) => void) => ({
    apiKey: 'k',
    username: 'rajandran',
    onProblem,
  })

  /**
   * THE ONE THAT MATTERS, and it is the bug that was reported.
   *
   * Both of the server's refusals used to arrive as the same sentence, "check
   * that a device is paired under WhatsApp", because `post` returned a boolean
   * and the reason was dropped on the floor. A trader whose device IS paired
   * but whose account is not linked read that, went and looked at the device,
   * found it paired, and had nowhere left to go.
   */
  it('tells the trader what the server actually said', async () => {
    const onProblem = vi.fn()
    fetchWith({
      '/api/v1/whatsapp/notify': {
        ok: false,
        status: 'error',
        message: 'Username not found or not linked to WhatsApp',
      },
    })

    await deliverAlert({ ...OFF, whatsapp: true }, NOTICE, context(onProblem))

    const said = String(onProblem.mock.calls[0]?.[0])
    expect(said).toContain('Username not found or not linked to WhatsApp')
    expect(said).toContain('WhatsApp')
    // Still no status codes in front of a trader.
    expect(said).not.toMatch(/\b[45]\d\d\b/)
  })

  it('says something useful when the server gives no reason at all', async () => {
    const onProblem = vi.fn()
    fetchWith({ '/api/v1/telegram/notify': { ok: false } })

    await deliverAlert({ ...OFF, telegram: true }, NOTICE, context(onProblem))

    const said = String(onProblem.mock.calls[0]?.[0])
    expect(said).toContain('Telegram')
    expect(said.length).toBeGreaterThan(20)
  })
})

describe('how the outward channels are attempted', () => {
  const OFF = { sound: false, notify: false, telegram: false, whatsapp: false }
  const NOTICE = { title: 'BHEL crossed 250', body: '', tag: 'a1' }

  /**
   * THE SECOND ONE THAT MATTERS. These ran in turn, and WhatsApp's endpoint
   * defaults `wait_for_delivery` to true, so an alert asking for both waited
   * out the whole Telegram round trip before WhatsApp was even started.
   *
   * The assertion is that BOTH requests are in flight while neither has
   * answered. A sequential implementation cannot satisfy it: its second fetch
   * does not exist until the first resolves.
   */
  it('starts both channels before either has answered', async () => {
    const started: string[] = []
    let releaseTelegram: () => void = () => {}
    const telegramAnswered = new Promise<void>((resolve) => {
      releaseTelegram = resolve
    })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        started.push(String(url))
        if (String(url).includes('telegram')) await telegramAnswered
        return { ok: true, json: async () => ({ status: 'success' }) } as Response
      })
    )

    const sending = deliverAlert(
      { ...OFF, telegram: true, whatsapp: true },
      NOTICE,
      { apiKey: 'k', username: 'rajandran', onProblem: vi.fn() }
    )

    // Let the microtask queue drain without letting Telegram answer.
    await Promise.resolve()
    await Promise.resolve()

    expect(started).toHaveLength(2)
    expect(started.some((one) => one.includes('whatsapp'))).toBe(true)

    releaseTelegram()
    await expect(sending).resolves.toEqual(expect.arrayContaining(['telegram', 'whatsapp']))
  })
})
