/**
 * What happens when an alert fires, beyond drawing a toast.
 *
 * **An alert is a message to somebody who is not looking at the chart**, so the
 * question a trader is really answering when they set one is "how do you want to
 * be told". The four answers here are the ones the platform can already deliver,
 * and each is chosen per alert rather than once for the whole terminal: a price
 * you are waiting on all week and a level you are watching for the next ten
 * minutes do not deserve the same interruption.
 *
 * The defaults say which of them is the ordinary case. Sound and a desktop
 * notification are on, because between them they reach somebody with the tab
 * behind another window, and neither costs anything or leaves the machine.
 * Telegram and WhatsApp are off, because both send a message out of the building
 * to an account somebody configured for order flow, and a chart alert silently
 * joining that stream is not a thing to decide on a trader's behalf.
 *
 * **A delivery that fails is reported once and never retried.** These run on a
 * price being reached, and a retry loop behind a fired alert is a queue that
 * grows while the market moves. The toast has already happened by the time any
 * of this is attempted, so the alert itself is never lost to a failed send.
 */

import { notifyIfHidden } from './alertNotify'

/** How a trader asked to be told, stored with the alert itself. */
export interface AlertDelivery {
  /** A short tone. On by default: it is the one that works with the tab behind another window. */
  readonly sound: boolean
  /** The operating system's own notification, shown only while the page is hidden. */
  readonly notify: boolean
  readonly telegram: boolean
  readonly whatsapp: boolean
}

/**
 * What an alert does when the trader says nothing.
 *
 * Read by every alert stored before this existed, too: a record with no delivery
 * of its own gets this, which is the behaviour it already had plus the sound.
 */
export const DEFAULT_DELIVERY: AlertDelivery = {
  sound: true,
  notify: true,
  telegram: false,
  whatsapp: false,
}

/** The delivery an alert carries, or the default where it carries none. */
export function deliveryOf(payload: unknown): AlertDelivery {
  const held = (payload as { deliver?: Partial<AlertDelivery> } | undefined)?.deliver
  if (held === undefined || held === null || typeof held !== 'object') return DEFAULT_DELIVERY
  const flag = (name: keyof AlertDelivery): boolean =>
    typeof held[name] === 'boolean' ? (held[name] as boolean) : DEFAULT_DELIVERY[name]
  return {
    sound: flag('sound'),
    notify: flag('notify'),
    telegram: flag('telegram'),
    whatsapp: flag('whatsapp'),
  }
}

/* ── the sound ──────────────────────────────────────────────────────────── */

/**
 * One audio context for the page, built on the first sound and kept.
 *
 * A context per alert is a handle per alert, and a browser caps how many exist
 * before it refuses to make another: a chart left open all day firing a
 * repeating alert would stop making any sound at all, which is the failure mode
 * nobody would connect to the cause.
 */
let context: AudioContext | null = null

function audio(): AudioContext | null {
  if (typeof window === 'undefined') return null
  const Ctor =
    window.AudioContext ??
    (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (typeof Ctor !== 'function') return null
  try {
    context ??= new Ctor()
    return context
  } catch {
    return null
  }
}

/**
 * Let a sound be made later, from the click that is happening now.
 *
 * A browser starts an audio context suspended and only resumes it inside a user
 * gesture, so the first alert to fire hours later cannot start one: the tone
 * would be silently dropped and the trader would believe the alert never fired.
 * Arming an alert is a click, and it is the gesture this borrows.
 */
export function readySound(): void {
  const ctx = audio()
  if (ctx && ctx.state === 'suspended') void ctx.resume().catch(() => {})
}

/**
 * Two short tones, the second higher than the first.
 *
 * Synthesised rather than played from a file. A file is a request that can fail
 * exactly when it is needed, on a page that may have been open since before the
 * network went away, and it is one more asset to serve from an origin that must
 * not be assumed.
 */
export function playAlertSound(): boolean {
  const ctx = audio()
  if (!ctx) return false
  try {
    if (ctx.state === 'suspended') void ctx.resume().catch(() => {})
    const at = ctx.currentTime
    for (const [index, hz] of [880, 1174].entries()) {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.value = hz
      // Shaped rather than switched: a square edge on a sine is a click, and a
      // click is what a broken speaker sounds like.
      const start = at + index * 0.18
      gain.gain.setValueAtTime(0.0001, start)
      gain.gain.exponentialRampToValueAtTime(0.2, start + 0.01)
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.16)
      osc.connect(gain).connect(ctx.destination)
      osc.start(start)
      osc.stop(start + 0.18)
    }
    return true
  } catch {
    return false
  }
}

/* ── the messages ───────────────────────────────────────────────────────── */

/** Everything a send needs that the alert itself does not carry. */
export interface DeliveryContext {
  readonly apiKey: string
  readonly username: string
  /** Reported once per failure, in a trader's words. */
  readonly onProblem: (message: string) => void
}

async function post(path: string, body: Record<string, unknown>): Promise<boolean> {
  // A relative URL, because this application is served from a port, a domain, a
  // subdomain and a container, and an absolute one works for whoever wrote it.
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) return false
  const answer = (await res.json().catch(() => null)) as { status?: string } | null
  return answer?.status !== 'error'
}

/**
 * Send the alert everywhere the trader asked for.
 *
 * Every channel is attempted, and one refusing does not stop the next: a
 * Telegram bot that is stopped has nothing to do with whether the WhatsApp
 * device is paired. Failures are named one by one, because "an alert could not
 * be delivered" leaves a trader with nothing to fix.
 */
export async function deliverAlert(
  delivery: AlertDelivery,
  notice: { title: string; body: string; tag: string },
  context: DeliveryContext
): Promise<string[]> {
  // Named one by one rather than counted, because this is what the log stores
  // and "2 channels" answers nothing six hours later. A channel that refused
  // is simply absent: the row then says the alert fired and reached nobody,
  // which is a different thing from the alert not firing.
  const accepted: string[] = []

  if (delivery.sound && playAlertSound()) accepted.push('sound')
  if (delivery.notify && notifyIfHidden(notice)) accepted.push('notification')

  const message =
    notice.body && notice.body !== notice.title ? `${notice.title}\n${notice.body}` : notice.title

  if (delivery.telegram) {
    try {
      const sent = await post('/api/v1/telegram/notify', {
        apikey: context.apiKey,
        username: context.username,
        message,
      })
      if (sent) accepted.push('telegram')
      else {
        context.onProblem(
          'The alert fired, but Telegram did not take the message. Check that the bot is running and your account is linked under Telegram.'
        )
      }
    } catch {
      context.onProblem('The alert fired, but Telegram could not be reached.')
    }
  }

  if (delivery.whatsapp) {
    try {
      const sent = await post('/api/v1/whatsapp/notify', {
        apikey: context.apiKey,
        username: context.username,
        message,
      })
      if (sent) accepted.push('whatsapp')
      else {
        context.onProblem(
          'The alert fired, but WhatsApp did not take the message. Check that a device is paired under WhatsApp.'
        )
      }
    } catch {
      context.onProblem('The alert fired, but WhatsApp could not be reached.')
    }
  }

  return accepted
}
