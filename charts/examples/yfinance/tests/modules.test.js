// Every module evaluates outside a browser. A module that touched the DOM
// at import time, or reached a cyclic import's binding before it was
// initialised, throws here and nowhere else: in the page the failure would
// be a blank document.
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));

// main.js is the page itself: it builds the app and loads a symbol on
// import, so it is the one module that needs a document.
const MODULES = readdirSync(SRC).filter((f) => f.endsWith('.js') && f !== 'main.js').sort();

/** The init hook each module hands its state to, where it has one. */
const INIT = {
  'account.js': 'initAccount',
  'anchored-study.js': 'initAnchoredStudy',
  'axis-chrome.js': 'initAxisChrome',
  'box-settings.js': 'initBoxSettings',
  'bracket.js': 'initBracket',
  'chart-settings.js': 'initChartSettings',
  'clipboard.js': 'initClipboard',
  'compare.js': 'initCompare',
  'drawing.js': 'initDrawing',
  'feed.js': 'initFeed',
  'goto.js': 'initGoTo',
  'grid.js': 'initGridView',
  'history.js': 'initHistory',
  'hover.js': 'initHover',
  'indicators.js': 'initIndicators',
  'inspection.js': 'initInspection',
  'indicator-source.js': 'initIndicatorSource',
  'link.js': 'initLink',
  'menus.js': 'initMenus',
  'orders.js': 'initOrders',
  'persist.js': 'initPersist',
  'rail.js': 'initRail',
  'replay.js': 'initReplay',
  'routed-study.js': 'initRoutedStudy',
  'snapshot.js': 'initSnapshot',
  'split.js': 'initSplit',
  'status.js': 'initStatus',
  'timezone.js': 'initTimezone',
  'toolbar.js': 'initToolbar',
  'volume.js': 'initVolume',
  'workspaces.js': 'initWorkspaces',
  'templates.js': 'initTemplates',
};

describe('demo modules', () => {
  it('lists the modules the README documents', () => {
    expect(MODULES).toEqual([
      'account.js', 'alerts.js', 'anchored-study.js', 'axis-chrome.js', 'box-settings.js', 'bracket.js', 'canvas-tips.js', 'chart-data-controls.js', 'chart-data.js', 'chart-settings.js', 'clipboard.js', 'compare.js', 'drawing-scope.js', 'drawing.js',
      'expression.js', 'feed.js', 'goto.js', 'grid-view.js', 'grid.js', 'history.js', 'host-study.js', 'hover.js', 'indicator-input-controls.js', 'indicator-source.js', 'indicator-templates.js',
      'indicators.js', 'inspection.js', 'intervals.js', 'level-editor.js',
      'link.js', 'market-panels.js', 'menus.js', 'orders.js', 'pane-target.js', 'persist.js', 'properties.js', 'rail-flyout.js',
      'rail.js', 'replay-timing.js', 'replay.js', 'routed-study.js', 'session-marks.js', 'session.js', 'snapshot.js', 'split.js', 'status.js', 'symbol-search.js', 'templates.js', 'text-editor.js',
      'ticks.js', 'timeline.js', 'timezone.js', 'toolbar.js', 'transforms.js', 'ui.js', 'volume.js', 'workspace-catalog.js', 'workspace-document.js', 'workspace-host.js', 'workspace-transition.js', 'workspaces.js',
    ]);
  });

  it('uses engine branding once and snapshots it before teardown', () => {
    const main = readFileSync(SRC + 'main.js', 'utf8');

    expect(main).not.toContain("from './watermark.js'");
    expect(main).not.toContain("id === 'watermark'");
    const snapshot = main.indexOf('const decorations = chartDecorationsForRebuild(app.chart);');
    expect(snapshot).toBeGreaterThan(-1);
    expect(snapshot).toBeLessThan(main.indexOf('app.chart.destroy()'));
    expect(main).toContain('...decorations,');
    expect(main).toContain("app.chart.on('branding:changed', renderToolbar)");
  });

  for (const file of MODULES) {
    it(`${file} imports without a DOM and exposes its init`, async () => {
      const mod = await import(SRC + file);
      const init = INIT[file];
      if (init) expect(typeof mod[init], init).toBe('function');
      else expect(Object.keys(mod).length).toBeGreaterThan(0);
    });
  }
});
