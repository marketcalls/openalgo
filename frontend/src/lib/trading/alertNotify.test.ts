/**
 * Telling somebody an alert fired when they are not looking at the tab.
 *
 * Every test here is about a case where the wrong behaviour is silence. A toast
 * is drawn into a page a hidden tab never paints, so an alert delivered as a
 * toast alone reaches nobody until they come back and find it already gone,
 * which is the opposite of what an alert is for.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { askToNotify, notificationState, notifyIfHidden } from './alertNotify'

/** The browser's notification surface, as much of it as this module touches. */
function withNotification(
  permission: NotificationPermission,
  request?: () => Promise<NotificationPermission>
) {
  const shown: { title: string; options?: NotificationOptions }[] = []
  class Fake {
    public onclick: (() => void) | null = null
    public static permission: NotificationPermission = permission
    public static requestPermission =
      request ?? (async () => Fake.permission)
    constructor(title: string, options?: NotificationOptions) {
      shown.push({ title, options })
    }
    close() {}
  }
  vi.stubGlobal('Notification', Fake)
  return shown
}

function hide(state: DocumentVisibilityState) {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue(state)
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const NOTICE = { title: 'RELIANCE crossing 1264.7', body: 'Crossed on the close', tag: 'a1' }

describe('showing a notification', () => {
  it('shows one when the tab is hidden and the trader allowed it', () => {
    const shown = withNotification('granted')
    hide('hidden')
    expect(notifyIfHidden(NOTICE)).toBe(true)
    expect(shown).toHaveLength(1)
    expect(shown[0]?.title).toBe(NOTICE.title)
    expect(shown[0]?.options?.body).toBe(NOTICE.body)
  })

  it('shows nothing while the trader is looking at the chart', () => {
    // The toast is already the right message for somebody watching, and an
    // application that throws a second copy at them gets muted for good.
    const shown = withNotification('granted')
    hide('visible')
    expect(notifyIfHidden(NOTICE)).toBe(false)
    expect(shown).toHaveLength(0)
  })

  it('shows nothing when the trader said no', () => {
    const shown = withNotification('denied')
    hide('hidden')
    expect(notifyIfHidden(NOTICE)).toBe(false)
    expect(shown).toHaveLength(0)
  })

  it('shows nothing when the trader has not been asked', () => {
    // `default` is not a yes. Constructing one here throws in a real browser.
    const shown = withNotification('default')
    hide('hidden')
    expect(notifyIfHidden(NOTICE)).toBe(false)
    expect(shown).toHaveLength(0)
  })

  it('carries a tag, so an alert firing every bar is one notification', () => {
    const shown = withNotification('granted')
    hide('hidden')
    notifyIfHidden(NOTICE)
    expect(shown[0]?.options?.tag).toBe('a1')
  })

  it('does not throw where the browser has no notifications at all', () => {
    vi.stubGlobal('Notification', undefined)
    hide('hidden')
    expect(() => notifyIfHidden(NOTICE)).not.toThrow()
    expect(notifyIfHidden(NOTICE)).toBe(false)
    expect(notificationState()).toBe('unsupported')
  })

  it('does not throw when the browser refuses to construct one', () => {
    // Some browsers only allow one from a service worker. The toast has already
    // happened, so there is nothing to fall back to and nothing to report.
    class Refuses {
      static permission: NotificationPermission = 'granted'
      static requestPermission = async () => 'granted' as NotificationPermission
      constructor() {
        throw new Error('Notification requires a service worker')
      }
    }
    vi.stubGlobal('Notification', Refuses)
    hide('hidden')
    expect(() => notifyIfHidden(NOTICE)).not.toThrow()
    expect(notifyIfHidden(NOTICE)).toBe(false)
  })
})

describe('asking to notify', () => {
  it('asks once when the trader has not answered', async () => {
    const asked = vi.fn(async () => 'granted' as NotificationPermission)
    withNotification('default', asked)
    expect(await askToNotify()).toBe(true)
    expect(asked).toHaveBeenCalledTimes(1)
  })

  it('does not ask again when the answer is already yes', async () => {
    const asked = vi.fn(async () => 'granted' as NotificationPermission)
    withNotification('granted', asked)
    expect(await askToNotify()).toBe(true)
    expect(asked).not.toHaveBeenCalled()
  })

  it('does not ask again when the answer was no', async () => {
    // Asking a second time is what gets an origin permanently blocked.
    const asked = vi.fn(async () => 'denied' as NotificationPermission)
    withNotification('denied', asked)
    expect(await askToNotify()).toBe(false)
    expect(asked).not.toHaveBeenCalled()
  })

  it('takes a refusal as an answer rather than an error', async () => {
    const asked = vi.fn(async () => 'denied' as NotificationPermission)
    withNotification('default', asked)
    expect(await askToNotify()).toBe(false)
  })

  it('does not throw where asking itself throws', async () => {
    const asked = vi.fn(async () => {
      throw new Error('requires a user gesture')
    })
    withNotification('default', asked as never)
    await expect(askToNotify()).resolves.toBe(false)
  })

  it('answers no where the browser has no notifications', async () => {
    vi.stubGlobal('Notification', undefined)
    await expect(askToNotify()).resolves.toBe(false)
  })
})
