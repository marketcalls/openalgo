/**
 * The chart grid's rules. Kept apart from grid.ts so the shared component
 * sheet can carry them without importing the grid, which imports the shell.
 * Every colour is a widget token, written on the grid root by the grid, apart
 * from the link group hues, which have one value per theme here. The bar's
 * menus bring their own rules when they load (grid-menus.ts).
 */

/** Link group hues, by letter: eight, repeated for groups I to P. The letter always says which group. */
const HUES_DARK = ['#5b9cf6', '#f0a445', '#4cc38a', '#d673d1', '#3fc1c9', '#d9c34a', '#ef6a6a', '#9d85f2'];
const HUES_LIGHT = ['#1f63c9', '#b8660b', '#17864f', '#a23c9e', '#0e7f86', '#8a7300', '#c0392b', '#6247c4'];
const hues = (theme: 'dark' | 'light', list: readonly string[]): string => [...'ABCDEFGHIJKLMNOP']
  .map((letter, i) => `.oac-grid[data-theme="${theme}"] [data-group="${letter}"] { --oac-group: ${list[i % list.length]}; }`).join('\n');

export const CHART_GRID_CSS = `
.oac-grid { position: relative; display: flex; flex-direction: column; width: 100%; height: 100%; min-width: 0; min-height: 0;
  background: var(--oac-bg); color: var(--oac-tx); font: var(--oac-fs)/1.35 var(--oac-font); }
.oac-grid [hidden] { display: none !important; }
.oac-grid__tabs { display: flex; gap: 2px; padding: 4px; overflow-x: auto; flex: none; background: var(--oac-panel);
  border-bottom: 1px solid var(--oac-bd-soft); scrollbar-width: thin; scrollbar-color: var(--oac-sb-thumb) transparent; }
.oac-grid__tabs::-webkit-scrollbar { height: 6px; }
.oac-grid__tabs::-webkit-scrollbar-thumb { background: var(--oac-sb-thumb); border-radius: 999px; }
.oac-grid__tab { flex: none; height: 26px; padding: 0 10px; border: 1px solid transparent; border-radius: var(--oac-radius);
  background: transparent; color: var(--oac-mut); font: inherit; cursor: pointer; white-space: nowrap; }
.oac-grid__tab:hover { color: var(--oac-tx); background: var(--oac-elev); }
.oac-grid__tab[aria-selected="true"] { color: var(--oac-tx-strong); background: var(--oac-on-bg); border-color: var(--oac-on-bd); }
.oac-grid__tab:focus-visible, .oac-grid__split:focus-visible { outline: 2px solid var(--oac-ring); outline-offset: -2px; }
.oac-grid__cells { position: relative; flex: 1; display: grid; min-height: 0; background: var(--oac-bd-soft); }
.oac-grid__cell { position: relative; min-width: 0; min-height: 0; overflow: hidden; }
.oac-grid__cell::after { content: ''; position: absolute; inset: 0; border: 1px solid transparent; pointer-events: none; z-index: 30; }
.oac-grid[data-single="false"][data-compact="false"]:not([data-maximized="true"]) .oac-grid__cell[data-active="true"]::after { border-color: var(--oac-acc); }
.oac-grid__split { position: relative; z-index: 31; touch-action: none; transition: background .12s; }
.oac-grid__split::before { content: ''; position: absolute; inset: 0 -3px; }
.oac-grid__split[data-axis="row"]::before { inset: -3px 0; }
.oac-grid__split[data-axis="column"] { cursor: col-resize; }
.oac-grid__split[data-axis="row"] { cursor: row-resize; }
.oac-grid__split:hover, .oac-grid__split.is-drag { background: var(--oac-acc); }
.oac-grid:is([data-compact="true"], [data-maximized="true"]) .oac-grid__cells { grid-template: minmax(0,1fr) / minmax(0,1fr) !important; }
.oac-grid:is([data-compact="true"], [data-maximized="true"]) .oac-grid__cell { grid-area: 1 / 1 / 2 / 2 !important; }

/* Dragging a chart by its bar onto another's place. */
.oac-grid[data-single="false"][data-compact="false"]:not([data-maximized="true"]) .oac-grid__cell .oac-topbar { cursor: grab; }
.oac-grid[data-single="false"][data-compact="false"]:not([data-maximized="true"]) .oac-grid__cell .oac-topbar input { cursor: text; }
.oac-grid[data-dragging="true"], .oac-grid[data-dragging="true"] * { cursor: grabbing !important; user-select: none; }
.oac-grid__cell[data-dragging="true"] { opacity: .55; }
.oac-grid__cell[data-drop="true"]::after { border: 2px dashed var(--oac-acc); background: var(--oac-on-bg); }

/* Dense cells: a chart a few hundred pixels across keeps its plot and the
   controls a chart needs every minute; the rest waits for maximize. */
/* One row that scrolls sideways rather than a bar wrapped over a third of the plot. */
.oac-grid__cell[data-dense="true"] :is(.oac-rail, .oac-rail-tab) { display: none; }
.oac-grid__cell[data-dense="true"] .oac-topbar { gap: 2px; padding: 3px 5px; flex-wrap: nowrap; overflow-x: auto; overflow-y: hidden;
  scrollbar-width: none; -webkit-mask-image: linear-gradient(to right, #000 calc(100% - 18px), transparent);
  mask-image: linear-gradient(to right, #000 calc(100% - 18px), transparent); }
.oac-grid__cell[data-dense="true"] .oac-topbar::-webkit-scrollbar { display: none; }
.oac-grid__cell[data-dense="true"] .oac-topbar > * { flex-shrink: 0; }
.oac-grid__cell[data-dense="true"] .oac-sym > input { width: 96px; }
.oac-grid__cell[data-dense="true"] .oac-sym__ex { display: none; }
.oac-grid__cell[data-dense="true"] :is(.oac-topbar__goto, .oac-topbar__objects, .oac-topbar__data, .oac-topbar__watchlist,
  .oac-topbar__news, .oac-topbar__alerts, .oac-topbar__theme, .oac-topbar__branding-slot, .oac-topbar__spacer + .oac-sep) { display: none; }
/* A label goes where its glyph shows: a host's chart type with none keeps its name. */
.oac-grid__cell[data-dense="true"] .oac-topbar > .oac-btn > span:not(.oac-glyph):not(.oac-chev):not([hidden] + span) { display: none; }

/* The grid's own chrome takes the widget's controls; these rules only place it. The bar's strip
   holds its height (a control and its padding) before the bar loads into it (grid-bar.ts). */
.oac-widget.oac-grid__bar { position: relative; display: flex; align-items: center; gap: 4px; flex: none; height: auto;
  min-height: calc(var(--oac-ctl-h) + 9px); padding: 4px 6px; background: var(--oac-panel); border-bottom: 1px solid var(--oac-bd-soft);
  overflow: visible; container: oac-grid-bar / inline-size; }
/* One bar under the charts: the widget's own strip, acting on the active chart. */
.oac-widget.oac-grid__foot { display: block; flex: none; height: auto; min-height: 0; }
.oac-widget.oac-grid__overlay { position: absolute; inset: 0; display: block; background: transparent; pointer-events: none;
  z-index: 80; overflow: visible; }
/* A link group mark: the letter on a panel, the group's hue as a stripe. */
.oac-grid__chip { display: inline-flex; align-items: center; justify-content: center; min-width: 17px; height: 17px;
  padding: 0 4px 0 6px; border-radius: 4px; background: var(--oac-elev-2); color: var(--oac-tx-strong);
  box-shadow: inset 3px 0 0 var(--oac-group, var(--oac-faint)); font: 700 10.5px/1 var(--oac-font); flex: none; }
.oac-grid__chip[data-group="none"] { padding: 0 3px; box-shadow: none; background: transparent; color: var(--oac-faint); }
.oac-grid__chip[data-group="none"] > svg { width: 13px; height: 13px; fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round; }
.oac-grid__mark { display: inline-flex; align-items: center; justify-content: center; height: 24px; min-width: 24px; padding: 0 3px;
  margin-right: 2px; border: 1px solid transparent; border-radius: 6px; background: transparent; cursor: pointer; flex: none; }
.oac-grid__mark:hover { background: var(--oac-elev); border-color: var(--oac-bd-soft); }
.oac-grid__mark:focus-visible { outline: 2px solid var(--oac-ring); outline-offset: -1px; }
.oac-grid__mark--float { position: absolute; top: 6px; left: 6px; z-index: 32; background: var(--oac-panel); border-color: var(--oac-bd-soft); }
${hues('dark', HUES_DARK)}
${hues('light', HUES_LIGHT)}
@media (prefers-reduced-motion: reduce) {
  .oac-grid__split { transition: none; }
}
`;
