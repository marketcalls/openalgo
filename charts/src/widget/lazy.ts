/**
 * The parts of the widget that load on first use.
 *
 * A plain widget never opens the shortcuts editor, the Layouts menu, the
 * indicator templates list or the chart data dialog, never shows a grid's
 * bar or its menus, and persists nothing to IndexedDB, so none of them rides
 * in the tier's own file: the build writes each one beside it
 * (rollup.config.js) and `import()` fetches it the first time it is needed.
 * The script-tag build is the exception: a classic script cannot share a
 * chunk, so its widget file carries the parts and `import()` settles with no
 * fetch.
 * Once a part has arrived it is used at once, as if it had been bundled in;
 * until then the request waits for it. A load that fails is reported where
 * the user asked, and forgotten, so the next request asks again rather than
 * waiting on a promise that has already failed. A browser keeps a failed
 * module fetch for the life of the page, so there the answer stays the same
 * until the page reloads; a loader that retries gets its retry.
 *
 * Each part is declared beside the code that uses it. The tier entry exports
 * none of this.
 */
import { inTextField } from './context';
import { errorText, widgetText, type WidgetTranslationOptions } from './localization';

export interface LazyPart<T> {
  /** The module once it has arrived, else null. */
  now: T | null;
  /** Fetch it once: every caller shares the load in flight. */
  load(): Promise<T>;
}

/** The parts declared so far, which `loadWidgetParts` fetches. */
const declared: Array<LazyPart<unknown>> = [];

/** A part fetched with `load` on first use. */
export function lazyPart<T>(load: () => Promise<T>): LazyPart<T> {
  let loading: Promise<T> | null = null;
  const part: LazyPart<T> = {
    now: null,
    load: () => (loading ??= load().then(module => (part.now = module), (error: unknown) => {
      loading = null;
      throw error;
    })),
  };
  declared.push(part);
  return part;
}

/**
 * What one control, or controls whose parts would replace each other, has on
 * its way: only its latest request is answered, once, however often it was
 * pressed while the part loaded.
 */
export interface PartSlot { waiting: object | null }

/**
 * A user's request for a part, from a control of the page. Once the part has
 * arrived a press opens it at once; until then the answer comes later, and
 * by then the user may have asked for something else or moved on.
 */
interface PartAsk {
  readonly slot: PartSlot;
  readonly doc: Document;
  /** The control that asked: pressing it again is asking again, not moving on. */
  readonly from?: Element | null | undefined;
}

/**
 * Run `use` with a part: at once when it has arrived, else when it does,
 * unless `live` says by then that whoever asked has gone. A failed load goes
 * to `failed` on the same terms. A request a user made (`ask`) is dropped
 * when a later one from its slot replaced it, and opens nothing when the
 * user moved on while it loaded: a press elsewhere, Escape, or typing into
 * another field. A part bundled in would have opened before any of those,
 * and one arriving after them would take the focus from what the user
 * turned to. A failure is still told, since the user did ask.
 */
export function usePart<T>(part: LazyPart<T>, use: (module: T) => void, failed: (error: unknown) => void, live: () => boolean,
  ask?: PartAsk): void {
  if (part.now !== null) { use(part.now); return; }
  let settle = (): boolean | null => (live() ? true : null);
  if (ask !== undefined) {
    const { slot, doc, from } = ask;
    const me = slot.waiting = {};
    const focused = doc.activeElement;
    let away = false;
    const press = (event: Event): void => { if (from?.contains(event.target as Node) !== true) away = true; };
    const key = (event: Event): void => { if ((event as KeyboardEvent).key === 'Escape') away = true; };
    doc.addEventListener('pointerdown', press, true);
    doc.addEventListener('keydown', key, true);
    settle = () => {
      doc.removeEventListener('pointerdown', press, true);
      doc.removeEventListener('keydown', key, true);
      if (slot.waiting !== me) return null;
      slot.waiting = null;
      if (!live()) return null;
      const now = doc.activeElement;
      return !away && (now === focused || !inTextField(now));
    };
  }
  part.load().then(module => { if (settle() === true) use(module); }, (error: unknown) => { if (settle() !== null) failed(error); });
}

/** What a part that could not load says: its name and the reason. */
export function partFailed(text: WidgetTranslationOptions, name: string, error: unknown): string {
  return widgetText(text, '{name} could not load: {error}', { name, error: errorText(text, error) });
}

/**
 * Fetch every part declared so far. The unit tests open the parts the way a
 * page does once they have arrived; the late and failed loads have tests of
 * their own.
 */
export function loadWidgetParts(): Promise<unknown[]> {
  return Promise.all(declared.map(part => part.load()));
}
