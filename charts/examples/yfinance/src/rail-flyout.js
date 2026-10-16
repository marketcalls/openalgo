// The rail's floating pieces: the group flyout, the small context menu and
// the dwell tooltip, plus the placement maths they share. Everything here is
// host chrome built from the tier's shipped glyphs; nothing reaches the
// controller directly, the rail hands in callbacks.
import { iconUse, chromeIconSvg, DRAWING_TOOL_ICONS, ICON_SIZE, ICON_STROKE } from '/dist/openalgo-charts.draw.mjs';
import { esc } from './ui.js';

/** How long the pointer rests on a control before its label appears. */
export const TIP_DWELL_MS = 600;

/** Chart-only full screen puts the stage in the top layer, where nothing outside its subtree paints. */
export const layerHost = () => document.fullscreenElement || document.body;

/**
 * A tool's glyph as a `<use>` into the sprite the rail injected. A tool the
 * tier has no glyph for (a host-registered one) gets its initial instead of
 * a throw, so one custom tool cannot blank the rail.
 */
export function toolGlyph(id, opts) {
  if (DRAWING_TOOL_ICONS[id]) return iconUse(id, opts);
  return '<span class="glyph--text" aria-hidden="true">' + esc(String(id).charAt(0).toUpperCase()) + '</span>';
}

/** A chrome glyph on the 16 grid, inline. */
export const chromeGlyph = (id, opts) => chromeIconSvg(id, opts);

/**
 * Where a panel of `size` goes beside `anchor` without leaving the viewport:
 * to the right of it by `gap`, its top on the anchor's top, then pulled up
 * (never past `pad`) when it would run off the bottom, and flipped to the
 * left only when the right has no room at all.
 */
export function placeBeside(anchor, size, viewport, gap = 6, pad = 8) {
  let left = anchor.right + gap;
  let side = 'right';
  if (left + size.width > viewport.width - pad && anchor.left - gap - size.width >= pad) {
    left = anchor.left - gap - size.width;
    side = 'left';
  }
  left = Math.max(pad, Math.min(left, viewport.width - size.width - pad));
  const top = Math.max(pad, Math.min(anchor.top, viewport.height - size.height - pad));
  return { left, top, side };
}

/** A tip centred on the anchor's edge, flipped across it when its side has no room. */
export function placeTip(anchor, size, viewport, side = 'right', gap = 8, pad = 6) {
  let x;
  let y;
  if (side === 'right' || side === 'left') {
    const wantRight = side === 'right';
    x = wantRight ? anchor.right + gap : anchor.left - gap - size.width;
    if (wantRight ? x + size.width > viewport.width - pad : x < pad) {
      x = wantRight ? anchor.left - gap - size.width : anchor.right + gap;
    }
    y = anchor.top + anchor.height / 2 - size.height / 2;
  } else {
    const wantBelow = side !== 'top';
    y = wantBelow ? anchor.bottom + gap : anchor.top - gap - size.height;
    if (wantBelow ? y + size.height > viewport.height - pad : y < pad) {
      y = wantBelow ? anchor.top - gap - size.height : anchor.bottom + gap;
    }
    x = anchor.left + anchor.width / 2 - size.width / 2;
  }
  return {
    left: Math.max(pad, Math.min(x, viewport.width - size.width - pad)),
    top: Math.max(pad, Math.min(y, viewport.height - size.height - pad)),
  };
}

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });

/**
 * A button's box widened to the right edge of the rail it sits in, so a
 * panel opens clear of the rail rather than flush with the button inside
 * it. `edge` names the rail; it defaults to the nearest one.
 */
function anchorBox(anchor, edge) {
  const r = anchor.getBoundingClientRect();
  const rail = edge || (anchor.closest ? anchor.closest('.rail') : null);
  if (!rail) return r;
  const right = Math.max(r.right, rail.getBoundingClientRect().right);
  return { left: r.left, top: r.top, right, bottom: r.bottom, width: right - r.left, height: r.height };
}

// ── dwell tooltip ──────────────────────────────────────────────────────
// One node for every rail control, shown after the pointer has rested on a
// button for a moment. The demo's shared tip appears on entry, which suits
// a toolbar of a dozen buttons; a rail the pointer crosses on its way to the
// chart would flash a label at every row it passed. The specs are read at
// show time, because a group button stands for whichever tool was last
// picked from it and a control's label follows its state.
const tipSpecs = new WeakMap();
let tipNode = null;
let tipTimer = 0;
let tipFor = null;

export function attachRailTip(target, spec) {
  tipSpecs.set(target, spec);
  const first = typeof spec === 'function' ? spec() : spec;
  if (first && first.title && !target.getAttribute('aria-label')) target.setAttribute('aria-label', first.title);
  const arm = () => {
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => showRailTip(target), TIP_DWELL_MS);
  };
  target.addEventListener('pointerenter', arm);
  target.addEventListener('focus', arm);
  target.addEventListener('pointerleave', hideRailTip);
  target.addEventListener('blur', hideRailTip);
  // A press means the user has decided; a label left over a flyout that just
  // opened reads as part of the flyout.
  target.addEventListener('pointerdown', hideRailTip);
  target.addEventListener('keydown', hideRailTip);
  return target;
}

/** Re-read a control's spec into its accessible name, for a label that follows state. */
export function refreshTipLabel(target) {
  const raw = tipSpecs.get(target);
  if (typeof raw !== 'function') return;
  const spec = raw();
  if (spec && spec.title) target.setAttribute('aria-label', spec.title);
}

export function hideRailTip() {
  clearTimeout(tipTimer);
  tipTimer = 0;
  tipFor = null;
  if (tipNode) tipNode.classList.remove('is-on');
}

export function showRailTip(target) {
  const raw = tipSpecs.get(target);
  if (!raw || !target.isConnected) return;
  const spec = typeof raw === 'function' ? raw() : raw;
  if (!spec || !spec.title) { hideRailTip(); return; }
  if (typeof raw === 'function') target.setAttribute('aria-label', spec.title);
  if (!tipNode) {
    tipNode = document.createElement('div');
    tipNode.className = 'rail-tip';
    tipNode.setAttribute('role', 'presentation');
  }
  const host = layerHost();
  if (tipNode.parentNode !== host) host.appendChild(tipNode);
  tipFor = target;
  tipNode.innerHTML = esc(spec.title)
    + (spec.chord ? '<kbd class="rail-tip__chord">' + esc(spec.chord) + '</kbd>' : '')
    + (spec.sub ? '<span class="rail-tip__sub">' + esc(spec.sub) + '</span>' : '');
  const at = placeTip(target.getBoundingClientRect(), { width: tipNode.offsetWidth, height: tipNode.offsetHeight },
    viewport(), spec.side || 'right');
  tipNode.style.left = at.left + 'px';
  tipNode.style.top = at.top + 'px';
  tipNode.classList.add('is-on');
}

/** The control the tip is up for, or null. Tests read it; nothing else should. */
export const railTipTarget = () => tipFor;

// ── group flyout ───────────────────────────────────────────────────────
let fly = null;      // { el, anchor, close }

export const flyoutOpen = () => fly !== null;
export const flyoutEl = () => (fly ? fly.el : null);

export function closeFlyout() {
  if (!fly) return;
  const f = fly;
  fly = null;
  f.el.remove();
  document.removeEventListener('pointerdown', f.onOutside, true);
  f.anchor.setAttribute('aria-expanded', 'false');
  if (f.onClose) f.onClose();
}

/**
 * The list of a group's tools beside its rail button. Each row carries the
 * tool's glyph, its name, a pin star and its chord at the right edge.
 *
 * `opts`: `{ anchor, group, armed, nameOf, chordOf, isPinned, onPick, onPin,
 * onClose, viaKeyboard }`. `group.items` is a list of `{ head }` and
 * `{ tool }` entries in display order.
 */
export function openFlyout(opts) {
  closeFlyout();
  hideRailTip();
  const { anchor, group } = opts;
  const m = document.createElement('div');
  m.className = 'fly';
  m.setAttribute('role', 'menu');
  m.setAttribute('aria-label', group.title);
  m.tabIndex = -1;
  for (const it of group.items) {
    if (it.head) {
      const h = document.createElement('div');
      h.className = 'fly__head';
      h.textContent = it.head;
      m.appendChild(h);
      continue;
    }
    const pinned = opts.isPinned(it.tool);
    const chord = opts.chordOf(it.tool);
    const row = document.createElement('div');
    row.className = 'fly__row';
    row.setAttribute('role', 'menuitemradio');
    row.setAttribute('aria-checked', String(opts.armed === it.tool));
    row.tabIndex = -1;
    row.dataset.tool = it.tool;
    row.innerHTML =
      '<span class="fly__glyph">' + toolGlyph(it.tool) + '</span>' +
      '<span class="fly__name">' + esc(opts.nameOf(it.tool)) + '</span>' +
      '<button type="button" class="fly__star" tabindex="-1" aria-pressed="' + pinned + '"' +
        ' aria-label="Pin to rail">' +
        chromeGlyph(pinned ? 'star-filled' : 'star') + '</button>' +
      '<kbd class="fly__chord">' + (chord ? esc(chord) : '') + '</kbd>';
    row.addEventListener('click', (e) => {
      const star = e.target.closest ? e.target.closest('.fly__star') : null;
      e.stopPropagation();
      if (star) { togglePin(row, it.tool); return; }
      closeFlyout();
      opts.onPick(it.tool);
    });
    m.appendChild(row);
  }

  const togglePin = (row, tool) => {
    const on = !opts.isPinned(tool);
    opts.onPin(tool, on);
    const star = row.querySelector('.fly__star');
    // One name; the pressed state says pinned.
    star.setAttribute('aria-pressed', String(on));
    star.innerHTML = chromeGlyph(on ? 'star-filled' : 'star');
  };

  // Arrows walk the rows, Enter arms, ArrowRight reaches the row's star and
  // ArrowLeft comes back, Escape returns to the button that opened it.
  m.addEventListener('keydown', (e) => {
    const rows = Array.from(m.querySelectorAll('.fly__row'));
    const cur = e.target.closest ? e.target.closest('.fly__row') : null;
    const at = rows.indexOf(cur);
    const go = (i) => { rows[(i + rows.length) % rows.length].focus(); };
    let handled = true;
    switch (e.key) {
      case 'ArrowDown': go(at + 1); break;
      case 'ArrowUp': go(at - 1); break;
      case 'Home': go(0); break;
      case 'End': go(rows.length - 1); break;
      case 'ArrowRight': if (cur) cur.querySelector('.fly__star').focus(); break;
      case 'ArrowLeft': if (cur) cur.focus(); break;
      case 'Enter':
      case ' ':
        if (!cur) { handled = false; break; }
        if (e.target.closest('.fly__star')) togglePin(cur, cur.dataset.tool);
        else { closeFlyout(); opts.onPick(cur.dataset.tool); anchor.focus(); }
        break;
      case 'Escape': closeFlyout(); anchor.focus(); break;
      default: handled = false;
    }
    if (handled) { e.preventDefault(); e.stopPropagation(); }
  });

  const onOutside = (e) => {
    if (m.contains(e.target) || anchor.contains(e.target)) return;
    closeFlyout();
  };
  document.addEventListener('pointerdown', onOutside, true);
  layerHost().appendChild(m);
  const at = placeBeside(anchorBox(anchor, opts.edge), { width: m.offsetWidth, height: m.offsetHeight }, viewport());
  m.style.left = at.left + 'px';
  m.style.top = at.top + 'px';
  anchor.setAttribute('aria-expanded', 'true');
  fly = { el: m, anchor, onOutside, onClose: opts.onClose };
  if (opts.viaKeyboard) {
    const first = m.querySelector('.fly__row[aria-checked="true"]') || m.querySelector('.fly__row');
    if (first) first.focus();
  } else {
    m.focus();
  }
  return m;
}

// ── small context menu ─────────────────────────────────────────────────
// Right-click on a rail button: pin or unpin, remove everything. Rows are
// `{ label, icon, tool, onSelect, danger, disabled }`; `tool` draws a tool
// glyph through the sprite, `icon` a chrome glyph. A disabled row stays in
// the list with its count, so the menu still says what it would do.
let menu = null;

export function closeRailMenu() {
  if (!menu) return;
  const m = menu;
  menu = null;
  m.el.remove();
  document.removeEventListener('pointerdown', m.onOutside, true);
}

export function openRailMenu(anchor, rows, at) {
  closeRailMenu();
  hideRailTip();
  const m = document.createElement('div');
  m.className = 'rail-menu';
  m.setAttribute('role', 'menu');
  for (const r of rows) {
    const b = document.createElement('button');
    b.type = 'button';
    b.setAttribute('role', 'menuitem');
    b.className = (r.danger ? 'danger' : '') + (r.disabled ? ' is-off' : '');
    b.setAttribute('aria-disabled', String(r.disabled === true));
    b.innerHTML = (r.tool ? toolGlyph(r.tool) : r.icon ? chromeGlyph(r.icon) : '<span class="rail-menu__gap"></span>')
      + '<span>' + esc(r.label) + '</span>';
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      if (r.disabled) return;
      closeRailMenu();
      r.onSelect();
    });
    m.appendChild(b);
  }
  m.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeRailMenu(); anchor.focus(); e.preventDefault(); e.stopPropagation(); }
  });
  const onOutside = (e) => { if (!m.contains(e.target)) closeRailMenu(); };
  document.addEventListener('pointerdown', onOutside, true);
  layerHost().appendChild(m);
  const box = at
    ? { left: at.x, right: at.x, top: at.y, bottom: at.y, width: 0, height: 0 }
    : anchorBox(anchor);
  const pos = placeBeside(box, { width: m.offsetWidth, height: m.offsetHeight }, viewport());
  m.style.left = pos.left + 'px';
  m.style.top = pos.top + 'px';
  menu = { el: m, onOutside };
  const first = m.querySelector('button');
  if (first) first.focus();
  return m;
}

export const railMenuOpen = () => menu !== null;

// ── stylesheet ─────────────────────────────────────────────────────────
// Injected by the rail with its own rules, once. Glyphs sit in a 24px slot
// at the grid's native size so a 2-unit stroke is two device pixels, and
// every hover and pressed tint is a class, so no pointer path touches
// inline style.
export const RAIL_FLYOUT_CSS = `
.rail-tip { position: fixed; z-index: 200; left: 0; top: 0; max-width: 260px; pointer-events: none;
  padding: 5px 9px; border-radius: 6px; background: var(--elev-2); color: var(--tx);
  border: 1px solid var(--bd); box-shadow: 0 6px 20px rgba(0,0,0,.45);
  font: 12px/1.4 system-ui, sans-serif; opacity: 0; transition: opacity .09s ease; }
.rail-tip.is-on { opacity: 1; }
.rail-tip__chord { margin-left: 10px; color: var(--mut); font: 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
  font-variant-numeric: tabular-nums; }
.rail-tip__sub { display: block; margin-top: 2px; color: var(--faint); font-size: 11px; }

.fly { position: fixed; z-index: 60; min-width: 244px; max-width: 320px; max-height: calc(100vh - 16px);
  overflow-y: auto; padding: 6px; background: var(--panel); border: 1px solid var(--bd);
  border-radius: 10px; box-shadow: 0 14px 40px rgba(0,0,0,.55); outline: none; }
.fly__head { padding: 8px 10px 4px; color: var(--faint); font-size: 10px; text-transform: uppercase;
  letter-spacing: .7px; }
.fly__row { display: flex; align-items: center; gap: 8px; padding: 4px 6px 4px 8px; border-radius: 7px;
  color: var(--tx); font-size: 13px; cursor: pointer; outline: none; user-select: none; }
.fly__row:hover, .fly__row:focus-visible { background: var(--elev-2); }
.fly__row[aria-checked="true"] { background: var(--on-bg); color: var(--acc-2); }
.fly__glyph { width: ${ICON_SIZE}px; height: ${ICON_SIZE}px; display: grid; place-items: center; flex: none; }
.fly__glyph > svg { width: ${ICON_SIZE}px; height: ${ICON_SIZE}px; fill: none; stroke: currentColor; stroke-width: ${ICON_STROKE};
  stroke-linecap: round; stroke-linejoin: round; }
.fly__name { flex: 1 1 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fly__chord { min-width: 40px; text-align: right; color: var(--faint);
  font: 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace; font-variant-numeric: tabular-nums; }
.fly__star { width: 22px; height: 22px; display: grid; place-items: center; padding: 0; border: 0;
  border-radius: 5px; background: transparent; color: var(--faint); cursor: pointer; opacity: 0;
  transition: opacity .1s, color .1s; }
.fly__row:hover .fly__star, .fly__row:focus-within .fly__star, .fly__star[aria-pressed="true"] { opacity: 1; }
.fly__star:hover { background: var(--elev); color: var(--tx); }
.fly__star:focus-visible { outline: 2px solid var(--acc-2); outline-offset: -1px; opacity: 1; }
.fly__star[aria-pressed="true"] { color: var(--amber); }
.fly__star > svg { width: 14px; height: 14px; stroke: currentColor; stroke-width: 1.5;
  stroke-linecap: round; stroke-linejoin: round; }
.fly__star[aria-pressed="false"] > svg { fill: none; }

.rail-menu { position: fixed; z-index: 61; min-width: 190px; padding: 5px; background: var(--panel);
  border: 1px solid var(--bd); border-radius: 9px; box-shadow: 0 12px 34px rgba(0,0,0,.5); }
.rail-menu button { display: flex; align-items: center; gap: 9px; width: 100%; padding: 6px 8px;
  background: transparent; border: 0; border-radius: 6px; color: var(--tx); font: inherit;
  font-size: 12.5px; text-align: left; cursor: pointer; }
.rail-menu button:hover, .rail-menu button:focus-visible { background: var(--elev-2); outline: none; }
.rail-menu button.danger:hover { color: var(--danger-tx); }
.rail-menu button.is-off, .rail-menu button.is-off:hover { color: var(--faint); background: transparent; cursor: default; }
.rail-menu button > svg { width: 16px; height: 16px; flex: none; stroke: currentColor;
  stroke-linecap: round; stroke-linejoin: round; }
/* A tool glyph at 16px here, so its stroke is scaled to keep the tier's line. */
.rail-menu button > svg[viewBox="0 0 24 24"] { stroke-width: ${ICON_STROKE * ICON_SIZE / 16}; fill: none; }
.rail-menu__gap { width: 16px; flex: none; }
.glyph--text { display: inline-grid; place-items: center; width: ${ICON_SIZE}px; height: ${ICON_SIZE}px; font-size: 12px;
  font-weight: 600; }
@media (prefers-reduced-motion: reduce) { .rail-tip, .fly__star { transition: none; } }
`;
