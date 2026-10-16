import { el } from './ui.js';
import { ticon } from './toolbar.js';
import { capturePaneTarget } from './pane-target.js';
import { openChartDataControls } from './chart-data-controls.js';

let app;
let menuTarget = null;

/* ── chart snapshot ──────────────────────────────────────────────────
 * `chart.takeScreenshot()` returns a canvas with everything on it, the
 * watermark and the replay mark included, because they are drawn on the
 * chart rather than laid over it in HTML.
 */

/** A PNG blob of the chart as it stands. */
export function snapshotBlob(target = capturePaneTarget(app)) {
  return new Promise((resolve, reject) => {
    if (!target?.chart.takeScreenshot) { reject(new Error('no screenshot in this build')); return; }
    if (!target.current()) { reject(new Error('chart changed; open the snapshot menu again')); return; }
    const canvas = target.chart.takeScreenshot();
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('canvas produced no image'))), 'image/png');
  });
}

export function snapshotName(target = capturePaneTarget(app)) {
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
  return `${(target?.request.symbol || 'chart').replace(/[^A-Za-z0-9._-]/g, '')}-${target?.request.interval || ''}-${stamp}.png`;
}

export async function downloadSnapshot(target = menuTarget ?? capturePaneTarget(app)) {
  closeSnapMenu();
  try {
    const blob = await snapshotBlob(target);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = snapshotName(target);
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Revoked on the next turn: revoking synchronously races the download in
    // some browsers, which then saves an empty file.
    setTimeout(() => URL.revokeObjectURL(url), 0);
    el('status').textContent = 'saved ' + a.download;
  } catch (err) {
    el('status').textContent = 'snapshot failed: ' + err.message;
  }
}

export async function copySnapshot(target = menuTarget ?? capturePaneTarget(app)) {
  closeSnapMenu();
  try {
    const blob = await snapshotBlob(target);
    // The clipboard image API is the only one that pastes into a post
    // composer. It needs a secure context and a user gesture, both of which
    // a click on this menu item supplies.
    if (!navigator.clipboard || typeof ClipboardItem === 'undefined') {
      throw new Error('clipboard images need https or localhost');
    }
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    el('status').textContent = 'chart copied, paste it anywhere';
  } catch (err) {
    el('status').textContent = 'copy failed: ' + err.message;
  }
}

export function openSnapMenu(anchor) {
  menuTarget = capturePaneTarget(app);
  let menu = el('snapmenu');
  if (!menu) {
    menu = document.createElement('div');
    menu.id = 'snapmenu';
    menu.innerHTML =
      '<div class="head">Chart snapshot</div>'
      + '<button id="snap-save">' + ticon('download') + '<span>Save PNG</span>'
      + '<span class="key">Ctrl+Alt+S</span></button>'
      + '<button id="snap-copy">' + ticon('copy') + '<span>Copy image</span>'
      + '<span class="key">Ctrl+Shift+S</span></button>'
      + '<button id="snap-data">' + ticon('download') + '<span>Download chart data (CSV)</span></button>';
    document.body.appendChild(menu);
    el('snap-save').addEventListener('click', () => downloadSnapshot());
    el('snap-copy').addEventListener('click', () => copySnapshot());
    el('snap-data').addEventListener('click', () => { const target = menuTarget; closeSnapMenu(); openChartDataControls(app, target); });
  }
  const r = anchor.getBoundingClientRect();
  menu.hidden = false;
  // Placed after unhiding so the measured width is the real one, and pulled
  // back inside the window rather than opening off the right edge.
  const w = menu.offsetWidth;
  menu.style.top = (r.bottom + 6) + 'px';
  menu.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left)) + 'px';
}

export function closeSnapMenu() {
  menuTarget = null;
  const menu = el('snapmenu');
  if (menu) menu.hidden = true;
}

export function initSnapshot(a) {
  app = a;
  menuTarget = null;
  document.addEventListener('click', (e) => {
    const menu = el('snapmenu');
    if (menu && !menu.hidden && !menu.contains(e.target)) closeSnapMenu();
  });
  document.addEventListener('keydown', (e) => {
    // The physical key: Ctrl+Option+S types no 's' on macOS.
    if (!e.ctrlKey || e.code !== 'KeyS') return;
    if (e.altKey) { e.preventDefault(); downloadSnapshot(capturePaneTarget(app)); }
    else if (e.shiftKey) { e.preventDefault(); copySnapshot(capturePaneTarget(app)); }
  });
}
