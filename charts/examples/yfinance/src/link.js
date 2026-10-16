import { el } from './ui.js';
import { renderToolbar } from './toolbar.js';
import { popupMenu } from './menus.js';
import { isSplit, openSplit, closeSplit } from './split.js';
import { autosave } from './persist.js';
import { capturePaneTarget } from './pane-target.js';

let app;
export function initLink(a) { app = a; }

// ── link switches ──────────────────────────────────────────────────────

export function describeLink() {
  if (!app.linkGroup) return 'unavailable';
  const o = app.linkGroup.options();
  const on = ['crosshair', 'viewport', 'symbol', 'interval', 'appearance'].filter((k) => o[k]);
  if (app.drawingLinkGroup?.options().enabled) on.push('drawings');
  return on.length ? on.join(' + ') : 'nothing synced';
}

export function setLink(patch) {
  if (!app.linkGroup) return;
  app.linkGroup.setOptions(patch);
  autosave();
  renderToolbar();
  el('status').textContent = 'link: ' + describeLink()
    + ' · missing instant: ' + app.linkGroup.options().whenMissing;
}

export function openLinkMenu(anchor) {
  if (!app.linkGroup) {
    el('status').textContent = 'this dist/ has no chart linking';
    return;
  }
  const o = app.linkGroup.options();
  const rows = [
    { group: 'Layout' },
    {
      // Named for the action, so it carries no checked state as well.
      label: isSplit() ? 'Close the second chart' : 'Open a second chart',
      icon: 'split',
      onSelect: () => (isSplit() ? closeSplit() : openSplit()),
    },
    // More than two charts, or rows, live in the grid view: a page built on
    // the widget tier's chart grid over the same feed.
    { label: 'Open the chart grid', icon: 'gridView', onSelect: () => location.assign('grid.html') },
    { group: isSplit() ? 'Sync' : 'Sync (open the second chart to see it)' },
    { label: 'Crosshair', check: true, on: o.crosshair, onSelect: () => setLink({ crosshair: !o.crosshair }) },
    { label: 'Viewport', check: true, on: o.viewport, onSelect: () => setLink({ viewport: !o.viewport }) },
    { label: 'Symbol', check: true, on: o.symbol, onSelect: () => setLink({ symbol: !o.symbol }) },
    { label: 'Interval', check: true, on: o.interval, disabled: typeof app.linkGroup.setInterval !== 'function',
      reason: typeof app.linkGroup.setInterval !== 'function' ? 'This build has no interval linking' : '',
      onSelect: () => setLink({ interval: !o.interval }) },
    { label: 'Appearance', check: true, on: o.appearance, onSelect: () => setLink({ appearance: !o.appearance }) },
    { label: 'Drawings (same instrument)', check: true, on: app.drawingLinkGroup?.options().enabled,
      onSelect: () => {
        app.drawingLinkGroup?.setOptions({ enabled: !app.drawingLinkGroup.options().enabled });
        renderToolbar();
      } },
    { label: 'Share existing drawings from selected chart',
      disabled: !app.drawingLinkGroup?.options().enabled || !isSplit(),
      reason: 'Enable drawing sync and open the second chart',
      onSelect: () => {
        const target = capturePaneTarget(app);
        if (target?.current()) app.drawingLinkGroup.share(target.chart);
      } },
    { group: 'When the follower has no such bar' },
    { label: 'Snap to the nearest bar', on: o.whenMissing === 'nearest', onSelect: () => setLink({ whenMissing: 'nearest' }) },
    { label: 'Draw nothing', on: o.whenMissing === 'hide', onSelect: () => setLink({ whenMissing: 'hide' }) },
  ];
  popupMenu(anchor, rows);
}
