import { esc } from './ui.js';

// ── shared hover label ─────────────────────────────────────────────────
// A `title` waits about a second, cannot be styled, and cannot carry a
// second line, which is no use on a rail of near-identical glyphs or on a
// toolbar of bare icons. One tip element serves every control: it is
// refilled and repositioned per target rather than built per button, so a
// toolbar that rebuilds itself on every state change leaks nothing.
const tipSpecs = new WeakMap();
let tipNode = null;
let tipFor = null;

/**
 * Give `target` a hover label. `spec` is `{ title, sub, chord, side }` or a
 * function returning one: a button whose meaning changes with state (the
 * rail's last-picked tool, the transport's play/pause) has to be read at
 * hover time, not frozen when the button was built.
 *
 * Any `title` already on the element moves to `aria-label` and is dropped,
 * or the browser draws its own box over this one a second later.
 */
export function attachTip(target, spec) {
  tipSpecs.set(target, spec);
  const label = (typeof spec === 'function' ? spec() : spec).title;
  if (label && !target.getAttribute('aria-label')) target.setAttribute('aria-label', label);
  target.removeAttribute('title');
  target.addEventListener('pointerenter', () => showTip(target));
  target.addEventListener('pointerleave', hideTip);
  // A press means the user has decided; the label has done its job and a
  // tip left over a menu that just opened reads as part of the menu.
  target.addEventListener('pointerdown', hideTip);
  target.addEventListener('focus', () => showTip(target));
  target.addEventListener('blur', hideTip);
  return target;
}

let canvasSpot = null;

/**
 * A label for a control painted on a canvas (canvas-tips.js), which has no
 * element to hover: a one-pixel spot at the pointer stands in for it.
 */
export function showCanvasTip(title, point) {
  if (!canvasSpot) {
    canvasSpot = document.createElement('span');
    canvasSpot.className = 'tip-spot';
    canvasSpot.setAttribute('aria-hidden', 'true');
  }
  if (!canvasSpot.isConnected) document.body.appendChild(canvasSpot);
  canvasSpot.style.left = point.x + 'px';
  canvasSpot.style.top = point.y + 'px';
  tipSpecs.set(canvasSpot, { title, side: 'bottom' });
  showTip(canvasSpot);
}

export function hideCanvasTip() {
  if (canvasSpot && tipFor === canvasSpot) hideTip();
}

export function hideTip() {
  if (!tipNode) return;
  tipNode.classList.remove('is-on');
  tipFor = null;
}

export function showTip(target) {
  const raw = tipSpecs.get(target);
  if (!raw) return;
  const spec = typeof raw === 'function' ? raw() : raw;
  if (!spec || !spec.title) { hideTip(); return; }
  // A label read at hover time is also the accessible name, so refresh it:
  // the transport's play button is Play or Pause depending on the moment.
  if (typeof raw === 'function') target.setAttribute('aria-label', spec.title);
  if (!tipNode) {
    tipNode = document.createElement('div');
    tipNode.id = 'tip';
    tipNode.setAttribute('role', 'presentation');
  }
  // Chart full screen puts the stage in the top layer, where nothing
  // outside its subtree is painted: a tip left on <body> would simply not
  // appear over the rail, which is the one place full screen still has one.
  const host = document.fullscreenElement || document.body;
  if (tipNode.parentNode !== host) host.appendChild(tipNode);
  tipFor = target;
  tipNode.innerHTML = esc(spec.title)
    + (spec.chord ? '<span class="tip-chord">' + esc(spec.chord) + '</span>' : '')
    + (spec.sub ? '<span class="tip-sub">' + esc(spec.sub) + '</span>' : '');
  placeTip(target, spec.side || 'bottom');
  tipNode.classList.add('is-on');
}

/**
 * Anchor beside the control, then flip to the opposite side rather than
 * open off the edge of the window. The rail sits against the left edge and
 * the toolbar against the top, so both flips are reachable in normal use.
 */
function placeTip(target, side) {
  const r = target.getBoundingClientRect();
  const w = tipNode.offsetWidth;
  const h = tipNode.offsetHeight;
  const pad = 6;
  const gap = 8;
  let x, y;
  if (side === 'right' || side === 'left') {
    const wantRight = side === 'right';
    x = wantRight ? r.right + gap : r.left - gap - w;
    if (wantRight ? x + w > window.innerWidth - pad : x < pad) {
      x = wantRight ? r.left - gap - w : r.right + gap;
    }
    y = r.top + r.height / 2 - h / 2;
  } else {
    const wantBelow = side !== 'top';
    y = wantBelow ? r.bottom + gap : r.top - gap - h;
    if (wantBelow ? y + h > window.innerHeight - pad : y < pad) {
      y = wantBelow ? r.top - gap - h : r.bottom + gap;
    }
    x = r.left + r.width / 2 - w / 2;
  }
  tipNode.style.left = Math.max(pad, Math.min(x, window.innerWidth - w - pad)) + 'px';
  tipNode.style.top = Math.max(pad, Math.min(y, window.innerHeight - h - pad)) + 'px';
}

export function initHover() {
  // Toolbars here rebuild wholesale, so the element a tip is describing can be
  // torn out from under it. Anything that moves the page takes the tip down.
  window.addEventListener('scroll', hideTip, true);
  window.addEventListener('blur', hideTip);
  window.addEventListener('resize', hideTip);
  document.addEventListener('pointermove', (e) => {
    // A canvas control's label goes with the chart's hover id, not the pointer's target.
    if (!tipFor || tipFor === canvasSpot) return;
    // `pointerleave` never fires for a button that was removed while hovered,
    // which is exactly what a toolbar rebuild does.
    if (!tipFor.isConnected || !(tipFor === e.target || tipFor.contains(e.target))) hideTip();
  }, true);
}
