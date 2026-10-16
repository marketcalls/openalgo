// The grid view of the reference host: the widget tier's chart grid over the
// same /api/history feed as the main page. It opens the portable layouts the
// main page saves, including the ones with more than two charts or with rows,
// which the main page hands over here instead of refusing. grid.html calls
// initGridView(); like every module but main.js, importing this one builds
// nothing.
import '/dist/openalgo-charts.indicators.mjs';
import { createChartGrid } from '/dist/openalgo-charts.widget.mjs';
import { WorkspaceRepository, createIndexedDbWorkspaceStorage } from '/dist/openalgo-charts.workspace.mjs';
import {
  GRID_INTERVALS, GRID_PRESET_LABELS, gridFeeds, presetGlyph, takeGridHandoff, readGridFile, gridDocument,
} from './grid-view.js';
import { THEME_KEY } from './ui.js';
import { sessionCalendarFor } from './ticks.js';
import { referenceWatchlists, referenceQuotes, referenceNewsFeed } from './market-panels.js';

const PERSIST = 'yfinance-grid';
const FIRST_VISIT = ['AAPL', 'MSFT', 'RELIANCE.NS', '^NSEI'];

/** Build the grid view in `doc` and return the grid. */
export function initGridView(doc = document) {
  const $ = id => doc.getElementById(id);
  const view = doc.defaultView;
  const storage = (() => { try { return view.localStorage; } catch { return null; } })();
  const read = key => { try { return storage?.getItem(key) ?? null; } catch { return null; } };
  const paintPage = name => {
    doc.documentElement.dataset.theme = name;
    doc.documentElement.style.colorScheme = name;
    try { storage?.setItem(THEME_KEY, name); } catch { /* private mode */ }
  };
  const theme = read(THEME_KEY) === 'light' ? 'light' : 'dark';
  paintPage(theme);

  // The grid restores its own last layout once its store (IndexedDB) has
  // answered, and a hand-off then replaces those charts. Their requests wait
  // until the hand-off is applied; by then the replaced charts have cancelled
  // them, so none reaches the source.
  const handed = takeGridHandoff((() => { try { return view.sessionStorage; } catch { return null; } })());
  let release = () => {};
  const ready = handed === null ? undefined : new Promise(resolve => { release = resolve; });
  const coarse = view.matchMedia?.('(pointer: coarse)').matches === true;
  const grid = createChartGrid($('grid'), {
    // Each chart loads the history period its layout saved.
    document: doc, feed: gridFeeds({ ready }), symbol: 'AAPL', exchange: '', interval: '1d', intervals: GRID_INTERVALS,
    theme, preset: '2x2', persist: PERSIST, links: { crosshair: true, viewport: true },
    // The grid's own bar: layouts up to sixteen charts, maximize, link groups,
    // one picture of every chart and the desk's saved layouts. The page's bar
    // keeps only the file. The bar under the charts acts on the active one.
    toolbar: true, bottombar: true,
    // Each chart's venue hours, as on the main page: the bar under the charts
    // says whether the active chart's market is open, and sizes its ranges in sessions.
    sessionCalendar: ({ symbol }) => sessionCalendarFor(symbol),
    // Saved desks for the bar's Layouts control, and indicator templates in
    // every chart's picker, in a database of their own: the main page's
    // layouts are one chart each, and its catalog lists only those.
    workspaces: new WorkspaceRepository(createIndexedDbWorkspaceStorage(view.indexedDB, 'yfinance-grid'), 'desk'),
    // Touch devices get the auto rule in each chart (compact in a phone-sized
    // cell, desktop in a tablet-sized one); a mouse keeps the desktop bar even
    // when a chart in a four-way split is narrow.
    mobile: coarse ? 'auto' : 'never',
    // Nothing here passes pane 0 for the price, so a chart may keep its price
    // pane below its studies, and a layout the main page saved that way opens.
    movablePrimaryPane: true,
    // Each chart's dock offers the main page's lists and news: one list store and
    // one shared quote poll for every chart, prices only from /api/quotes.
    watchlist: { store: referenceWatchlists(), quotes: referenceQuotes() },
    news: { feed: referenceNewsFeed },
  });
  const status = text => { $('grid-status-text').textContent = text; };
  const glyph = $('grid-glyph');
  glyph.style.display = 'inline-block';
  glyph.style.verticalAlign = '-3px';
  glyph.style.marginRight = '6px';
  const showLayout = () => {
    const { preset } = grid.layout();
    glyph.innerHTML = presetGlyph(preset);
    return GRID_PRESET_LABELS[preset] || preset || 'Custom layout';
  };
  grid.on('layout', ({ reason }) => {
    const name = showLayout();
    if (reason === 'preset') status(`${name}: ${grid.cells().length} charts`);
    else if (reason === 'swap') status('Charts swapped');
  });
  grid.on('theme', ({ theme: name }) => paintPage(name));
  showLayout();

  /** Validate the whole file, then apply it all or not at all. */
  const openLayout = (text, from) => {
    let payload;
    try { payload = readGridFile(text); }
    catch (error) { status(`Could not open the layout from ${from}: ${error.message}`); return false; }
    const report = grid.applyWorkspace(payload);
    status(report.applied ? `Opened the layout from ${from}: ${grid.cells().length} charts`
      : `Could not open the layout from ${from}, nothing changed: ${report.reason}`);
    return report.applied;
  };

  $('grid-import').addEventListener('click', () => { $('grid-file').value = ''; $('grid-file').click(); });
  $('grid-file').addEventListener('change', async () => {
    const file = $('grid-file').files?.[0];
    if (file) openLayout(await file.text(), file.name);
  });
  $('grid-export').addEventListener('click', () => {
    const text = JSON.stringify(gridDocument(grid.getWorkspace()), null, 2);
    const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    const anchor = doc.createElement('a');
    anchor.href = url;
    anchor.download = 'openalgo-grid-layout.json';
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status('Layout exported');
  });

  void grid.ready.then(() => {
    const restored = grid.restored();
    // A first visit shows four different instruments rather than one repeated.
    if (restored === null && handed === null) grid.cells().forEach((cell, i) => cell.widget.setSymbol(FIRST_VISIT[i] || 'AAPL'));
    showLayout();
    if (handed !== null) openLayout(handed, 'the main view');
    else if (restored?.applied === false) status(`The saved grid could not be restored and is kept until you change this one: ${restored.reason}`);
    else status(`${grid.cells().length} charts. Click a chart to make it active; drag a chart's bar to move it, double-click it to maximize.`);
    release();
    // For the tests: the grid as the page shows it, once its saved desk has landed.
    if (new URLSearchParams(view.location.search).get('test') === '1') view.__grid = grid;
  });
  return grid;
}
