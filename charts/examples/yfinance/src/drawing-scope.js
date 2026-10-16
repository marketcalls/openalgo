// Drawings per symbol. A line drawn on AAPL belongs to AAPL: loading MSFT into
// the same chart shows MSFT's own drawings, and AAPL's come back with AAPL.
//
// The draw tier does the work (`InstrumentDrawings` follows the chart's data
// context and swaps documents as it changes); this host only chooses where
// the documents live and says so when storage refuses one. Each chart of the
// split view keeps its own set, so two charts on one symbol never overwrite
// each other's lines through a shared entry.
import * as drawTier from '/dist/openalgo-charts.draw.mjs';
import { toast } from './ui.js';

// Off the namespace, like the other late additions: a dist/ from before
// drawings were per instrument still draws, with one drawing set per chart.
const { InstrumentDrawings, memoryDrawingStore, webStorageDrawingStore } = drawTier;

/** Every symbol's drawings sit under this prefix, then the chart's number, then the symbol. */
export const DRAWINGS_PREFIX = 'oa-charts:drawings:';

let warned = false;

/** The page's storage when it can be reached at all; a privacy mode can refuse even that. */
function pageStorage() {
  try { return typeof localStorage === 'undefined' ? null : localStorage; }
  catch (_) { return null; }
}

/**
 * Keep `draw`'s drawings per symbol for chart `pane` (1 or 2). `prefer` is
 * 'live' when the chart was just built from a state that already holds the
 * symbol's drawings (a rebuild, a layout), and 'stored' for a chart built
 * fresh. Returns null on a dist/ without the helper.
 */
export function scopeDrawings(chart, draw, pane, prefer) {
  if (!InstrumentDrawings) return null;
  const storage = pageStorage();
  const store = storage ? webStorageDrawingStore(storage, `${DRAWINGS_PREFIX}${pane}:`) : memoryDrawingStore();
  return new InstrumentDrawings(chart, draw, {
    store, prefer,
    // Said once: the drawings are still there for this session, and the next
    // change tries storage again, so a notice per drag would only be noise.
    onError: ({ operation, key }) => {
      if (operation === 'read' || warned) return;
      warned = true;
      toast('error', `The drawings for ${decodeURIComponent(key)} could not be saved to browser storage. They are kept for this session.`);
    },
  });
}
