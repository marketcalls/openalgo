/**
 * The widget stylesheet: one `<style>` per document, every rule scoped under
 * `.oac-widget`, every colour a token from `tokens.ts`.
 *
 * Nothing here names a colour twice or reaches outside the widget root. A
 * host page keeps its own cascade, and two widgets on one page share the one
 * sheet while carrying their own token values inline, so one can be dark and
 * the other light.
 *
 * The rules follow the craft standard in CLAUDE.md: styled scrollbars on
 * every scrolling surface, no browser-default checkbox, select or colour
 * input, small square swatches, dense rows, muted uppercase section heads.
 * The dialog modules mount inside `.oac-widget`, so they inherit all of it.
 */

import { token as v } from './tokens';
import { ICON_SIZE, ICON_STROKE, CHROME_ICON_SIZE, CHROME_ICON_STROKE } from 'openalgo-charts/draw';

/** Id of the injected `<style>`; one per document. */
export const WIDGET_STYLE_ID = 'oac-widget-css';

export const WIDGET_CSS = `
.oac-widget { position: relative; display: grid; grid-template-rows: auto 1fr auto; width: 100%; height: 100%;
  min-height: 0; min-width: 0; background: ${v('bg')}; color: ${v('tx')}; font: ${v('fs')}/1.35 ${v('font')};
  -webkit-font-smoothing: antialiased; overflow: hidden; }
.oac-widget, .oac-widget * { box-sizing: border-box; }
.oac-widget.oac-alert-host { position: absolute; inset: 0; display: block; background: transparent; pointer-events: none; z-index: 40; }
.oac-widget[data-theme="dark"] { color-scheme: dark; }
.oac-widget[data-theme="light"] { color-scheme: light; }
.oac-widget button, .oac-widget input, .oac-widget select, .oac-widget textarea { font: inherit; color: inherit; }
.oac-widget button { cursor: pointer; }
.oac-widget kbd { font: 11px/1 ${v('mono')}; font-variant-numeric: tabular-nums; }
.oac-widget [hidden] { display: none !important; }
.oac-widget .oac-row:has(> .oac-input-error:not([hidden])) { flex-wrap: wrap; }
.oac-widget .oac-input-error { flex-basis: 100%; min-width: 0; color: ${v('danger')}; font-size: 11px; overflow-wrap: anywhere; }
.oac-widget .oac-row__ctl:has([data-input-action]) { flex-wrap: wrap; }
.oac-widget .oac-row__ctl [data-input-action] { font-size: 11px; padding: 3px 7px; }
.oac-widget [aria-invalid="true"] { border-color: ${v('danger')}; }
.oac-widget .oac-input-pick { position: absolute; top: 8px; left: 50%; transform: translateX(-50%);
  display: flex; align-items: center; gap: 8px; max-width: calc(100% - 16px); padding: 8px;
  color: ${v('tx')}; background: ${v('panel')}; border: 1px solid ${v('bd')}; border-radius: 6px; pointer-events: auto; }

/* Scrollbars: a thumb one step lighter than its panel, and no visible track. */
.oac-widget * { scrollbar-width: thin; scrollbar-color: ${v('sb-thumb')} transparent; }
.oac-widget ::-webkit-scrollbar { width: 10px; height: 10px; }
.oac-widget ::-webkit-scrollbar-track { background: transparent; }
.oac-widget ::-webkit-scrollbar-thumb { background: ${v('sb-thumb')}; border: 2px solid transparent;
  background-clip: padding-box; border-radius: 999px; }
.oac-widget ::-webkit-scrollbar-thumb:hover { background: ${v('sb-thumb-hover')}; background-clip: padding-box; }
.oac-widget ::-webkit-scrollbar-corner { background: transparent; }

/* Focus: one ring, keyboard only. Text fields glow on the border instead. */
.oac-widget :focus-visible { outline: 2px solid ${v('ring')}; outline-offset: 2px; }
.oac-widget :focus:not(:focus-visible) { outline: none; }
.oac-widget input:not([type=checkbox]):not([type=color]):not([type=range]):focus-visible,
.oac-widget select:focus-visible, .oac-widget textarea:focus-visible {
  outline: none; border-color: ${v('acc')}; box-shadow: 0 0 0 3px ${v('ring-soft')}; }
.oac-widget .oac-sr { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; border: 0;
  overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; }

/* Form controls: nothing left to the browser on a themed panel. */
.oac-widget input[type=checkbox] { appearance: none; -webkit-appearance: none; flex: none; margin: 0;
  width: 15px; height: 15px; border: 1px solid ${v('bd')}; border-radius: 4px; background: ${v('elev')};
  cursor: pointer; display: inline-grid; place-content: center; transition: background .12s, border-color .12s; }
.oac-widget input[type=checkbox]:hover { border-color: ${v('bd-hover')}; }
.oac-widget input[type=checkbox]:checked { background: ${v('acc')}; border-color: ${v('acc')}; }
.oac-widget input[type=checkbox]:checked::after { content: ''; width: 4px; height: 8px; margin-top: -2px;
  border: solid ${v('bg')}; border-width: 0 2px 2px 0; transform: rotate(45deg); }
.oac-widget input[type=checkbox]:disabled { opacity: .4; cursor: not-allowed; }
/* A radio is the checkbox's round sibling; the dot is an inset ring, which needs no pseudo-element. */
.oac-widget input[type=radio] { appearance: none; -webkit-appearance: none; flex: none; margin: 0; width: 15px; height: 15px;
  border: 1px solid ${v('bd')}; border-radius: 50%; background: ${v('elev')}; cursor: pointer; transition: background .12s, border-color .12s; }
.oac-widget input[type=radio]:hover { border-color: ${v('bd-hover')}; }
.oac-widget input[type=radio]:checked { border-color: ${v('acc')}; background: ${v('acc')}; box-shadow: inset 0 0 0 3px ${v('elev')}; }
.oac-widget select { appearance: none; -webkit-appearance: none; height: ${v('ctl-h')}; padding: 0 24px 0 8px;
  background: ${v('elev')}; border: 1px solid ${v('bd')}; border-radius: ${v('radius')}; cursor: pointer; }
.oac-widget .oac-select { position: relative; display: inline-flex; }
/* The chevron overlays the select rather than sitting beside it. selectBox
   wraps the glyph in an oac-chev span, and this rule used to name
   .oac-select > svg, which that markup has never had: the span stayed an
   ordinary flex item, so it took eleven pixels of the row and left the select
   eleven pixels short of every input beside it, with its arrow outside its own
   box. Sized here rather than left to .oac-chev, whose inline-grid is right
   where a chevron follows a word, as it does in the top bar. */
.oac-widget .oac-select > .oac-chev { position: absolute; right: 7px; top: 50%; width: 11px; height: 11px;
  transform: translateY(-50%); pointer-events: none; display: block; color: ${v('mut')}; }
.oac-widget select option, .oac-widget select optgroup { background: ${v('panel')}; color: ${v('tx')}; }
.oac-widget input[type=color] { width: 26px; height: 26px; padding: 0; flex: none; cursor: pointer; appearance: none;
  -webkit-appearance: none; background-color: ${v('elev')}; border: 1px solid ${v('bd')}; border-radius: ${v('radius')}; }
.oac-widget input[type=color]:hover { border-color: ${v('bd-hover')}; }
.oac-widget input[type=color]::-webkit-color-swatch-wrapper { padding: 3px; }
.oac-widget input[type=color]::-webkit-color-swatch { border: 1px solid rgba(0,0,0,.35); border-radius: 4px; }
.oac-widget input[type=color]::-moz-color-swatch { border: 1px solid rgba(0,0,0,.35); border-radius: 4px; }
.oac-widget .oac-swatch { width: 20px; height: 20px; border-radius: 5px; border: 1px solid rgba(0,0,0,.35); }
.oac-widget input[type=number] { -moz-appearance: textfield; appearance: textfield; }
.oac-widget input[type=number]::-webkit-inner-spin-button, .oac-widget input[type=number]::-webkit-outer-spin-button {
  -webkit-appearance: none; margin: 0; }
.oac-widget input[type=text], .oac-widget input[type=number], .oac-widget input[type=search], .oac-widget textarea {
  height: ${v('ctl-h')}; padding: 0 8px; background: ${v('elev')}; border: 1px solid ${v('bd')}; border-radius: ${v('radius')};
  transition: border-color .15s, box-shadow .15s; }
.oac-widget textarea { height: auto; padding: 6px 8px; }
.oac-widget input::placeholder { color: ${v('faint')}; }
.oac-widget input:hover, .oac-widget select:hover { border-color: ${v('bd-hover')}; }
.oac-widget input[type=range] { appearance: none; -webkit-appearance: none; height: 22px; margin: 0;
  background: transparent; cursor: pointer; }
.oac-widget input[type=range]::-webkit-slider-runnable-track { height: 3px; border-radius: 2px; background: ${v('elev-3')}; }
.oac-widget input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 12px; height: 12px;
  margin-top: -4.5px; border-radius: 50%; background: ${v('acc')}; border: 0; }
.oac-widget input[type=range]::-moz-range-track { height: 3px; border-radius: 2px; background: ${v('elev-3')}; }
.oac-widget input[type=range]::-moz-range-thumb { width: 12px; height: 12px; border-radius: 50%; background: ${v('acc')}; border: 0; }

/* Section heads and rows shared by every panel. */
.oac-widget .oac-head { padding: 8px 10px 4px; color: ${v('faint')}; font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .7px; }
.oac-widget .oac-row { display: flex; align-items: center; gap: 8px; min-height: 26px; padding: 2px 0; }
.oac-widget .oac-row > label { flex: 1 1 auto; min-width: 0; color: ${v('tx')}; }

/* Help mark: a 13px ring after a label, muted until pointed at. It must not
   grow the row, so it sits on the label's own line box and never wraps away
   from the words it belongs to. */
.oac-widget .oac-help { display: inline-flex; align-items: center; justify-content: center;
  width: 13px; height: 13px; margin-left: 5px; vertical-align: -2px; flex: none;
  border: 1px solid ${v('bd')}; border-radius: 50%; color: ${v('faint')};
  font-size: 9px; font-weight: 600; line-height: 1; cursor: help; user-select: none; }
.oac-widget .oac-help:hover { color: ${v('tx')}; border-color: ${v('bd-hover')}; }
/* A heading's rows as one named group, laid out as if the box were not there. */
.oac-widget .oac-form__group { display: contents; }

/* Buttons: flat, 28px tall, a tint when pressed or active. */
.oac-widget .oac-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  height: ${v('ctl-h')}; padding: 0 9px; background: transparent; border: 1px solid transparent;
  border-radius: ${v('radius')}; color: ${v('tx')}; white-space: nowrap; transition: background .1s, border-color .1s, color .1s; }
.oac-widget .oac-btn:hover { background: ${v('elev')}; border-color: ${v('bd-soft')}; }
.oac-widget .oac-btn.is-on, .oac-widget .oac-btn[aria-pressed="true"], .oac-widget .oac-btn[aria-expanded="true"] {
  background: ${v('on-bg')}; border-color: ${v('on-bd')}; color: ${v('acc-2')}; }
.oac-widget .oac-btn.is-off, .oac-widget .oac-btn[aria-disabled="true"], .oac-widget .oac-btn:disabled {
  color: ${v('faint')}; cursor: default; }
.oac-widget .oac-btn.is-off:hover, .oac-widget .oac-btn[aria-disabled="true"]:hover, .oac-widget .oac-btn:disabled:hover {
  background: transparent; border-color: transparent; }
.oac-widget .oac-btn--icon { width: ${v('ctl-h')}; padding: 0; }
.oac-widget .oac-btn--primary { background: ${v('acc')}; color: ${v('bg')}; border-color: transparent; font-weight: 600; }
.oac-widget .oac-btn--primary:hover { background: ${v('acc-2')}; border-color: transparent; }
.oac-widget .oac-btn--danger:not(.is-off):hover { color: ${v('danger')}; }
.oac-widget .oac-btn > b { font-weight: 700; letter-spacing: .3px; }
.oac-widget .oac-glyph { display: inline-grid; place-items: center; line-height: 0; flex: none; }
.oac-widget .oac-glyph > svg { fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; }
.oac-widget .oac-glyph--tool > svg { width: ${ICON_SIZE}px; height: ${ICON_SIZE}px; stroke-width: ${ICON_STROKE}; }
.oac-widget .oac-glyph--chrome > svg { width: ${CHROME_ICON_SIZE}px; height: ${CHROME_ICON_SIZE}px; stroke-width: ${CHROME_ICON_STROKE}; }
.oac-widget .oac-glyph--text { display: inline-grid; place-items: center; width: ${ICON_SIZE}px; height: ${ICON_SIZE}px;
  font-size: 12px; font-weight: 600; }
.oac-widget .oac-chev { display: inline-grid; place-items: center; line-height: 0; color: ${v('mut')}; }
.oac-widget .oac-chev > svg { width: 11px; height: 11px; fill: none; stroke: currentColor; stroke-width: 1.5;
  stroke-linecap: round; stroke-linejoin: round; }
.oac-widget .oac-sep { width: 1px; height: 20px; background: ${v('bd-soft')}; margin: 0 2px; flex: none; }

/* Top bar */
.oac-widget .oac-topbar { grid-row: 1; display: flex; align-items: center; gap: 4px; min-height: ${v('topbar-h')};
  padding: 5px 8px; background: ${v('panel')}; border-bottom: 1px solid ${v('bd-soft')}; flex-wrap: wrap; }
.oac-widget .oac-topbar__spacer { flex: 1 1 auto; }
.oac-widget .oac-topbar__branding-slot { display: inline-flex; align-items: center; }
.oac-widget .oac-topbar__branding { color: ${v('mut')}; font-size: 11px; text-decoration: none; white-space: nowrap; }
.oac-widget .oac-topbar__branding:hover { color: ${v('tx')}; text-decoration: underline; }
.oac-widget .oac-sym { position: relative; display: inline-flex; align-items: center; }
.oac-widget .oac-sym > input { width: 132px; height: ${v('ctl-h')}; padding: 0 8px 0 28px; font-weight: 600;
  letter-spacing: .3px; text-transform: uppercase; }
.oac-widget .oac-sym > .oac-glyph { position: absolute; left: 8px; color: ${v('mut')}; pointer-events: none; }
.oac-widget .oac-sym__ex { margin-left: 6px; color: ${v('faint')}; font-size: 11px; font-weight: 600; letter-spacing: .5px; }
.oac-widget .oac-pills { display: inline-flex; background: ${v('elev')}; border: 1px solid ${v('bd-soft')};
  border-radius: 7px; padding: 2px; }
.oac-widget .oac-pills > button { height: 22px; padding: 0 8px; background: transparent; border: 0; border-radius: 5px;
  color: ${v('mut')}; font-weight: 600; font-size: 11.5px; letter-spacing: .2px; }
.oac-widget .oac-pills > button:hover { color: ${v('tx')}; }
.oac-widget .oac-pills > button[aria-pressed="true"] { background: ${v('elev-2')}; color: ${v('acc-2')}; }
.oac-widget .oac-pills > button:focus-visible { outline-offset: -1px; }

/* Popup menu (chart types, screenshot, symbol results) */
.oac-widget .oac-menu { min-width: 190px; max-width: 320px; max-height: 60vh; overflow-y: auto; padding: 5px;
  background: ${v('panel')}; border: 1px solid ${v('bd')}; border-radius: 9px; box-shadow: ${v('shadow')}; outline: none; }
.oac-widget .oac-menu__find { padding: 3px 3px 6px; }
.oac-widget .oac-menu__find > input { width: 100%; }
.oac-widget .oac-menu__row { display: flex; align-items: center; gap: 9px; width: 100%; padding: 6px 8px;
  background: transparent; border: 0; border-radius: 6px; color: ${v('tx')}; text-align: left; white-space: nowrap; }
.oac-widget .oac-menu__row:hover, .oac-widget .oac-menu__row:focus-visible, .oac-widget .oac-menu__row.is-active {
  background: ${v('elev-2')}; outline: none; }
.oac-widget .oac-menu__row[aria-checked="true"] { color: ${v('acc-2')}; }
.oac-widget .oac-menu__row[aria-checked="true"]::before { content: ''; width: 6px; height: 6px; border-radius: 50%;
  background: ${v('acc-2')}; margin: 0 2px 0 -2px; flex: none; }
.oac-widget .oac-menu__row[aria-checked="false"]::before { content: ''; width: 6px; height: 6px; margin: 0 2px 0 -2px; flex: none; }
.oac-widget .oac-menu__row[aria-disabled="true"] { color: ${v('faint')}; cursor: default; background: transparent; }
.oac-widget .oac-menu__row.is-danger:hover { color: ${v('danger')}; }
.oac-widget .oac-menu__label { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.oac-widget .oac-menu__sub { color: ${v('faint')}; font-size: 11px; }
.oac-widget .oac-menu__key { margin-left: auto; color: ${v('faint')}; }
.oac-widget .oac-menu__empty { padding: 8px 10px; color: ${v('faint')}; }
/* A hovered row is elev-2, where faint text no longer reads: its hints brighten with it. */
.oac-widget .oac-menu__row:is(:hover, :focus-visible, .is-active) :is(.oac-menu__sub, .oac-menu__key),
.oac-widget .oac-fly__row:is(:hover, :focus-visible) .oac-fly__chord { color: ${v('mut')}; }

/* Stage: the rail on the left, the chart filling the rest. */
.oac-widget .oac-stage { grid-row: 2; position: relative; min-height: 0; min-width: 0; display: flex; }
.oac-widget .oac-chart { position: relative; flex: 1 1 auto; min-width: 0; min-height: 0;
  cursor: var(--oac-tool-cursor, crosshair); }
.oac-widget .oac-chart:focus-visible { outline-offset: -2px; }

/* Data state stays compact inside a chart, including narrow embedded widgets. */
.oac-widget .oac-data-status { position: absolute; top: 8px; right: 8px; z-index: 30;
  max-width: calc(100% - 16px); width: max-content; max-height: 45%; overflow-y: auto;
  display: flex; flex-direction: column; gap: 4px; pointer-events: none; font-size: 12px; }
.oac-widget .oac-data-status__row { display: flex; align-items: center; gap: 8px;
  max-width: 320px; padding: 4px 6px 4px 10px; background: ${v('panel')}; color: ${v('tx')};
  border: 1px solid ${v('bd')}; border-radius: 6px; pointer-events: auto; }
.oac-widget .oac-data-status__text { min-width: 0; overflow-wrap: anywhere; }
.oac-widget .oac-data-status__row > button { flex: none; color: ${v('acc-2')}; }

/* Rail */
.oac-widget .oac-rail { flex: none; width: ${v('rail-w')}; display: flex; flex-direction: column; align-items: center;
  gap: 2px; padding: 6px 0 0; background: ${v('panel-2')}; border-right: 1px solid ${v('bd-soft')};
  overflow-y: auto; overflow-x: hidden; scrollbar-width: none; }
.oac-widget .oac-rail::-webkit-scrollbar { width: 0; height: 0; }
.oac-widget .oac-rail__btn { position: relative; width: 32px; height: 30px; padding: 0; display: grid; place-items: center;
  flex: none; background: transparent; border: 1px solid transparent; border-radius: 6px; color: ${v('mut')};
  transition: background .09s, color .09s, border-color .09s; }
.oac-widget .oac-rail__btn:hover { background: ${v('elev')}; color: ${v('tx')}; }
.oac-widget .oac-rail__btn:focus-visible { outline: 2px solid ${v('acc-2')}; outline-offset: -2px; }
.oac-widget .oac-rail__btn.is-on { background: ${v('on-bg')}; border-color: ${v('on-bd')}; color: ${v('acc-2')}; }
.oac-widget .oac-rail__btn.is-weak { color: ${v('acc-2')}; }
.oac-widget .oac-rail__btn.is-off { color: ${v('faint')}; cursor: default; }
.oac-widget .oac-rail__btn.is-off:hover { background: transparent; color: ${v('faint')}; }
.oac-widget .oac-rail__btn--danger:not(.is-off):hover { color: ${v('danger')}; }
.oac-widget .oac-rail__chev { position: absolute; right: 0; bottom: 0; width: 13px; height: 13px; display: grid;
  place-items: center; border-radius: 5px 0 6px 0; color: ${v('mut')}; opacity: 0; transition: opacity .1s, background .1s; }
.oac-widget .oac-rail__chev > svg { width: 9px; height: 9px; fill: none; stroke: currentColor; stroke-width: 2.2;
  stroke-linecap: round; stroke-linejoin: round; }
.oac-widget .oac-rail__btn:hover .oac-rail__chev, .oac-widget .oac-rail__btn:focus-visible .oac-rail__chev,
.oac-widget .oac-rail__btn[aria-expanded="true"] .oac-rail__chev { opacity: 1; }
.oac-widget .oac-rail__chev:hover { background: ${v('elev-2')}; color: ${v('tx')}; }
.oac-widget .oac-rail__btn.is-held::after, .oac-widget .oac-rail__btn[data-mode="weak"]::after,
.oac-widget .oac-rail__btn[data-mode="strong"]::after { content: ''; position: absolute; top: 3px; right: 3px;
  width: 5px; height: 5px; border-radius: 50%; }
.oac-widget .oac-rail__btn.is-held::after, .oac-widget .oac-rail__btn[data-mode="strong"]::after { background: ${v('acc-2')}; }
.oac-widget .oac-rail__btn[data-mode="weak"]::after { border: 1.5px solid ${v('acc-2')}; width: 4px; height: 4px; }
.oac-widget .oac-rail__sep { width: 22px; height: 1px; background: ${v('bd-soft')}; margin: 4px 0; flex: none; }
.oac-widget .oac-rail__favs { display: contents; }
.oac-widget .oac-rail__ctl { margin-top: auto; position: sticky; bottom: 0; display: flex; flex-direction: column;
  align-items: center; gap: 2px; width: 100%; padding: 4px 0 6px; background: ${v('panel-2')};
  border-top: 1px solid ${v('bd-soft')}; flex: none; }
/* Tools that scroll under the controls fade out instead of being cut through. */
.oac-widget .oac-rail__ctl::before { content: ''; position: absolute; left: 0; right: 0; bottom: 100%; height: 14px;
  background: linear-gradient(to bottom, transparent, ${v('panel-2')}); pointer-events: none; }
.oac-widget .oac-rail__ctl .oac-rail__sep { margin: 3px 0; }
.oac-widget .oac-rail.is-collapsed { display: none; }
.oac-widget .oac-rail-tab { position: absolute; left: 0; bottom: 6px; z-index: 6; width: 16px; height: 26px; padding: 0;
  display: grid; place-items: center; background: ${v('panel-2')}; color: ${v('mut')};
  border: 1px solid ${v('bd-soft')}; border-left: 0; border-radius: 0 6px 6px 0;
  transition: background .09s, color .09s, width .09s; }
.oac-widget .oac-rail-tab:hover { width: 20px; background: ${v('elev')}; color: ${v('tx')}; }
.oac-widget .oac-rail-tab:focus-visible { outline: 2px solid ${v('acc-2')}; outline-offset: -2px; }
.oac-widget .oac-rail-tab > svg { width: 12px; height: 12px; }
.oac-widget .oac-rail-tab[hidden] { display: none; }

/* Rail flyout: a group's tools, with a pin star and the chord on each row. */
.oac-widget .oac-fly { min-width: 244px; max-width: 320px; max-height: calc(100% - 16px); overflow-y: auto; padding: 6px;
  background: ${v('panel')}; border: 1px solid ${v('bd')}; border-radius: 10px; box-shadow: ${v('shadow')}; outline: none; }
.oac-widget .oac-fly__row { display: flex; align-items: center; gap: 8px; padding: 4px 6px 4px 8px; border-radius: 7px;
  color: ${v('tx')}; font-size: 13px; cursor: pointer; outline: none; user-select: none; }
.oac-widget .oac-fly__row:hover, .oac-widget .oac-fly__row:focus-visible { background: ${v('elev-2')}; }
.oac-widget .oac-fly__row[aria-checked="true"] { background: ${v('on-bg')}; color: ${v('acc-2')}; }
.oac-widget .oac-fly__name { flex: 1 1 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.oac-widget .oac-fly__chord { min-width: 40px; text-align: right; color: ${v('faint')}; }
.oac-widget .oac-fly__star { width: 22px; height: 22px; display: grid; place-items: center; padding: 0; border: 0;
  border-radius: 5px; background: transparent; color: ${v('faint')}; opacity: 0; transition: opacity .1s, color .1s; }
.oac-widget .oac-fly__row:hover .oac-fly__star, .oac-widget .oac-fly__row:focus-within .oac-fly__star,
.oac-widget .oac-fly__star[aria-pressed="true"] { opacity: 1; }
.oac-widget .oac-fly__star:hover { background: ${v('elev')}; color: ${v('tx')}; }
.oac-widget .oac-fly__star:focus-visible { outline: 2px solid ${v('acc-2')}; outline-offset: -1px; opacity: 1; }
.oac-widget .oac-fly__star[aria-pressed="true"] { color: ${v('amber')}; }
.oac-widget .oac-fly__star > svg { width: 14px; height: 14px; stroke: currentColor; stroke-width: 1.5;
  stroke-linecap: round; stroke-linejoin: round; }
.oac-widget .oac-fly__star[aria-pressed="false"] > svg { fill: none; }

/* Tooltip */
.oac-widget .oac-tip-spot { position: absolute; width: 1px; height: 1px; pointer-events: none; }
.oac-widget .oac-tip { position: absolute; z-index: 200; left: 0; top: 0; max-width: 260px; pointer-events: none;
  padding: 5px 9px; border-radius: 6px; background: ${v('elev-2')}; color: ${v('tx')}; border: 1px solid ${v('bd')};
  box-shadow: ${v('shadow')}; font-size: 12px; line-height: 1.4; opacity: 0; transition: opacity .09s ease; }
.oac-widget .oac-tip.is-on { opacity: 1; }
.oac-widget .oac-tip__chord { margin-left: 10px; color: ${v('mut')}; }
/* The tip sits on elev-2, a step above the surfaces faint text is measured on. */
.oac-widget .oac-tip__sub { display: block; margin-top: 2px; color: ${v('mut')}; font-size: 11px; }

/* Status line */
.oac-widget .oac-statusline { grid-row: 3; display: flex; align-items: center; gap: 12px; height: ${v('status-h')}; padding: 0 10px;
  background: ${v('panel')}; border-top: 1px solid ${v('bd-soft')}; color: ${v('mut')}; font-size: 11.5px;
  font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; }
.oac-widget .oac-statusline__sym { color: ${v('tx-strong')}; font-weight: 600; letter-spacing: .3px; }
.oac-widget .oac-statusline__iv { color: ${v('faint')}; margin-left: 4px; font-weight: 600; }
.oac-widget .oac-statusline__field { display: inline-flex; align-items: center; gap: 4px; }
.oac-widget .oac-statusline__field > i { font-style: normal; color: ${v('faint')}; }
.oac-widget .oac-statusline__field > b { font-weight: 500; color: ${v('tx')}; }
.oac-widget .oac-statusline .is-up > b { color: ${v('up')}; }
.oac-widget .oac-statusline .is-down > b { color: ${v('down')}; }
.oac-widget .oac-statusline__msg { margin-left: auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; color: ${v('mut')}; }
.oac-widget .oac-statusline__msg.is-error { color: ${v('danger')}; }
.oac-widget .oac-statusline__tz { color: ${v('faint')}; }

/* Narrow widget chrome */
.oac-widget .oac-mobile { display: none; }
.oac-widget.is-mobile { grid-template-rows: auto minmax(0, 1fr) auto; }
.oac-widget.is-mobile > .oac-topbar, .oac-widget.is-mobile > .oac-statusline,
.oac-widget.is-mobile > .oac-stage > :is(.oac-rail, .oac-rail-tab) { display: none; }
.oac-widget.is-mobile > .oac-stage { grid-row: 2; }
.oac-widget.is-mobile > .oac-mobile { display: contents; }
.oac-widget .oac-mobile__header { grid-row: 1; z-index: 40; display: grid; grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px; min-height: 52px; padding: calc(4px + env(safe-area-inset-top)) max(8px, env(safe-area-inset-right)) 4px
  max(8px, env(safe-area-inset-left)); background: ${v('panel')}; border-bottom: 1px solid ${v('bd-soft')}; }
.oac-widget .oac-mobile__symbol { width: 100%; min-width: 0; height: 44px; text-transform: uppercase; font-weight: 600; }
.oac-widget .oac-mobile__footer { grid-row: 3; z-index: 40; min-width: 0; padding-bottom: env(safe-area-inset-bottom);
  background: ${v('panel')}; border-top: 1px solid ${v('bd-soft')}; }
.oac-widget .oac-mobile__bar, .oac-widget .oac-mobile__selection { display: grid; grid-auto-flow: column;
  grid-auto-columns: minmax(0, 1fr); min-width: 0; }
.oac-widget .oac-mobile__selection { border-bottom: 1px solid ${v('bd-soft')}; }
.oac-widget .oac-mobile__action { min-width: 0; min-height: 44px; padding: 6px 10px; border: 0; border-radius: 0;
  background: transparent; color: ${v('tx')}; overflow-wrap: anywhere; touch-action: manipulation; }
.oac-widget .oac-mobile__action:hover, .oac-widget .oac-mobile__action:focus-visible { background: ${v('elev')}; }
.oac-widget .oac-mobile__action[aria-pressed="true"] { color: ${v('acc-2')}; background: ${v('on-bg')}; }
.oac-widget .oac-mobile__action[aria-disabled="true"] { color: ${v('faint')}; cursor: default; background: transparent; }
.oac-widget .oac-mobile__branding { display: flex; align-items: center; width: 100%; min-height: 44px; text-decoration: none; }
.oac-widget .oac-mobile-sheet.oac-dialog { left: 0; right: 0; top: auto; bottom: 0; transform: none; width: 100%;
  max-width: 100%; max-height: calc(100% - env(safe-area-inset-top) - 12px); border-radius: 14px 14px 0 0;
  padding-bottom: env(safe-area-inset-bottom); }
.oac-widget .oac-mobile-sheet__head { flex: none; display: flex; align-items: center; gap: 8px;
  min-height: 52px; padding: 4px 8px 4px 14px; border-bottom: 1px solid ${v('bd-soft')}; }
.oac-widget .oac-mobile-sheet__title { flex: 1 1 auto; color: ${v('tx-strong')}; font-size: 14px; }
.oac-widget .oac-mobile-sheet__body { flex: 1 1 auto; min-height: 0; overflow: auto; overscroll-behavior: contain;
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-content: start; padding: 8px; }
.oac-widget .oac-mobile-sheet__body > .oac-head { grid-column: 1 / -1; }
.oac-widget .oac-mobile-sheet__controls { grid-column: 1 / -1; display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)); border-bottom: 1px solid ${v('bd-soft')}; margin-bottom: 6px; }
.oac-widget .oac-mobile-sheet__body small { display: block; color: ${v('faint')}; }
/* A sheet row with a glyph (a chart type): the glyph sits on the middle of its label, not the baseline. */
.oac-widget .oac-mobile-sheet .oac-mobile__action > .oac-glyph { vertical-align: middle; margin: -2px 8px 0 0; }
.oac-widget .oac-mobile-results { width: min(360px, calc(100% - 16px)); max-height: min(50%, 360px); overflow: hidden;
  display: flex; flex-direction: column; background: ${v('panel')}; border: 1px solid ${v('bd')}; border-radius: 10px; box-shadow: ${v('shadow')}; }
.oac-widget .oac-mobile-results__head { flex: none; display: flex; align-items: center; gap: 8px; min-height: 44px;
  padding-left: 12px; border-bottom: 1px solid ${v('bd-soft')}; }
.oac-widget .oac-mobile-results__head > strong { flex: 1 1 auto; color: ${v('tx-strong')}; }
.oac-widget .oac-mobile-results__list { flex: 1 1 auto; min-height: 0; max-height: min(42vh, 300px);
  overflow-y: auto; overscroll-behavior: contain; }
.oac-widget .oac-mobile-results__list > .oac-mobile__action { display: block; width: 100%; text-align: left; }
.oac-widget .oac-mobile-results__list small { display: block; color: ${v('faint')}; }
.oac-widget .oac-mobile-results__status { min-height: 44px; padding: 13px 12px; color: ${v('mut')}; }
.oac-widget.is-mobile .oac-toasts { bottom: calc(54px + env(safe-area-inset-bottom)); }

/* Toasts */
.oac-widget .oac-toasts { position: absolute; right: 12px; bottom: calc(${v('status-h')} + 10px); z-index: 90; display: flex;
  flex-direction: column; gap: 8px; width: min(340px, calc(100% - 24px)); pointer-events: none; }
.oac-widget .oac-toast { display: flex; align-items: flex-start; gap: 8px; padding: 8px 6px 8px 12px; border-radius: 8px;
  background: ${v('panel')}; color: ${v('tx')}; border: 1px solid ${v('bd')}; border-left: 3px solid ${v('acc')};
  box-shadow: ${v('shadow')}; font-size: 12.5px; line-height: 1.45; pointer-events: auto; animation: oac-toast-in .16s ease-out; }
.oac-widget .oac-toast--success { border-left-color: ${v('buy')}; }
.oac-widget .oac-toast--error { border-left-color: ${v('sell')}; }
.oac-widget .oac-toast__msg { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; padding-top: 2px; }
.oac-widget .oac-toast__x { flex: none; width: 26px; height: 26px; border: 0; border-radius: 6px; background: transparent;
  color: ${v('faint')}; padding: 0; display: grid; place-items: center; }
.oac-widget .oac-toast__x:hover { background: ${v('elev-2')}; color: ${v('tx')}; }
.oac-widget .oac-toast__x > svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.5; }
.oac-widget .oac-toast.is-out { opacity: 0; transform: translateY(6px); transition: opacity .16s, transform .16s; }
@keyframes oac-toast-in { from { opacity: 0; transform: translateY(6px); } }

/* Overlay layer: popovers anchored to a control, dialogs centred over a scrim. */
.oac-widget .oac-layer { container: oac-widget / inline-size; position: absolute; inset: 0; z-index: 60; pointer-events: none; }
/* Not the tooltip: it shows over controls (the rail's tab, the bar's buttons) and
   must never take the press meant for them. */
.oac-widget .oac-layer > :not(.oac-tip, .oac-tip-spot) { pointer-events: auto; }
.oac-widget .oac-scrim { position: absolute; inset: 0; background: ${v('scrim')}; }
.oac-widget .oac-pop { position: absolute; left: 0; top: 0; }
.oac-widget .oac-dialog { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  min-width: 0; max-width: calc(100% - 24px); max-height: calc(100% - 24px); display: flex; flex-direction: column;
  background: ${v('panel')}; border: 1px solid ${v('bd')}; border-radius: 12px; box-shadow: ${v('shadow')}; outline: none; }
.oac-widget .oac-dialog__head { flex: none; min-width: 0; display: flex; align-items: center; gap: 8px; padding: 12px 14px 8px; }
.oac-widget .oac-dialog__title { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; font-size: 14px; font-weight: 700; color: ${v('tx-strong')}; }
.oac-widget .oac-dialog__body { flex: 1 1 auto; min-height: 0; min-width: 0; overflow: auto; overscroll-behavior: contain; padding: 4px 14px 10px; }
.oac-widget .oac-dialog__foot { flex: none; min-width: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 14px 12px;
  border-top: 1px solid ${v('bd-soft')}; }
.oac-widget .oac-dialog__foot > .oac-spacer { flex: 1 1 auto; }
.oac-widget .oac-csv { width: 490px; }
.oac-widget .oac-csv__ranges, .oac-widget .oac-csv .oac-dialog__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.oac-widget .oac-csv__hint { color: ${v('mut')}; line-height: 1.5; }
.oac-widget .oac-csv__error { color: ${v('danger')}; overflow-wrap: anywhere; }
.oac-widget .oac-csv__error:empty { display: none; }

/* Point and figure and Renko settings: a size, its unit and its method share one control column. */
.oac-widget .oac-ctset { width: 380px; }
.oac-widget .oac-ctset .oac-row__ctl { width: min(244px, 66%); }
.oac-widget .oac-ctset__presets { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; width: 100%; padding: 2px 0; }
.oac-widget .oac-ctset__preset { height: 24px; padding: 0 4px; font-size: 11px; font-variant-numeric: tabular-nums;
  background: ${v('elev')}; border-color: ${v('bd-soft')}; }
.oac-widget .oac-ctset__size { display: flex; align-items: center; gap: 6px; width: 100%; min-width: 0; }
.oac-widget .oac-ctset .oac-row__ctl .oac-ctset__size > input { flex: 1 1 0; width: auto; min-width: 0; }
.oac-widget .oac-ctset .oac-input--num { text-align: right; font-variant-numeric: tabular-nums; }
.oac-widget .oac-ctset .oac-row__ctl .oac-ctset__size > .oac-select { flex: 0 0 100px; width: 100px; }
.oac-widget .oac-ctset__unit { flex: none; color: ${v('mut')}; font-size: 11px; white-space: nowrap; }
.oac-widget .oac-ctset__radios { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px 14px; }
.oac-widget .oac-ctset__radio { display: inline-flex; align-items: center; gap: 6px; color: ${v('tx')}; white-space: nowrap; cursor: pointer; }

/* Shortcuts panel */
.oac-widget .oac-keys { columns: 2; column-gap: 24px; min-width: 520px; }
.oac-widget .oac-keys__group { break-inside: avoid; margin-bottom: 8px; }
.oac-widget .oac-keys__row { display: flex; align-items: center; gap: 10px; padding: 3px 0; }
.oac-widget .oac-keys__row > span { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.oac-widget .oac-keys__row > kbd { flex: none; padding: 2px 6px; border-radius: 4px; background: ${v('elev')};
  border: 1px solid ${v('bd-soft')}; color: ${v('mut')}; }
.oac-widget .oac-keys__row.is-shadowed > span, .oac-widget .oac-keys__row.is-shadowed > kbd { color: ${v('faint')}; text-decoration: line-through; }
.oac-widget .oac-keys__note { color: ${v('faint')}; font-size: 11px; padding: 4px 0 0; }

@container oac-widget (max-width: 720px) {
  .oac-widget .oac-keys { columns: 1; min-width: 0; }
}
@media (max-width: 720px) {
  .oac-widget .oac-sym > input { width: 104px; }
}
@media (prefers-reduced-motion: reduce) {
  .oac-widget .oac-rail__btn, .oac-widget .oac-rail__chev, .oac-widget .oac-tip, .oac-widget .oac-fly__star,
  .oac-widget .oac-btn, .oac-widget .oac-toast.is-out { transition: none; }
  .oac-widget .oac-toast { animation: none; }
  .oac-widget .oac-mobile__action { transition: none; }
}
`;

/**
 * Put the stylesheet into `doc` once. Safe to call per widget: the second
 * call leaves a populated sheet untouched. An empty server-rendered sheet
 * is filled in place, preserving its nonce. `extra` is appended to the
 * shell's rules when filling the sheet; the dialog modules hand theirs in
 * here, so the page still carries one sheet. `nonce` authorizes the style
 * element under CSP; the host controls its style-attribute policy separately.
 */
export function injectWidgetStyles(doc: Document, extra = '', nonce?: string): HTMLStyleElement {
  const existing = doc.getElementById(WIDGET_STYLE_ID) as HTMLStyleElement | null;
  if (existing?.textContent?.trim()) return existing;
  const style = existing ?? doc.createElement('style');
  style.id = WIDGET_STYLE_ID;
  // CSP checks connected sheets when their text changes. Read the IDL
  // property because browsers hide a connected element's nonce attribute.
  if (!style.nonce && nonce !== undefined) style.nonce = nonce;
  style.textContent = WIDGET_CSS + extra;
  if (existing === null) (doc.head ?? doc.body ?? doc.documentElement).appendChild(style);
  return style;
}

/**
 * Add the rules of a part that loads on first use (lazy.ts) to the sheet,
 * once per document. Appended to the widget's own sheet they keep its CSP
 * nonce, and they come after every rule they refine, as they did when the
 * part was bundled in. A page with no sheet gets none here, as before.
 */
export function addWidgetStyles(doc: Document, css: string): void {
  const style = doc.getElementById(WIDGET_STYLE_ID);
  if (style !== null && !(style.textContent ?? '').includes(css)) style.appendChild(doc.createTextNode(css));
}
