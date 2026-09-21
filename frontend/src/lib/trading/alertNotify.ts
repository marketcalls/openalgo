/**
 * Telling a trader an alert fired when they are not looking at the tab.
 *
 * **A toast is a message to somebody who is already watching.** It is drawn
 * into a page that a hidden tab never paints and a minimized window never
 * shows, so an alert delivered as a toast alone is an alert nobody receives
 * until they come back and find it gone. That is the opposite of what an alert
 * is for: the whole point is to be told about a price you are not watching.
 *
 * So a fired alert goes to the operating system's own notification when the
 * page is hidden, and stays a toast when it is not. Two rules, both of which
 * exist because the other behaviour is worse:
 *
 * - **Only when hidden.** A desktop notification thrown while the trader is
 *   looking at the chart is a second copy of something already on screen, and
 *   an application that does that gets its notifications turned off for good.
 * - **Never asked for out of nowhere.** Permission is requested when an alert
 *   is armed, which is a click the trader just made and the one moment the
 *   request explains itself. Asking on page load is how a permission prompt
 *   becomes a thing people dismiss without reading.
 *
 * Everything here is written so that a browser with no notification support, a
 * trader who said no, and a trader who never answered all behave the same way:
 * the toast still happens and nothing throws. A denied permission is not an
 * error, it is an answer.
 */

/** What a fired alert says, in the two lines a notification has room for. */
export interface AlertNotice {
  readonly title: string
  readonly body: string
  /**
   * Collapses repeats of the same alert into one notification.
   *
   * An alert that fires on every bar of a fast interval would otherwise stack a
   * notification per bar, and the trader would dismiss a column of them to find
   * out that all of them said the same thing.
   */
  readonly tag: string
}

/**
 * Whether this browser can show one at all.
 *
 * The value is tested and not the key. `'Notification' in window` is true for a
 * window carrying the name with nothing behind it, which is what a test double
 * and a stripped embedding both look like, and the next line then reads
 * `.permission` off undefined and throws out of the middle of delivering an
 * alert. A missing notification is a thing this module handles; an exception
 * thrown past the toast is not.
 */
export function notificationsSupported(): boolean {
  return typeof window !== 'undefined' && typeof window.Notification === 'function'
}

/**
 * Whether a notification would be shown if one fired now.
 *
 * `'default'` means the trader has not been asked, which is not the same as no:
 * it is why `askToNotify` exists and why it is called when an alert is armed.
 */
export function notificationState(): NotificationPermission | 'unsupported' {
  if (!notificationsSupported()) return 'unsupported'
  return Notification.permission
}

/**
 * Ask, once, at the moment an alert is armed.
 *
 * Returns whether a notification can now be shown, so a caller can say plainly
 * that alerts will only appear while the tab is open. It never throws and never
 * asks twice: a decision already made is returned as it stands, because asking
 * again is what a browser permanently blocks an origin for.
 */
export async function askToNotify(): Promise<boolean> {
  if (!notificationsSupported()) return false
  if (Notification.permission === 'granted') return true
  if (Notification.permission === 'denied') return false
  try {
    return (await Notification.requestPermission()) === 'granted'
  } catch {
    // Older browsers take a callback instead of returning a promise, and some
    // refuse outside a user gesture. Either way the answer is no, and a toast
    // is still shown.
    return false
  }
}

/**
 * Show one, if the page is hidden and the trader has allowed it.
 *
 * Returns whether the notification was shown, so the caller knows whether the
 * toast was the only delivery. Visible pages get nothing from here on purpose:
 * the toast is already the right message for somebody looking at the chart.
 */
export function notifyIfHidden(notice: AlertNotice): boolean {
  if (typeof document === 'undefined' || document.visibilityState !== 'hidden') return false
  if (!notificationsSupported() || Notification.permission !== 'granted') return false
  try {
    const shown = new Notification(notice.title, {
      body: notice.body,
      tag: notice.tag,
      // The page is hidden, so this is the first the trader hears of it.
      // Renotify would be wrong: the tag exists to collapse repeats, not to
      // make each repeat ring again.
      requireInteraction: false,
    })
    // Bring the chart forward when the notification is clicked, because the
    // next thing a trader wants after being told a price was reached is the
    // price.
    shown.onclick = () => {
      try {
        window.focus()
        shown.close()
      } catch {
        // A browser that refuses to focus is not a failure worth reporting:
        // the trader has already been told what they needed to know.
      }
    }
    return true
  } catch {
    // Some browsers refuse to construct one outside a service worker. The
    // toast has already been shown, so there is nothing to report and nothing
    // to fall back to.
    return false
  }
}
