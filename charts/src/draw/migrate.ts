/**
 * The drawing migration: 1.9.x to 2.0, and document version 2 to 3.
 *
 * Hosts persist `toJSON()` verbatim, and a 1.9.x host has done so for a long
 * time: a bare `Drawing[]` per pane in local storage, for a great many users.
 * Version 2 moved every text field out of the style bag, made `levels` a list
 * of {@link FibLevel} rather than bare ratios, and gave each drawing a
 * `zIndex`. Reading an old save through the new types would lose the text and
 * the levels silently, and the user would open 2.0 to a chart with holes in
 * it. This is the one place the old shape is understood, so nothing
 * downstream needs to.
 *
 * Rules, in the order of what they protect:
 *
 * - A drawing that can be rendered is kept. An optional field with the wrong
 *   type is dropped on its own; only an entry with no usable tool, anchors or
 *   pane is dropped, because it could never be drawn again anyway. The
 *   clipboard is stricter (a paste is all-or-nothing) and gates before it
 *   calls this.
 * - Ids and array order survive. The list order is the paint order, and a
 *   host may hold ids of its own against the drawings.
 * - Unknown fields are dropped, so the style bag stays closed and a stray key
 *   never reaches the model.
 * - An unregistered tool is not a reason to drop anything: a plugin tool may
 *   register after the layout is restored. This module never consults the
 *   registry, which also keeps it pure.
 * - A viewport drawing keeps its `viewportPoints` and carries no data
 *   anchors; one without usable viewport anchors is dropped, since falling
 *   back to its data anchors would put it somewhere it never was. Data is the
 *   default space and is never written out, so a document with no viewport
 *   drawing comes back exactly as it went in.
 * - Garbage yields an empty document. This runs on the load path, where an
 *   exception would take the whole chart down with it.
 *
 * Version 3 added one optional field, the interval range a drawing is shown
 * on, so a version 2 document needs no upgrade and comes back unchanged,
 * version and all. A range is kept when it names at least one bound, and the
 * document out is version 3 only when a drawing kept one. A document from a
 * later version is read the same lenient way: what this build knows is kept
 * and the rest dropped, since refusing it would empty the chart on load.
 *
 * Idempotent on a version 2 or 3 document, so a host can call it on every load.
 */
import type {
  Drawing, DrawingPolicy, DrawingStyle, DrawingText, DrawingsDocument, DrawingGroup, FibLevel,
} from './types';
import { cycleColor, levelColor } from './levels';
import { readViewportPoints } from './viewport';
import { drawingsDocumentVersion, readIntervalRange } from './intervals';
import {
  isNum, isRecord, isString, isUnsafeKey, legacyTextFields, oneOf, readPoints, readText,
  LINE_STYLES, STYLE_FLAGS, STYLE_NUMBERS, STYLE_STRINGS,
} from './drawing-fields';

const POLICY_FLAGS = ['selectable', 'editable', 'persistent', 'listed'] as const;

/** Deep enough for anything a tool stores in `props`, shallow enough to stop a cycle. */
const MAX_PROPS_DEPTH = 8;

/**
 * Ids minted for entries that arrive without one, or with one already taken.
 * Prefixed differently from the controller's own `d` ids so the two counters
 * can never meet.
 */
let minted = 1;

/**
 * Upgrade saved drawings to the current document shape. Accepts a 1.9.x
 * `Drawing[]` or a {@link DrawingsDocument} of any version. Every field is
 * validated, the 1.9.x text keys are lifted out of the style bag into `text`,
 * bare level ratios become coloured levels, and array order is kept. An entry
 * that could never be rendered is dropped; anything unparseable yields an
 * empty document rather than an error. The result is version 3 when a drawing
 * carries an interval range and version 2 otherwise.
 */
export function migrateDrawings(input: unknown): DrawingsDocument {
  const list = Array.isArray(input) ? input
    : isRecord(input) && Array.isArray(input.drawings) ? input.drawings
    : null;
  const drawings: Drawing[] = [];
  if (list === null) return { version: drawingsDocumentVersion(drawings), drawings };
  const seen = new Set<string>();
  for (const raw of list) {
    const d = migrateEntry(raw);
    if (d === null) continue;
    // Two drawings sharing an id would be one drawing to every lookup, so
    // the later one gets a fresh id and the earlier keeps what the host knows.
    while (d.id === '' || seen.has(d.id)) d.id = `m${minted++}`;
    seen.add(d.id);
    drawings.push(d);
  }
  const groups = migrateGroups(isRecord(input) ? input.groups : undefined, drawings);
  return { version: drawingsDocumentVersion(drawings), drawings, ...(groups.length ? { groups } : {}) };
}

/** Ignore stale or malformed group records, with the first valid membership winning. */
export function migrateGroups(input: unknown, drawings: readonly Drawing[]): DrawingGroup[] {
  if (!Array.isArray(input)) return [];
  const live = new Set(drawings.map(d => d.id));
  const ids = new Set<string>();
  const assigned = new Set<string>();
  const groups: DrawingGroup[] = [];
  for (const raw of input) {
    if (!isRecord(raw) || typeof raw.id !== 'string' || !raw.id.trim() || ids.has(raw.id)
      || typeof raw.name !== 'string' || !raw.name.trim() || !Array.isArray(raw.members)) continue;
    const members: string[] = [];
    for (const member of raw.members) {
      if (typeof member !== 'string' || !live.has(member) || assigned.has(member)) continue;
      members.push(member);
      assigned.add(member);
    }
    if (!members.length) continue;
    ids.add(raw.id);
    groups.push({ id: raw.id, name: raw.name.trim(), members });
  }
  return groups;
}

/** One entry of any shape into a current drawing, or null when it cannot be drawn. */
function migrateEntry(raw: unknown): Drawing | null {
  if (!isRecord(raw)) return null;
  const tool = raw.tool;
  if (typeof tool !== 'string' || tool === '') return null;
  const viewport = raw.space === 'viewport' ? readViewportPoints(raw.viewportPoints) : undefined;
  if (viewport === null) return null;
  const points = viewport === undefined ? readPoints(raw.points) : [];
  if (points === null) return null;
  // An absent pane is pane zero; a pane that cannot exist is a drawing that
  // cannot be shown, so that entry goes.
  const paneIndex = raw.paneIndex === undefined ? 0 : raw.paneIndex;
  if (!isNum(paneIndex) || paneIndex < 0 || !Number.isInteger(paneIndex)) return null;
  const style = isRecord(raw.style) ? raw.style : {};
  const out: Drawing = {
    // A numeric id is a host's own scheme, not corruption: keep its identity.
    id: typeof raw.id === 'string' ? raw.id : isNum(raw.id) ? String(raw.id) : '',
    tool,
    points,
    ...(viewport === undefined ? {} : { space: 'viewport' as const, viewportPoints: viewport }),
    style: migrateStyle(style, tool),
    paneIndex,
    zIndex: isNum(raw.zIndex) ? raw.zIndex : 0,
  };
  // A text block on the entry wins; the 1.9.x style keys only fill the gap.
  const text = migrateText(raw.text) ?? liftLegacyText(style);
  if (text !== null) out.text = text;
  if (isRecord(raw.props)) out.props = jsonRecord(raw.props, 0);
  if (typeof raw.locked === 'boolean') out.locked = raw.locked;
  if (typeof raw.visible === 'boolean') out.visible = raw.visible;
  const intervals = readIntervalRange(raw.intervals);
  if (intervals !== null) out.intervals = intervals;
  // History snapshots come through here too, so a policy the migration
  // dropped would be a policy one undo could strip.
  if (isRecord(raw.policy)) {
    const policy: DrawingPolicy = {};
    for (const key of POLICY_FLAGS) if (typeof raw.policy[key] === 'boolean') policy[key] = raw.policy[key];
    if (Object.keys(policy).length > 0) out.policy = policy;
  }
  // A slot in the series band names an entry by its inventory id; anything
  // else cannot name one, and the drawing paints by its z-index instead.
  if (typeof raw.stackAbove === 'string' && raw.stackAbove !== '') out.stackAbove = raw.stackAbove;
  if (isNum(raw.createdAt)) out.createdAt = raw.createdAt;
  return out;
}

/**
 * The style bag, closed to the keys {@link DrawingStyle} declares. The 1.9.x
 * text keys are not among them, so they fall away here and reappear through
 * {@link liftLegacyText}.
 */
function migrateStyle(value: Record<string, unknown>, tool: string): DrawingStyle {
  const out: DrawingStyle = {};
  for (const key of STYLE_STRINGS) {
    const v = value[key];
    if (typeof v === 'string') out[key] = v;
  }
  for (const key of STYLE_NUMBERS) {
    const v = value[key];
    if (isNum(v)) out[key] = v;
  }
  for (const key of STYLE_FLAGS) {
    const v = value[key];
    if (typeof v === 'boolean') out[key] = v;
  }
  if (oneOf(value.lineStyle, LINE_STYLES)) out.lineStyle = value.lineStyle;
  const levels = migrateLevels(value.levels, tool);
  if (levels !== null) out.levels = levels;
  return out;
}

/**
 * A bare 1.9.x ratio becomes a level in the colour the tool would have drawn
 * it by default, so the ladder looks the same after the upgrade and a settings
 * panel has a swatch to show. The convention is per family (see levels.ts): a
 * Gann fan colours by position, and a time zone takes the drawing's own
 * colour, so its levels are left without one.
 */
function upgradeLevel(tool: string, ratio: number, index: number): FibLevel {
  if (tool === 'fib-time-zone') return { ratio };
  if (tool === 'gann-fan') return { ratio, color: cycleColor(index) };
  return { ratio, color: levelColor(ratio) };
}

function migrateLevels(value: unknown, tool: string): FibLevel[] | null {
  if (!Array.isArray(value)) return null;
  const out: FibLevel[] = [];
  value.forEach((v, i) => {
    if (isNum(v)) {
      out.push(upgradeLevel(tool, v, i));
    } else if (isRecord(v) && isNum(v.ratio)) {
      const l: FibLevel = { ratio: v.ratio };
      if (typeof v.color === 'string') l.color = v.color;
      if (typeof v.enabled === 'boolean') l.enabled = v.enabled;
      if (typeof v.label === 'string') l.label = v.label;
      out.push(l);
    }
  });
  // A ladder whose every rung was unusable is no ladder at all: leaving `[]`
  // behind would draw nothing where the tool's defaults should show.
  return out.length === 0 && value.length > 0 ? null : out;
}

/** The text block, closed to the keys {@link DrawingText} declares. */
function migrateText(value: unknown): DrawingText | null {
  if (!isRecord(value) || typeof value.value !== 'string') return null;
  return readText(value.value, value, isString);
}

/**
 * The 1.9.x text fields, each under its new name (`legacyTextFields`). No
 * `text` means no label, whatever else the bag says: a shape with a font
 * colour and nothing to say has nothing to keep.
 */
function liftLegacyText(style: Record<string, unknown>): DrawingText | null {
  return typeof style.text === 'string' ? readText(style.text, legacyTextFields(style), isString) : null;
}

/**
 * Per-tool extras are persisted verbatim, so the only rule is JSON-safety:
 * what `JSON.stringify` would write is what survives. A value it would drop
 * from a record is dropped; one it would write as `null` inside an array is
 * written as `null`, which keeps the indices of the rest where they were (a
 * table's cells, say).
 */
function jsonRecord(value: Record<string, unknown>, depth: number): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, v] of Object.entries(value)) {
    if (isUnsafeKey(key)) continue;
    const clean = jsonValue(v, depth);
    if (clean !== undefined) out[key] = clean;
  }
  return out;
}

function jsonValue(v: unknown, depth: number): unknown {
  if (v === null || typeof v === 'boolean' || typeof v === 'string') return v;
  if (typeof v === 'number') return Number.isFinite(v) ? v : undefined;
  if (depth >= MAX_PROPS_DEPTH) return undefined;
  if (Array.isArray(v)) return v.map((item) => jsonValue(item, depth + 1) ?? null);
  if (isRecord(v)) return jsonRecord(v, depth + 1);
  return undefined;
}
