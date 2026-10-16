/**
 * What the chart grid reads back before it builds anything: a workspace
 * payload, checked whole so a desk it cannot honour changes no chart, and
 * each chart's drawings per instrument, kept beside the desk.
 *
 * Its own module so grid.ts keeps the grid itself; everything here is plain
 * data in and plain data out.
 */
import { isKnownInterval, registeredIndicators } from 'openalgo-charts';
import { isChartTypeChoice } from './chart-type-choice';
import type { DrawingDocumentStore, DrawingsDocument } from 'openalgo-charts/draw';
import type { WorkspacePayload } from 'openalgo-charts/workspace';
import { checkLinks } from './grid-links';
import { isRecord } from '../helpers/validate';

/** Each chart's drawing documents, by pane id, then by instrument key. */
export type ChartDrawings = Map<string, Map<string, DrawingsDocument>>;

/**
 * One cell's store, inside `docs`. The documents are copied on the way in,
 * so a later change on the chart never edits one the grid is about to save.
 */
export function cellDrawingStore(id: string, docs: ChartDrawings): DrawingDocumentStore {
  return {
    get: key => docs.get(id)?.get(key) ?? null,
    set: (key, document) => {
      let mine = docs.get(id);
      if (mine === undefined) docs.set(id, mine = new Map());
      mine.set(key, JSON.parse(JSON.stringify(document)) as DrawingsDocument);
    },
    remove: key => { docs.get(id)?.delete(key); },
  };
}

/** The saved drawings entry, read defensively: anything it cannot use is left out, never thrown. */
export function readChartDrawings(value: unknown): ChartDrawings {
  const out: ChartDrawings = new Map();
  if (!isRecord(value) || value.version !== 1 || !isRecord(value.charts)) return out;
  for (const [id, documents] of Object.entries(value.charts)) {
    if (!isRecord(documents)) continue;
    const mine = new Map<string, DrawingsDocument>();
    for (const [key, document] of Object.entries(documents)) if (isRecord(document)) mine.set(key, document as unknown as DrawingsDocument);
    out.set(id, mine);
  }
  return out;
}

const int = (v: unknown, lo: number, hi: number): boolean => Number.isInteger(v) && (v as number) >= lo && (v as number) <= hi;

/** What a grid cannot honour, checked before anything is built. Empty when the payload is usable. */
export function checkWorkspace(p: WorkspacePayload): string {
  if (!isRecord(p) || !isRecord(p.layout) || !Array.isArray(p.layout.slots) || !Array.isArray(p.panes) || !isRecord(p.sync)) {
    return 'not a workspace payload';
  }
  const { rows, columns, slots } = p.layout;
  if (!int(rows, 1, 8) || !int(columns, 1, 8) || !int(p.panes.length, 1, 16)) return 'unsupported grid size';
  for (const [weights, count] of [[p.layout.rowWeights, rows], [p.layout.columnWeights, columns]] as const) {
    if (weights !== undefined && (!Array.isArray(weights) || weights.length !== count
      || !weights.every(w => typeof w === 'number' && w > 0 && w <= 1000))) return 'invalid track weights';
  }
  const studies = new Set(registeredIndicators().map(d => d.id));
  const ids = new Set<string>();
  for (const pane of p.panes) {
    if (!isRecord(pane) || typeof pane.id !== 'string' || pane.id === '' || ids.has(pane.id)) return 'invalid or duplicate chart id';
    ids.add(pane.id);
    if (typeof pane.symbol !== 'string' || typeof pane.exchange !== 'string' || !isRecord(pane.chart)
      || !['string', 'undefined'].includes(typeof pane.historyPeriod)) return `${pane.id}: invalid chart`;
    if (!isKnownInterval(pane.interval)) return `${pane.id}: unknown interval ${String(pane.interval)}`;
    if (!isChartTypeChoice(pane.chartType)) return `${pane.id}: unknown chart type ${String(pane.chartType)}`;
    if (Array.isArray(pane.comparisons) && pane.comparisons.length > 0) return `${pane.id}: comparison symbols are not supported in a grid chart`;
    for (const study of Array.isArray(pane.chart.indicators) ? pane.chart.indicators : []) {
      if (!studies.has(study?.indicatorId)) return `${pane.id}: unavailable study ${String(study?.indicatorId)}`;
    }
  }
  const placed = new Set<string>();
  const taken = new Set<number>();
  for (const slot of slots) {
    const rowSpan = slot?.rowSpan ?? 1, columnSpan = slot?.columnSpan ?? 1;
    if (!isRecord(slot) || !ids.has(slot.paneId) || placed.has(slot.paneId) || !int(slot.row, 0, rows - 1) || !int(slot.column, 0, columns - 1)
      || !int(rowSpan, 1, rows - slot.row) || !int(columnSpan, 1, columns - slot.column)) return 'invalid layout slot';
    placed.add(slot.paneId);
    for (let r = slot.row; r < slot.row + rowSpan; r++) for (let c = slot.column; c < slot.column + columnSpan; c++) {
      if (taken.has(r * columns + c)) return 'layout slots overlap';
      taken.add(r * columns + c);
    }
  }
  if (placed.size !== ids.size) return 'every chart needs one layout slot';
  if (!ids.has(p.activePaneId)) return 'the active chart is missing';
  return checkLinks(p);
}
