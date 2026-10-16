import { el } from './ui.js';
import { autosave } from './persist.js';

let app;
export function initClipboard(a) { app = a; }

// ── drawing clipboard ──────────────────────────────────────────────────
//
// The engine installs no key listeners, so the chords are the host's. Both
// charts have their own controller and both share one in-memory clipboard,
// which is what makes copy-here / paste-there work even when the browser
// refuses the OS clipboard permission.

/**
 * The system clipboard, with the read half bounded.
 *
 * `navigator.clipboard.readText()` needs a permission Chrome asks for with
 * a popup, and until that popup is answered the promise simply never
 * settles: pressing the paste chord did nothing at all, forever, with no
 * error to report. A paste that falls back is far better than a paste that
 * hangs, and the engine's in-memory clipboard is shared by every controller
 * on the page, so a timed-out read still pastes what was copied here. The
 * write half is left alone: it runs inside the key gesture and succeeds.
 */
export const CLIPBOARD_READ_MS = 1200;
export const clipboardPort = (typeof navigator !== 'undefined' && navigator.clipboard)
  ? {
      writeText: (text) => navigator.clipboard.writeText(text),
      readText: () => Promise.race([
        navigator.clipboard.readText(),
        new Promise((_, reject) => setTimeout(
          () => reject(new Error('system clipboard read not permitted')), CLIPBOARD_READ_MS)),
      ]),
    }
  : null;

export const activeDraw = () => (app.focusPane === 2 && app.draw2 ? app.draw2 : app.draw);
export const paneName = (d) => (d === app.draw2 ? 'Chart 2' : 'Chart 1');
export const canClip = () => {
  const d = activeDraw();
  return Boolean(d) && typeof d.copy === 'function';
};

/** Append "this tab only" when the payload never reached the OS clipboard. */
export function clipScope(d) {
  const err = typeof d.clipboard === 'function' ? d.clipboard().lastError() : null;
  return err ? ' (this tab only: ' + String(err).replace(/^Error:\s*/, '') + ')' : '';
}

export async function clipboardAction(action) {
  const d = activeDraw();
  if (!d || typeof d.copy !== 'function') {
    el('status').textContent = 'this dist/ has no drawing clipboard';
    return;
  }
  try {
    if (action === 'copy') {
      const ok = await d.copy();
      el('status').textContent = ok
        ? 'copied from ' + paneName(d) + clipScope(d)
        : 'select a drawing first';
      return;
    }
    if (action === 'cut') {
      const ok = await d.cut();
      el('status').textContent = ok
        ? 'cut from ' + paneName(d) + clipScope(d)
        : 'select a drawing first';
      if (ok && d === app.draw) autosave();
      return;
    }
    const made = await d.paste();
    el('status').textContent = made.length
      ? 'pasted ' + made.length + ' into ' + paneName(d) + clipScope(d)
      : 'nothing of ours on the clipboard';
    if (made.length && d === app.draw) autosave();
  } catch (e) {
    el('status').textContent = 'clipboard: ' + (e && e.message ? e.message : e);
  }
}
