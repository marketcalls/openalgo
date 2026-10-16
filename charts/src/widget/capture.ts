/**
 * The two ways a picture of a chart leaves the page, shared by the chart's
 * capture menu (topbar.ts) and the chart grid's (grid-capture.ts): a PNG
 * handed to the browser as a download, and a PNG put on the clipboard. Each
 * reports what really happened, so a menu never says saved or copied for a
 * picture that did not leave.
 */
import { errorText, widgetText, type WidgetTranslationOptions } from './localization';

/**
 * Hand the `picture` to the browser as a PNG named `filename`. False when
 * there is none, or it could not be handed over: a canvas tainted by a
 * cross-origin image refuses to be read, and a runtime without a document
 * cannot click.
 */
export function downloadCanvas(doc: Document, picture: () => HTMLCanvasElement | null, filename: string): boolean {
  try {
    const canvas = picture();
    if (canvas === null) return false;
    const url = canvas.toDataURL('image/png');
    const a = doc.createElement('a');
    a.href = url;
    a.download = filename;
    // In the document for the click: an engine may download only from an anchor that is.
    (doc.body ?? doc.documentElement).appendChild(a);
    a.click();
    a.remove();
    return true;
  } catch {
    return false;
  }
}

/** Whether the runtime can put an image on the clipboard: it needs https or localhost. */
export function canCopyImage(): boolean {
  const g = globalThis as { navigator?: { clipboard?: { write?: unknown } }; ClipboardItem?: unknown };
  return g.navigator?.clipboard?.write !== undefined && g.ClipboardItem !== undefined;
}

/**
 * Put `canvas` on the clipboard as a PNG. `say` hears the outcome in the
 * words a status line or a toast shows: `copied` once the clipboard has it,
 * or why it does not, as an error.
 */
export function copyCanvasImage(text: WidgetTranslationOptions, canvas: HTMLCanvasElement, copied: string,
  say: (message: string, kind: 'info' | 'error') => void): void {
  const fail = (error: unknown): void => say(widgetText(text, 'Copy failed: {error}', { error: errorText(text, error) }), 'error');
  try {
    canvas.toBlob(blob => {
      if (blob === null) { say(widgetText(text, 'The canvas produced no image'), 'error'); return; }
      const Item = (globalThis as unknown as { ClipboardItem: new (parts: Record<string, Blob>) => unknown }).ClipboardItem;
      (globalThis.navigator.clipboard as unknown as { write(items: unknown[]): Promise<void> })
        .write([new Item({ 'image/png': blob })]).then(() => say(copied, 'info'), fail);
    }, 'image/png');
  } catch (error) { fail(error); }
}
