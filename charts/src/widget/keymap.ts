/**
 * The widget keymap: one place every chord the shell, the rail and the
 * dialogs answer to is registered, resolved and listed.
 *
 * The engine has a `ShortcutManager` of its own for chart navigation (arrows,
 * zoom, fit) keyed on physical key codes, and the draw tier answers
 * `matchDrawingShortcut` and `keyToDrawingAction` from `e.key`. Neither knows
 * about the other, about the rail's focus, or about a dialog being open, so
 * the two collide silently: the tier's Alt+V picks a vertical line and the
 * engine's Alt+V toggles the vertical grid, and whichever listener ran first
 * won. This layer runs before both, in the capture phase, with scopes that
 * say where a chord applies, and it records every collision so the shortcuts
 * panel can show the truth rather than the intent.
 *
 * Bindings are written the way the draw tier writes them (`Alt+T`, `Mod+Z`,
 * `?`), from the key the event reports, not the physical code: a chord that
 * has to be read out to a user is a character, and `?` has no code that means
 * the same thing on every layout.
 *
 * A binding registered with a `command` can be moved to another chord by the
 * user. The command is the stable name, because the chord is exactly what
 * changes: a saved override says `tool:trend-line` goes to `Alt+Y`, and it
 * still means that after a release adds or reorders bindings. The engine's
 * commands are rebound here too, as `chart:<command>` in the engine's own
 * code-based grammar, so one editor and one saved record cover both.
 *
 * The class touches no DOM until `attach`, and `handle` takes any object
 * with the key fields, so every rule is testable without a browser.
 */
import { isReservedCombo, normalizeCombo, type ShortcutListItem } from 'openalgo-charts';
// The engine's own platform test, so its key hints and the widget's never
// disagree on Cmd or Ctrl. A pure helper, so the path inlines just it.
import { detectMac } from '../input/shortcuts';
import { inTextField, type WidgetContext } from './context';
import { lazyPart, partFailed, usePart, type PartSlot } from './lazy';
import { widgetText } from './localization';

/**
 * Where a binding applies. `global` always; `widget` while the pointer or the
 * focus is inside the widget; `chart` while either is on the chart itself;
 * `rail` while the focus is in the tool rail; `overlay` while a dialog or a
 * menu is open, when nothing else fires. The shell decides which are active
 * (see `setScopes`); they are tried narrowest first.
 */
export type KeyScope = 'global' | 'widget' | 'chart' | 'rail' | 'overlay' | (string & {});

/** The event fields the keymap reads. A DOM `KeyboardEvent` satisfies it. */
export interface KeyEventLike {
  key: string;
  code?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  target?: unknown;
  preventDefault?(): void;
  stopPropagation?(): void;
  /** Used while a chord is being captured, so no other listener on the document sees the press. */
  stopImmediatePropagation?(): void;
}

/**
 * What runs for a chord. Return `false` to decline: the next binding on the
 * same chord (or the engine, or the browser) gets the key. Anything else
 * claims it, and the event is prevented and stopped.
 */
export type KeyAction = (e: KeyEventLike) => boolean | void;

export interface KeyBindingOptions {
  /** Shown in the shortcuts panel. Defaults to the chord itself. */
  label?: string;
  /** Section of the shortcuts panel. Default `Widget`. */
  group?: string;
  /** Gate read at key time; a false skips the binding without declining for others. */
  when?: (() => boolean) | undefined;
  /** Fire even when the focus is in a text field. Default false. */
  inText?: boolean;
  /** Keep out of the shortcuts panel (a binding that only exists to layer under another). */
  hidden?: boolean | undefined;
  /**
   * Declares that this binding shares its chord on purpose: it declines when
   * it does not apply, so an earlier widget binding or the engine's own
   * command on the same chord still fires. Without it a second registration
   * on a chord, or one on a chord the engine binds, is recorded as a conflict.
   */
  layered?: boolean | undefined;
  /**
   * The stable name of what the binding does (`undo`, `tool:trend-line`),
   * unique among live bindings. `rebind`, `reset` and a saved override name
   * the binding by it. A binding without one cannot be rebound. The `chart:`
   * prefix is kept for the engine's commands.
   */
  command?: string;
  /**
   * Whether a user may move the binding to another chord. Default: true when
   * it has a `command`. False keeps a key that a convention or a neighbouring
   * control depends on where it is: Escape, Enter, the arrows.
   */
  rebindable?: boolean;
}

export interface KeyBinding {
  /** Registration number, in the order bindings were made. */
  readonly id: number;
  /** Canonical chord in force (see `parseKeyCombo`): the default, or the user's. `''` while unbound. */
  readonly combo: string;
  /** The chord it was registered with, which `reset` returns it to. */
  readonly defaultCombo: string;
  /** Its stable name, or null for a binding registered without one. */
  readonly command: string | null;
  /** Whether `rebind` may move it. */
  readonly rebindable: boolean;
  readonly scope: KeyScope;
  readonly label: string;
  readonly group: string;
  readonly hidden: boolean;
  readonly inText: boolean;
  /** Shares its chord deliberately; see `KeyBindingOptions.layered`. */
  readonly layered: boolean;
  readonly action: KeyAction;
  readonly when?: (() => boolean) | undefined;
}

export interface KeyConflict {
  readonly combo: string;
  readonly scope: KeyScope;
  /** Label of the binding that fires. */
  readonly kept: string;
  /** Label of the binding that never will while the kept one claims. */
  readonly shadowed: string;
  /** `widget` for two widget bindings, `chart` when the engine's own keymap loses the chord. */
  readonly source: 'widget' | 'chart';
}

/** A binding that holds a chord, as a rebind or `conflictsFor` reports it. */
export interface KeyChordUse {
  /** Its command (`chart:<command>` for the engine's), or null for a binding registered without one. */
  readonly command: string | null;
  readonly label: string;
  readonly group: string;
  readonly source: 'widget' | 'chart';
  /** False for a fixed binding, which no rebind can take the chord from. */
  readonly rebindable: boolean;
}

/** What `rebind` or `reset` did. */
export interface KeyRebindResult {
  /** True when the command now has the chord asked for. */
  readonly ok: boolean;
  /**
   * Why it did not: the command is `unknown` or `fixed`, the chord is
   * `invalid` or `reserved` by the browser, or it is `taken` by the bindings
   * in `conflicts`. Absent on success.
   */
  readonly reason?: 'unknown' | 'fixed' | 'invalid' | 'reserved' | 'taken';
  /** The bindings on the chord: what stopped the change, or, with `replace`, what gave the chord up. */
  readonly conflicts: readonly KeyChordUse[];
}

/**
 * The user's chords by command, JSON-safe, as `overrides()` returns them and
 * `applyOverrides` takes them. A widget command maps to one chord in the key
 * grammar (`Alt+y`); an engine command (`chart:zoomIn`) to one chord or
 * several in the engine's code grammar (`Alt+KeyZ`). Null unbinds.
 */
export type KeymapOverrides = Readonly<Record<string, string | readonly string[] | null>>;

/** What `onChange` reports: the commands whose chord moved. */
export interface KeymapChange {
  readonly commands: readonly string[];
}

/** Where the widget keeps the user's chords in its storage. */
export const KEYMAP_KEY = 'keymap';

/** The prefix that names an engine command among the keymap's own. */
const CHART = 'chart:';

const MOD_ALIASES: Readonly<Record<string, 'Mod' | 'Alt' | 'Shift'>> = {
  mod: 'Mod', ctrl: 'Mod', control: 'Mod', cmd: 'Mod', command: 'Mod', meta: 'Mod', win: 'Mod',
  alt: 'Alt', option: 'Alt', opt: 'Alt',
  shift: 'Shift',
};

const KEY_ALIASES: Readonly<Record<string, string>> = {
  esc: 'Escape', escape: 'Escape', del: 'Delete', delete: 'Delete', backspace: 'Backspace',
  enter: 'Enter', return: 'Enter', tab: 'Tab', space: 'Space', spacebar: 'Space',
  left: 'ArrowLeft', right: 'ArrowRight', up: 'ArrowUp', down: 'ArrowDown',
  arrowleft: 'ArrowLeft', arrowright: 'ArrowRight', arrowup: 'ArrowUp', arrowdown: 'ArrowDown',
  home: 'Home', end: 'End', pageup: 'PageUp', pagedown: 'PageDown', insert: 'Insert',
  plus: '+', minus: '-', question: '?', slash: '/', period: '.', comma: ',',
};

const MODIFIER_KEYS = new Set(['Shift', 'Control', 'Alt', 'Meta', 'OS', 'AltGraph', 'CapsLock', 'Fn']);

const MOD_ORDER = ['Mod', 'Alt', 'Shift'];

/** Canonical key name for one written key part. */
function canonicalKey(raw: string): string {
  const lower = raw.toLowerCase();
  if (KEY_ALIASES[lower] !== undefined) return KEY_ALIASES[lower];
  if (/^f([1-9]|1[0-2])$/.test(lower)) return lower.toUpperCase();
  if (raw.length === 1) return /[a-z]/i.test(raw) ? lower : raw;
  return raw;
}

/**
 * Canonical form of a chord (`'shift+alt+t'` -> `'Alt+Shift+t'`), or `''`
 * when the spec is not one. Letters are lower-cased and keep Shift; a symbol
 * or a digit drops it, because the character already says which key was
 * pressed with Shift held. Ctrl, Cmd and Meta all read as `Mod`.
 */
export function parseKeyCombo(spec: string): string {
  const s = spec.trim();
  if (s === '') return '';
  let key: string;
  let modParts: string[];
  // The key itself may be '+': alone, or after a modifier as `Ctrl++`.
  if (s === '+') {
    key = '+';
    modParts = [];
  } else if (s.endsWith('++')) {
    key = '+';
    modParts = s.slice(0, -2).split('+').map((p) => p.trim());
  } else {
    const parts = s.split('+').map((p) => p.trim());
    key = parts[parts.length - 1]!; // a split always returns at least one part
    modParts = parts.slice(0, -1);
  }
  // A bare modifier is not a chord: nothing is pressed with it.
  if (key === '' || MOD_ALIASES[key.toLowerCase()] !== undefined) return '';
  const mods = new Set<string>();
  for (const p of modParts) {
    const m = MOD_ALIASES[p.toLowerCase()];
    if (m === undefined) return '';
    mods.add(m);
  }
  key = canonicalKey(key);
  if (key.length === 1 && !/[a-z]/.test(key)) mods.delete('Shift');
  const ordered = MOD_ORDER.filter((m) => mods.has(m));
  return [...ordered, key].join('+');
}

/** The canonical chord an event stands for, or `''` for a bare modifier press. */
export function eventKeyCombo(e: KeyEventLike): string {
  let key = e.key ?? '';
  if (key === '' || key === 'Unidentified' || MODIFIER_KEYS.has(key)) return '';
  if (key === ' ' || key === 'Spacebar') key = 'Space';
  if (key === 'Esc') key = 'Escape';
  if (key === 'Del') key = 'Delete';
  // Alt turns a letter into a symbol on some layouts and platforms; the
  // physical key still says which letter was meant.
  const code = e.code ?? '';
  if (e.altKey === true && /^Key[A-Z]$/.test(code)) key = code.slice(3).toLowerCase();
  const mods: string[] = [];
  if (e.ctrlKey === true || e.metaKey === true) mods.push('Mod');
  if (e.altKey === true) mods.push('Alt');
  if (key.length === 1) {
    if (/[a-z]/i.test(key)) {
      key = key.toLowerCase();
      if (e.shiftKey === true) mods.push('Shift');
    }
  } else if (e.shiftKey === true) {
    mods.push('Shift');
  }
  return [...mods, key].join('+');
}

const DISPLAY_KEYS: Readonly<Record<string, string>> = {
  Escape: 'Esc', Delete: 'Del', ArrowLeft: 'Left', ArrowRight: 'Right', ArrowUp: 'Up', ArrowDown: 'Down',
};

/** A chord as a user reads it: `Ctrl+Shift+Z`, or `Cmd+Shift+Z` on a Mac. */
export function formatKeyCombo(combo: string, isMac: boolean = detectMac()): string {
  const c = parseKeyCombo(combo);
  if (c === '') return '';
  const parts = c.split('+');
  const key = parts[parts.length - 1]!; // a split always returns at least one part
  const mods = parts.slice(0, -1).map((m) => (m === 'Mod' ? (isMac ? 'Cmd' : 'Ctrl') : m === 'Alt' ? (isMac ? 'Opt' : 'Alt') : 'Shift'));
  const shown = DISPLAY_KEYS[key] ?? (key.length === 1 ? key.toUpperCase() : key);
  return [...mods, shown].join('+');
}

/**
 * The characters a US layout gives each punctuation and digit code, plain and
 * with Shift. The engine's own display reads codes the same way, so the two
 * grammars meet on the layout both of them assume.
 */
const US_CODES: Readonly<Record<string, string>> = {
  Equal: '=+', Minus: '-_', Slash: '/?', Comma: ',<', Period: '.>', Semicolon: ';:', Quote: '\'"',
  BracketLeft: '[{', BracketRight: ']}', Backslash: '\\|', Backquote: '`~',
  Digit1: '1!', Digit2: '2@', Digit3: '3#', Digit4: '4$', Digit5: '5%', Digit6: '6^', Digit7: '7&', Digit8: '8*', Digit9: '9(', Digit0: '0)',
  NumpadAdd: '++', NumpadSubtract: '--', NumpadMultiply: '**', NumpadDivide: '//', NumpadDecimal: '..',
};

/**
 * The engine's code-based combo (`Alt+KeyV`, `Mod+Shift+KeyS`, `Equal`) in
 * this keymap's key-based form, so the two can be compared. Layout-specific
 * symbols are read as a US layout would produce them, which is what the
 * engine's own display does too.
 */
export function fromChartCombo(combo: string): string {
  const parts = combo.split('+').map((p) => p.trim()).filter((p) => p !== '');
  if (parts.length === 0) return '';
  // parts is not empty, and each match's one group is not optional.
  const code = parts[parts.length - 1]!;
  const mods = parts.slice(0, -1).map((m) => (m === 'Alt' ? 'Alt' : m === 'Shift' ? 'Shift' : 'Mod'));
  let key: string;
  const letter = /^Key([A-Z])$/.exec(code);
  const pad = /^Numpad([0-9])$/.exec(code);
  if (letter !== null) key = letter[1]!.toLowerCase();
  else if (pad !== null) key = pad[1]!;
  else if (US_CODES[code] !== undefined) key = US_CODES[code][mods.includes('Shift') ? 1 : 0]!; // every entry is two characters
  else if (code === 'NumpadEnter') key = 'Enter';
  else key = code;
  return parseKeyCombo([...mods, key].join('+'));
}

/** Whether the browser keeps a key-form chord for itself, the engine's `isReservedCombo` read in this grammar. */
function reservedKey(combo: string): boolean {
  const parts = combo.split('+');
  const key = parts.pop() ?? '';
  return /^[a-z]$/.test(key) && isReservedCombo([...parts, 'Key' + key.toUpperCase()].join('+'));
}

/** The scopes that are live together, so a binding in one competes with a binding in another. */
const NESTED = new Set<KeyScope>(['global', 'widget', 'chart']);
const meets = (a: KeyScope, b: KeyScope): boolean => a === b || (NESTED.has(a) && NESTED.has(b));
/** A rail or overlay binding never stands between the user and the chart's own commands. */
const reachesChart = (scope: KeyScope): boolean => scope !== 'rail' && scope !== 'overlay';

/** The slice of the engine's shortcut manager the keymap reads, and drives when the user rebinds. */
export interface ChartShortcutSource {
  list(): ShortcutListItem[];
  /** With `disable` and `resetBinding`, what makes the chart's commands rebindable from the keymap. */
  setBinding?(command: string, combo: string | string[]): boolean;
  disable?(command: string): void;
  resetBinding?(command: string): void;
}

export interface KeymapOptions {
  isMac?: boolean;
  /** The chart's shortcut manager, for conflict detection, the panel's Chart section and rebinding its commands. */
  chart?: ChartShortcutSource | null;
  /** Which scopes are active right now, narrowest first. Default: `['global']`. */
  scopes?: () => readonly KeyScope[];
}

/** One row of the shortcuts panel. */
export interface KeymapRow {
  label: string;
  /** The chord in force, key form; `''` while unbound. */
  combo: string;
  display: string;
  /** Label of the widget binding that takes this chart chord first. */
  shadowedBy?: string;
  /** The command a rebind names; absent for a binding registered without one. */
  command?: string;
  /** Whether a user may move it. Set with `command`. */
  rebindable?: boolean;
  /** The chord it resets to, key form. Set with `command`. */
  defaultCombo?: string;
  /** True when it differs from its default, so there is something to reset. */
  changed?: boolean;
}

export interface KeymapGroup {
  readonly group: string;
  readonly rows: ReadonlyArray<KeymapRow>;
}

type Entry = { -readonly [K in keyof KeyBinding]: KeyBinding[K] };

/**
 * Keymaps recording a chord right now. Every chart on a page listens on the
 * same document and the one attached first sees a key first, so it stands
 * aside while a neighbour records: a chord typed into one chart's editor must
 * not also pick a tool in the chart beside it.
 */
const RECORDING = new Set<Keymap>();

const fail = (reason: NonNullable<KeyRebindResult['reason']>, conflicts: readonly KeyChordUse[] = []): KeyRebindResult => ({ ok: false, reason, conflicts });
const sameList = (a: readonly string[] | null, b: readonly string[] | null): boolean =>
  a === b || (a !== null && b !== null && a.length === b.length && a.every((c, i) => c === b[i]));

export class Keymap {
  private readonly _isMac: boolean;
  private readonly _chart: ChartShortcutSource | null;
  private _scopes: () => readonly KeyScope[];
  private readonly _bindings: Entry[] = [];
  private readonly _byCombo = new Map<string, Entry[]>();
  private readonly _conflictListeners = new Set<(c: KeyConflict) => void>();
  private readonly _changeListeners = new Set<(e: KeymapChange) => void>();
  /** The user's widget chords by command, kept for a command that registers later too. */
  private readonly _overrides = new Map<string, string | null>();
  /** The user's engine chords by engine command, in the engine's grammar. */
  private readonly _chartOverrides = new Map<string, string[] | null>();
  /** What each engine command had before the user touched it: a host's own bindings count as its default. */
  private _chartBaseline: Map<string, string[] | null> | null = null;
  private _capture: KeyAction | null = null;
  private _detach: (() => void) | null = null;
  /** The node `attach` listens on, which is what makes another keymap a neighbour. */
  private _target: object | null = null;
  private _nextId = 1;

  public constructor(opts: KeymapOptions = {}) {
    this._isMac = opts.isMac ?? detectMac();
    this._chart = opts.chart ?? null;
    this._scopes = opts.scopes ?? (() => ['global']);
  }

  public get isMac(): boolean { return this._isMac; }

  /** Replace the scope resolver. */
  public setScopes(fn: () => readonly KeyScope[]): void { this._scopes = fn; }

  public activeScopes(): readonly KeyScope[] { return this._scopes(); }

  /**
   * Bind a chord. Returns a disposer. Throws on a chord the grammar cannot
   * read, or a command another live binding has, because a binding that can
   * never fire or never be told apart is a defect at the call site, not at
   * key time. A saved override for the command applies at once.
   */
  public register(binding: string, action: KeyAction, scope: KeyScope = 'global', opts: KeyBindingOptions = {}): () => void {
    const combo = parseKeyCombo(binding);
    if (combo === '') throw new Error(`openalgo-charts widget: "${binding}" is not a key binding`);
    const command = opts.command ?? null;
    if (command !== null && (command === '' || command.startsWith(CHART) || this._bindings.some((b) => b.command === command))) {
      throw new Error(`openalgo-charts widget: "${command}" is not a free command name`);
    }
    const rebindable = command !== null && opts.rebindable !== false;
    const saved = command !== null && rebindable ? this._overrides.get(command) : undefined;
    const entry: Entry = {
      id: this._nextId++,
      combo: saved === undefined ? combo : saved ?? '',
      defaultCombo: combo,
      command,
      rebindable,
      scope,
      label: opts.label ?? formatKeyCombo(combo, this._isMac),
      group: opts.group ?? 'Widget',
      hidden: opts.hidden === true,
      inText: opts.inText === true,
      layered: opts.layered === true,
      action,
      when: opts.when,
    };
    const before = this._conflictKeys();
    this._bindings.push(entry);
    this._index(entry);
    if (before !== null) this._announce(before);
    return () => this._unregister(entry);
  }

  private _index(entry: Entry): void {
    if (entry.combo === '') return;
    const list = this._byCombo.get(entry.combo) ?? [];
    // Registration order decides which binding on a chord is tried first,
    // and a rebound one keeps its place rather than jumping the queue.
    let at = list.length;
    while (at > 0 && list[at - 1]!.id > entry.id) at--; // at - 1 is inside the list while at > 0
    list.splice(at, 0, entry);
    this._byCombo.set(entry.combo, list);
  }

  private _unindex(entry: Entry): void {
    const list = this._byCombo.get(entry.combo);
    if (list === undefined) return;
    const j = list.indexOf(entry);
    if (j >= 0) list.splice(j, 1);
    if (list.length === 0) this._byCombo.delete(entry.combo);
  }

  private _unregister(entry: Entry): void {
    const i = this._bindings.indexOf(entry);
    if (i >= 0) this._bindings.splice(i, 1);
    this._unindex(entry);
  }

  /** Widget against widget: a non-layered binding with an earlier one in its scope on its chord. */
  private _widgetConflicts(): KeyConflict[] {
    const out: KeyConflict[] = [];
    for (const b of this._bindings) {
      if (b.layered || b.combo === '') continue;
      const list = this._byCombo.get(b.combo) ?? [];
      const prior = list.slice(0, list.indexOf(b)).find((p) => p.scope === b.scope);
      if (prior !== undefined) out.push({ combo: b.combo, scope: b.scope, kept: prior.label, shadowed: b.label, source: 'widget' });
    }
    return out;
  }

  /** The collisions in force, as keys; null when nobody listens for new ones. */
  private _conflictKeys(): Set<string> | null {
    if (this._conflictListeners.size === 0) return null;
    return new Set(this._widgetConflicts().map((c) => `${c.combo}|${c.scope}|${c.kept}|${c.shadowed}`));
  }

  /** Tell the conflict listeners about every collision that was not there before. */
  private _announce(before: Set<string>): void {
    for (const c of this._widgetConflicts()) {
      if (before.has(`${c.combo}|${c.scope}|${c.kept}|${c.shadowed}`)) continue;
      for (const fn of this._conflictListeners) fn(c);
    }
  }

  /** Be told when a registration collides with an earlier one. */
  public onConflict(fn: (c: KeyConflict) => void): () => void {
    this._conflictListeners.add(fn);
    return () => this._conflictListeners.delete(fn);
  }

  /** Be told when the user's chords change: a rebind, a reset, or overrides applied. */
  public onChange(fn: (e: KeymapChange) => void): () => void {
    this._changeListeners.add(fn);
    return () => this._changeListeners.delete(fn);
  }

  private _emit(commands: Iterable<string | null>): void {
    const list = Array.from(new Set(Array.from(commands).filter((c): c is string => c !== null)));
    if (list.length === 0) return;
    for (const fn of this._changeListeners) fn({ commands: list });
  }

  /**
   * Hand the next key presses to `fn` ahead of every binding, for a control
   * that records a chord. Each press is prevented and stopped outright, so no
   * binding, no open dialog's Escape and no chart shortcut sees it, and
   * another keymap attached to the same node claims nothing meanwhile; `fn`
   * returns false to let one through (Tab moving the focus). Returns the
   * release. A second capture replaces the first.
   */
  public capture(fn: KeyAction): () => void {
    this._capture = fn;
    RECORDING.add(this);
    return () => {
      if (this._capture !== fn) return;
      this._capture = null;
      RECORDING.delete(this);
    };
  }

  /** Whether a control is recording a chord right now. */
  public get capturing(): boolean { return this._capture !== null; }

  /**
   * Resolve and run the binding for an event. True when a binding claimed it,
   * in which case the event has been prevented and stopped.
   */
  public handle(e: KeyEventLike): boolean {
    if (this._capture !== null) {
      if (this._capture(e) === false) return false;
      e.preventDefault?.();
      if (e.stopImmediatePropagation !== undefined) e.stopImmediatePropagation();
      else e.stopPropagation?.();
      return true;
    }
    if (this._target !== null) {
      for (const k of RECORDING) if (k !== this && k._target === this._target) return false;
    }
    const combo = eventKeyCombo(e);
    if (combo === '') return false;
    const list = this._byCombo.get(combo);
    if (list === undefined) return false;
    const typing = inTextField(e.target);
    for (const scope of this._scopes()) {
      for (const b of list.slice()) {
        if (b.scope !== scope) continue;
        if (typing && !b.inText) continue;
        if (b.when !== undefined && !b.when()) continue;
        if (b.action(e) === false) continue;
        e.preventDefault?.();
        e.stopPropagation?.();
        return true;
      }
    }
    return false;
  }

  /**
   * Listen on `target` in the capture phase, so a claimed chord never reaches
   * the engine's own listener on the document. Returns the detacher; a second
   * call replaces the first.
   */
  public attach(target: { addEventListener(t: string, fn: EventListener, opts?: boolean): void; removeEventListener(t: string, fn: EventListener, opts?: boolean): void }): () => void {
    this._detach?.();
    const fn = ((e: Event) => { this.handle(e as unknown as KeyEventLike); }) as EventListener;
    target.addEventListener('keydown', fn, true);
    this._target = target;
    this._detach = () => { target.removeEventListener('keydown', fn, true); this._detach = null; this._target = null; };
    return this._detach;
  }

  public list(): readonly KeyBinding[] { return this._bindings.slice(); }

  /** Every collision in force: widget against widget, and widget against the engine's keymap. */
  public conflicts(): readonly KeyConflict[] {
    const out = this._widgetConflicts();
    if (this._chart !== null) {
      for (const item of this._chart.list()) {
        if (item.isDisabled) continue;
        for (const raw of item.combos) {
          const combo = fromChartCombo(raw);
          const claim = (this._byCombo.get(combo) ?? []).find((b) => reachesChart(b.scope) && !b.layered);
          if (claim !== undefined) out.push({ combo, scope: claim.scope, kept: claim.label, shadowed: item.label, source: 'chart' });
        }
      }
    }
    return out;
  }

  public format(combo: string): string { return formatKeyCombo(combo, this._isMac); }

  // ── rebinding ────────────────────────────────────────────────────────

  private _use(b: Entry): KeyChordUse {
    return { command: b.command, label: b.label, group: b.group, source: 'widget', rebindable: b.rebindable };
  }

  private _chartEditable(): boolean {
    const s = this._chart;
    return s !== null && typeof s.setBinding === 'function' && typeof s.disable === 'function' && typeof s.resetBinding === 'function';
  }

  private _chartUse(item: ShortcutListItem): KeyChordUse {
    return { command: CHART + item.command, label: item.label, group: 'Chart', source: 'chart', rebindable: this._chartEditable() };
  }

  /** Who holds a key-form chord where a binding in `scope` would compete for it. */
  private _holders(combo: string, scope: KeyScope, except: string | null): KeyChordUse[] {
    const out: KeyChordUse[] = [];
    for (const b of this._byCombo.get(combo) ?? []) {
      if ((except !== null && b.command === except) || !meets(b.scope, scope)) continue;
      out.push(this._use(b));
    }
    if (this._chart !== null && reachesChart(scope)) {
      for (const item of this._chart.list()) {
        if (item.isDisabled || CHART + item.command === except) continue;
        if (item.combos.some((c) => fromChartCombo(c) === combo)) out.push(this._chartUse(item));
      }
    }
    return out;
  }

  /** Who holds any of these engine chords: another engine command, or a widget binding that claims first. */
  private _chartHolders(combos: readonly string[], except: string): KeyChordUse[] {
    const out: KeyChordUse[] = [];
    const s = this._chart;
    if (s === null) return out;
    for (const item of s.list()) {
      if (item.isDisabled || item.command === except) continue;
      if (item.combos.some((c) => combos.includes(c))) out.push(this._chartUse(item));
    }
    const seen = new Set<Entry>();
    for (const c of combos) {
      for (const b of this._byCombo.get(fromChartCombo(c)) ?? []) {
        // A layered binding declines when it does not apply, so the engine still gets the key.
        if (b.layered || !reachesChart(b.scope) || seen.has(b)) continue;
        seen.add(b);
        out.push(this._use(b));
      }
    }
    return out;
  }

  /**
   * The bindings that would compete with `combo` (key form) for a binding in
   * `scope`: widget bindings on it in that scope or one live at the same time
   * (`global`, `widget` and `chart` nest), and the engine's commands on it
   * unless the scope is `rail` or `overlay`. An unreadable chord has none.
   */
  public conflictsFor(combo: string, scope: KeyScope = 'widget'): KeyChordUse[] {
    const c = parseKeyCombo(combo);
    return c === '' ? [] : this._holders(c, scope, null);
  }

  /**
   * The chord a command answers to now, in key form: `''` while it is
   * unbound, null for a command nothing registered. An engine command
   * (`chart:<command>`) reports its first chord.
   */
  public chord(command: string): string | null {
    if (command.startsWith(CHART)) {
      const item = this._chart?.list().find((i) => CHART + i.command === command);
      if (item === undefined) return null;
      return item.isDisabled || item.combos.length === 0 ? '' : fromChartCombo(item.combos[0]!); // not empty past the length test
    }
    const entry = this._bindings.find((b) => b.command === command);
    return entry === undefined ? null : entry.combo;
  }

  private _setWidget(entry: Entry, combo: string): void {
    if (entry.combo !== combo) {
      this._unindex(entry);
      entry.combo = combo;
      this._index(entry);
    }
    const command = entry.command as string;
    if (combo === entry.defaultCombo) this._overrides.delete(command);
    else this._overrides.set(command, combo === '' ? null : combo);
  }

  private _chartNow(command: string): string[] | null | undefined {
    const item = this._chart?.list().find((i) => i.command === command);
    return item === undefined ? undefined : item.isDisabled ? null : item.combos.slice();
  }

  /**
   * What an engine command had before the keymap first changed it, recorded
   * at that moment: a host's own binding is its default, not the engine's.
   */
  private _base(command: string): string[] | null {
    const map = this._chartBaseline ?? (this._chartBaseline = new Map());
    if (!map.has(command)) map.set(command, this._chartNow(command) ?? null);
    return map.get(command) as string[] | null;
  }

  private _setChart(command: string, combos: string[] | null): void {
    const s = this._chart as Required<ChartShortcutSource>;
    const base = this._base(command);
    const put = (): void => { if (combos === null) s.disable(command); else s.setBinding(command, combos); };
    if (sameList(base, combos)) {
      // Back where it started: let the engine drop its override, then put a
      // host's own binding back when the engine's default is not it.
      s.resetBinding(command);
      if (!sameList(this._chartNow(command) ?? null, combos)) put();
      this._chartOverrides.delete(command);
      return;
    }
    put();
    this._chartOverrides.set(command, combos);
  }

  /** An engine command that gave chords up to a replace keeps the rest, or is unbound. */
  private _dropChart(holder: KeyChordUse, taken: (chartCombo: string) => boolean): void {
    const command = (holder.command as string).slice(CHART.length);
    const rest = (this._chartNow(command) ?? []).filter((c) => !taken(c));
    this._setChart(command, rest.length > 0 ? rest : null);
  }

  /** A widget binding that gave its chord up to a replace is left unbound. */
  private _dropWidget(holder: KeyChordUse): void {
    const entry = this._bindings.find((b) => b.command === holder.command);
    if (entry !== undefined) this._setWidget(entry, '');
  }

  /**
   * Move a command to another chord, or unbind it with null. A widget command
   * takes one chord in the key grammar; an engine command (`chart:<command>`)
   * one or several in the engine's code grammar, as `eventToCombo` gives
   * them. A chord the browser keeps is refused, and so is one another binding
   * holds, unless `replace` is set and every holder is rebindable: each then
   * gives the chord up and is left without it.
   */
  public rebind(command: string, combo: string | readonly string[] | null, opts: { replace?: boolean } = {}): KeyRebindResult {
    return this._rebind(command, combo, opts.replace === true, false);
  }

  /**
   * Put a command back on its default chord. The default may have been taken
   * meanwhile by a binding of the same kind (widget or chart); that is refused
   * as `taken` unless `replace` is set, as with `rebind`. A command nothing
   * registered yet just forgets its saved chord.
   */
  public reset(command: string, opts: { replace?: boolean } = {}): KeyRebindResult {
    return this._rebind(command, undefined, opts.replace === true, true);
  }

  /** Every command back on its default chord, including those not registered yet. */
  public resetAll(): void {
    const changed = this._clearAll();
    this._emit(changed);
  }

  private _clearAll(): string[] {
    const changed: string[] = [];
    for (const command of Array.from(this._overrides.keys())) {
      const entry = this._bindings.find((b) => b.command === command);
      if (entry !== undefined) this._setWidget(entry, entry.defaultCombo);
      this._overrides.delete(command);
      changed.push(command);
    }
    for (const command of Array.from(this._chartOverrides.keys())) {
      this._setChart(command, this._base(command));
      changed.push(CHART + command);
    }
    return changed;
  }

  private _rebind(command: string, combo: string | readonly string[] | null | undefined, replace: boolean, reset: boolean): KeyRebindResult {
    if (command.startsWith(CHART)) return this._rebindChart(command.slice(CHART.length), combo, replace, reset);
    const entry = this._bindings.find((b) => b.command === command);
    if (entry === undefined) {
      if (reset && this._overrides.delete(command)) this._emit([command]);
      return reset ? { ok: true, conflicts: [] } : fail('unknown');
    }
    if (!entry.rebindable) return fail('fixed');
    let next = entry.defaultCombo;
    if (!reset) {
      next = '';
      if (combo !== null && combo !== undefined) {
        const one = typeof combo === 'string' ? [combo] : combo;
        next = one.length === 1 ? parseKeyCombo(one[0]!) : ''; // the one chord
        if (next === '') return fail('invalid');
        if (reservedKey(next)) return fail('reserved');
      }
    }
    if (next === entry.combo) return { ok: true, conflicts: [] };
    // A default can shadow a chart command by design (the tier's Alt+H over
    // the grid toggle), so a reset stands aside only for another widget binding.
    const holders = next === '' ? [] : this._holders(next, entry.scope, command).filter((h) => !reset || h.source === 'widget');
    if (holders.length > 0) {
      if (!replace || holders.some((h) => !h.rebindable)) return fail('taken', holders);
      for (const h of holders) {
        if (h.source === 'chart') this._dropChart(h, (c) => fromChartCombo(c) === next);
        else this._dropWidget(h);
      }
    }
    this._setWidget(entry, next);
    this._emit([command, ...holders.map((h) => h.command)]);
    return { ok: true, conflicts: holders };
  }

  private _rebindChart(command: string, combo: string | readonly string[] | null | undefined, replace: boolean, reset: boolean): KeyRebindResult {
    const now = this._chart === null ? undefined : this._chartNow(command);
    if (now === undefined) return fail('unknown');
    if (!this._chartEditable()) return fail('fixed');
    let next: string[] | null = null;
    if (reset) {
      next = this._base(command);
    } else if (combo !== null && combo !== undefined) {
      const list = (typeof combo === 'string' ? [combo] : Array.from(combo)).map(normalizeCombo);
      if (list.length === 0 || list.includes('')) return fail('invalid');
      if (list.some((c) => isReservedCombo(c))) return fail('reserved');
      next = Array.from(new Set(list));
    }
    if (sameList(next, now)) {
      if (reset && this._chartOverrides.delete(command)) this._emit([CHART + command]);
      return { ok: true, conflicts: [] };
    }
    const holders = next === null ? [] : this._chartHolders(next, command).filter((h) => !reset || h.source === 'chart');
    if (holders.length > 0) {
      if (!replace || holders.some((h) => !h.rebindable)) return fail('taken', holders);
      const taken = next as string[];
      for (const h of holders) {
        if (h.source === 'chart') this._dropChart(h, (c) => taken.includes(c));
        else this._dropWidget(h);
      }
    }
    this._setChart(command, next);
    this._emit([CHART + command, ...holders.map((h) => h.command)]);
    return { ok: true, conflicts: holders };
  }

  /** The user's chords, JSON-safe: what a host saves and hands back to `applyOverrides`. */
  public overrides(): Record<string, string | string[] | null> {
    const out: Record<string, string | string[] | null> = {};
    for (const [command, combo] of this._overrides) out[command] = combo;
    for (const [command, combos] of this._chartOverrides) out[CHART + command] = combos === null ? null : combos.slice();
    return out;
  }

  /**
   * Make `overrides` the user's chords: every command it leaves out goes back
   * to its default, and each one it names moves (null unbinds). Written for a
   * saved record, so it reads anything: an entry that does not parse, is
   * reserved, or names a fixed binding is dropped, and one for a command
   * nothing registered yet is kept for when it does. Collisions a saved chord
   * makes are reported through `onConflict`, as a registration's are.
   */
  public applyOverrides(overrides: unknown): void {
    const widget = new Map<string, string | null>();
    const chart = new Map<string, string[] | null>();
    if (overrides !== null && typeof overrides === 'object' && !Array.isArray(overrides)) {
      for (const [command, raw] of Object.entries(overrides as Record<string, unknown>)) {
        if (command.startsWith(CHART)) {
          const name = command.slice(CHART.length);
          const list = raw === null ? null : (Array.isArray(raw) ? raw : [raw]).map((c) => (typeof c === 'string' ? normalizeCombo(c) : ''));
          if (name === '' || (list !== null && (list.length === 0 || list.some((c) => c === '' || isReservedCombo(c))))) continue;
          chart.set(name, list);
        } else if (command !== '' && (raw === null || typeof raw === 'string')) {
          const combo = raw === null ? null : parseKeyCombo(raw);
          if (combo === '' || (combo !== null && reservedKey(combo))) continue;
          const entry = this._bindings.find((b) => b.command === command);
          if (entry !== undefined && !entry.rebindable) continue;
          widget.set(command, combo);
        }
      }
    }
    const before = this._conflictKeys();
    const was = new Map(this._bindings.map((b) => [b, b.combo]));
    const had = this.overrides();
    this._clearAll();
    for (const [command, combo] of widget) {
      const entry = this._bindings.find((b) => b.command === command);
      if (entry === undefined) this._overrides.set(command, combo);
      else this._setWidget(entry, combo ?? '');
    }
    if (this._chartEditable()) {
      for (const [command, combos] of chart) if (this._chartNow(command) !== undefined) this._setChart(command, combos);
    }
    if (before !== null) this._announce(before);
    const after = this.overrides();
    const changed = this._bindings.filter((b) => b.command !== null && was.get(b) !== b.combo).map((b) => b.command);
    // A saved chord for a command not registered yet changes nothing on
    // screen, but it is still a change a store or a sibling chart must hear.
    for (const key of new Set([...Object.keys(had), ...Object.keys(after)])) {
      if (JSON.stringify(had[key]) !== JSON.stringify(after[key])) changed.push(key);
    }
    this._emit(changed);
  }

  /** The chord an engine command resets to, key form. */
  private _chartDefault(command: string, now: readonly string[]): string {
    const base = this._chartBaseline?.get(command);
    const list = base === undefined ? now : (base ?? []);
    return list.length === 0 ? '' : fromChartCombo(list[0]!); // not empty past the length test
  }

  /**
   * The bindings as the shortcuts panel shows them: the widget's own groups,
   * then the engine's chart commands, with any chord the widget claims first
   * marked as shadowed. An engine command the user unbound stays listed, so
   * it can be reset.
   */
  public describe(): KeymapGroup[] {
    const groups = new Map<string, KeymapRow[]>();
    for (const b of this._bindings) {
      if (b.hidden) continue;
      const rows = groups.get(b.group) ?? [];
      const row: KeymapRow = { label: b.label, combo: b.combo, display: this.format(b.combo) };
      if (b.command !== null) {
        row.command = b.command;
        row.rebindable = b.rebindable;
        row.defaultCombo = b.defaultCombo;
        row.changed = b.combo !== b.defaultCombo;
      }
      rows.push(row);
      groups.set(b.group, rows);
    }
    const out: KeymapGroup[] = Array.from(groups, ([group, rows]) => ({ group, rows }));
    if (this._chart !== null) {
      const shadow = new Map<string, string>();
      for (const c of this.conflicts()) if (c.source === 'chart') shadow.set(c.shadowed + '|' + c.combo, c.kept);
      const editable = this._chartEditable();
      const rows: KeymapRow[] = [];
      for (const item of this._chart.list()) {
        const mine = this._chartOverrides.has(item.command);
        if ((item.isDisabled || item.combos.length === 0) && !mine) continue;
        const combo = item.isDisabled || item.combos.length === 0 ? '' : fromChartCombo(item.combos[0]!); // not empty past the length test
        const row: KeymapRow = { label: item.label, combo, display: this.format(combo), command: CHART + item.command, rebindable: editable,
          defaultCombo: this._chartDefault(item.command, item.combos), changed: mine };
        const by = shadow.get(item.label + '|' + combo);
        if (by !== undefined) row.shadowedBy = by;
        rows.push(row);
      }
      if (rows.length > 0) out.push({ group: 'Chart', rows });
    }
    return out;
  }

  public destroy(): void {
    this._detach?.();
    this._capture = null;
    RECORDING.delete(this);
    this._bindings.length = 0;
    this._byCombo.clear();
    this._overrides.clear();
    this._chartOverrides.clear();
    this._conflictListeners.clear();
    this._changeListeners.clear();
  }
}

/**
 * A chord as the keymap shows it, in the form aria-keyshortcuts takes
 * (Ctrl+Shift+Z is Control+Shift+Z, Cmd+D is Meta+D, Del is Delete): a menu
 * row shows the chord beside its name and carries it as its shortcut, so the
 * chord is not read as part of the name.
 */
export function ariaKeys(chord: string): string {
  const aria: Readonly<Record<string, string>> = { Ctrl: 'Control', Cmd: 'Meta', Opt: 'Alt', Del: 'Delete', Esc: 'Escape', Left: 'ArrowLeft', Right: 'ArrowRight', Up: 'ArrowUp', Down: 'ArrowDown' };
  return chord.split('+').map(part => aria[part] ?? part).join('+');
}

/**
 * The chord a command answers to as a user reads it, for a tip or a menu row,
 * so a chord the user moved is shown where it went. `fallback` stands in
 * when nothing registered the command (chrome mounted over a host's own
 * keymap); an unbound command shows none. Internal: the tier entry does not
 * export it.
 */
export function commandChord(km: Keymap, command: string, fallback?: string): string | undefined {
  // The dialogs also mount over a context a host built itself, whose keymap
  // may be a stand-in; they showed the default chord there before 2.5.10.
  const own = km as Partial<Keymap> | undefined;
  const c = (typeof own?.chord === 'function' ? own.chord(command) : null) ?? fallback;
  if (c === undefined || c === '') return undefined;
  return typeof own?.format === 'function' ? own.format(c) : formatKeyCombo(c);
}

export interface ShortcutsPanelOptions {
  /**
   * Rows a user may change carry Change and Reset, and the panel a Reset all.
   * Default true, unless the widget was built with `shortcutsEditor: false`;
   * false lists the chords only.
   */
  edit?: boolean;
}

/**
 * Keymaps whose widget turned the editor off. A host that opens the panel
 * from a control of its own gets the same panel `?` opens, never controls
 * whose changes that widget would neither keep nor let the user reset.
 */
const LIST_ONLY = new WeakSet<object>();

/** Mark a keymap as list-only for the panel's default. Internal: the tier entry does not export it. */
export function markListOnly(keymap: object): void { LIST_ONLY.add(keymap); }

/** The panel and its editing controls, fetched when it first opens. Internal. */
export const shortcutsPart = lazyPart(() => import('./keymap-editor'));
/** Per widget, the panel on its way: `?` pressed again meanwhile opens one. */
const WAITING = new WeakMap<object, PartSlot>();

/**
 * The shortcuts panel: every group from `keymap.describe()`, two columns,
 * closed by Escape or its button, with the editing controls unless `edit` is
 * false. Returns the closer. The panel loads on first use (since 2.5.10), so
 * the first one opens once it has arrived, unless the closer ran or the user
 * moved on before then (lazy.ts); a panel that cannot load says so in a toast.
 */
export function openShortcutsPanel(ctx: WidgetContext, opts: ShortcutsPanelOptions = {}): () => void {
  let close: (() => void) | null = null;
  let wanted = true;
  let slot = WAITING.get(ctx);
  if (slot === undefined) WAITING.set(ctx, slot = { waiting: null });
  usePart(shortcutsPart, module => { close = module.mountShortcutsPanel(ctx, opts.edit ?? !LIST_ONLY.has(ctx.keymap)); },
    error => ctx.toast(partFailed(ctx, widgetText(ctx, 'Keyboard shortcuts'), error), 'error'),
    () => wanted && !ctx.chart.isDestroyed, { slot, doc: ctx.document });
  return () => { wanted = false; close?.(); };
}
