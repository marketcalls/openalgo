/**
 * Copy, cut and paste of drawings, across panes and across browser tabs.
 *
 * The draw tier does the work: `DrawingController.copy`, `cut` and `paste`
 * write a namespaced payload (`DRAWING_CLIPBOARD_KEY`) to the system clipboard
 * and keep a copy in a module-level clipboard every controller on the page
 * shares. That shared copy is what makes copy in one pane and paste in another
 * work when the browser refuses the clipboard permission. This module only
 * supplies the port the tier writes through, and the words a trader reads.
 */
import type { ClipboardPort } from 'openalgo-charts/draw'

/**
 * How long a paste waits for the system clipboard before falling back to the
 * copy kept in the page.
 *
 * `navigator.clipboard.readText()` asks for a permission, and until the prompt
 * is answered the promise never settles: the paste key did nothing at all, with
 * nothing to say why. A paste that falls back after a moment is far better than
 * one that hangs. Writing is left alone: it runs inside the key press and lands.
 */
export const CLIPBOARD_READ_MS = 1200

/** The system clipboard with its read bounded, or null when the browser has none. */
export function drawingClipboardPort(
  system?: Pick<Clipboard, 'readText' | 'writeText'> | null
): ClipboardPort | null {
  const clipboard =
    system === undefined ? (typeof navigator === 'undefined' ? null : navigator.clipboard) : system
  if (!clipboard) return null
  return {
    writeText: (text) => clipboard.writeText(text),
    readText: () =>
      new Promise<string>((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error('The system clipboard did not answer')),
          CLIPBOARD_READ_MS
        )
        clipboard.readText().then(
          (text) => {
            clearTimeout(timer)
            resolve(text)
          },
          (error: unknown) => {
            clearTimeout(timer)
            reject(error)
          }
        )
      }),
  }
}

/**
 * Whether a drawing was copied or cut on this page. The right-click menu offers
 * Paste only then: what is on the system clipboard can only be learnt by asking
 * it, which is asynchronous and may raise a permission prompt, and a menu row
 * that opens a prompt is not one anybody wants. Ctrl+V still pastes a copy made
 * in another tab.
 */
let held = false
export const drawingsOnClipboard = (): boolean => held
export function noteDrawingsCopied(): void {
  held = true
}

/** "Drawing" or "3 drawings", for a toast about what was moved. */
export function drawingsLabel(count: number): string {
  return count === 1 ? 'Drawing' : `${count} drawings`
}

/**
 * What a trader is told after a copy or a cut. When the system clipboard was
 * refused the copy still pastes in every chart of this tab, and says so, since
 * another tab will not see it.
 */
export function clipboardMessage(kind: 'copied' | 'cut', count: number, tabOnly: boolean): string {
  const scope = tabOnly ? ' Paste on any chart in this tab.' : ''
  return `${drawingsLabel(count)} ${kind}.${scope}`
}
