/**
 * A capture says what happened. The chart's PNG download reports a picture
 * the browser could not be handed (a canvas tainted by a cross-origin image
 * refuses to be read) as an error, never as saved, and a clipboard copy that
 * throws is reported rather than thrown out of the menu. The chart's capture
 * menu and the chart grid's share one download and one copy (capture.ts).
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { createWidget, type Widget } from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';
import { makeGrid, walk } from './widget-grid-harness';

beforeAll(ensureWindowGlobal);

const live: Widget[] = [];
afterEach(() => {
  for (const w of live.splice(0)) w.destroy();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function make(doc: FakeDocument = fakeWidgetDocument()): { w: Widget; root: FakeElement; doc: FakeDocument; statuses: string[] } {
  const w = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
    document: doc as unknown as Document, pixelRatio: () => 1, raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
    symbol: 'INFY', exchange: 'NSE', interval: '5m',
  });
  w.chart.applySize(800, 600);
  w.series.setData(walk(60, 1500));
  live.push(w);
  const statuses: string[] = [];
  w.on('status', e => statuses.push(`${e.kind} ${e.text}`));
  return { w, root: w.root as unknown as FakeElement, doc, statuses };
}

/** Open the chart's capture menu and press the row labelled `label`. */
function press(root: FakeElement, label: string): void {
  root.querySelector('.oac-topbar .oac-btn[aria-label="Capture chart"]')!.click();
  const row = root.querySelectorAll('.oac-menu .oac-menu__row').find(r => r.querySelector('.oac-menu__label')?.textContent === label);
  if (row === undefined) throw new Error(`no ${label} row`);
  row.click();
}

/** The anchors a document makes, so a test can see what a download clicked. */
function anchors(doc: FakeDocument): FakeElement[] {
  const made: FakeElement[] = [];
  const create = doc.createElement.bind(doc);
  vi.spyOn(doc, 'createElement').mockImplementation(((tag: string) => {
    const el = create(tag);
    if (tag === 'a') made.push(el);
    return el;
  }) as typeof doc.createElement);
  return made;
}

const canvas = (parts: { toDataURL?: () => string; toBlob?: (done: (blob: Blob | null) => void) => void }): HTMLCanvasElement =>
  parts as unknown as HTMLCanvasElement;

/** A clipboard that takes images, with what it was given. */
function clipboard(write: (items: unknown[]) => Promise<void> = async () => {}): unknown[][] {
  const written: unknown[][] = [];
  vi.stubGlobal('ClipboardItem', class { public constructor(public readonly parts: Record<string, Blob>) {} });
  vi.stubGlobal('navigator', { clipboard: { write: (items: unknown[]) => { written.push(items); return write(items); } } });
  return written;
}

describe('the chart capture menu', () => {
  it('says a PNG the browser could not be handed failed, rather than saved', () => {
    const { w, root, statuses } = make();
    vi.spyOn(w.chart, 'takeScreenshot').mockReturnValue(canvas({ toDataURL: () => { throw new Error('The canvas has been tainted by cross-origin data'); } }));
    press(root, 'Download PNG');
    expect(statuses).toEqual(['error This runtime cannot save files']);
  });

  it('hands a PNG to the browser through an anchor in the document, and says it was saved', () => {
    const { w, root, doc, statuses } = make();
    vi.spyOn(w.chart, 'takeScreenshot').mockReturnValue(canvas({ toDataURL: () => 'data:image/png;base64,iVBORw0KGgo=' }));
    const made = anchors(doc);
    const attached = vi.spyOn(doc.body, 'appendChild');
    press(root, 'Download PNG');
    expect(made).toHaveLength(1);
    expect(made[0]!.clicks).toBe(1);
    expect((made[0] as unknown as { download: string }).download).toMatch(/^INFY-5m-.*\.png$/);
    // Attached for the click, as an engine may download only from an anchor in the document, then taken away again.
    expect(attached).toHaveBeenCalledWith(made[0]);
    expect(made[0]!.parentNode).toBeNull();
    expect(statuses).toEqual(['info Saved a PNG of the chart']);
  });

  it('reports a copy the canvas refuses instead of throwing out of the menu', () => {
    clipboard();
    const { w, root, statuses } = make();
    vi.spyOn(w.chart, 'takeScreenshot').mockReturnValue(canvas({ toBlob: () => { throw new Error('tainted'); } }));
    expect(() => press(root, 'Copy image')).not.toThrow();
    expect(statuses).toEqual(['error Copy failed: tainted']);
  });

  it('copies the chart as a PNG and says so once the clipboard has it', async () => {
    const written = clipboard();
    const { w, root, statuses } = make();
    const blob = new Blob(['png'], { type: 'image/png' });
    vi.spyOn(w.chart, 'takeScreenshot').mockReturnValue(canvas({ toBlob: done => done(blob) }));
    press(root, 'Copy image');
    await Promise.resolve();
    await Promise.resolve();
    expect(written).toHaveLength(1);
    expect((written[0]![0] as { parts: Record<string, Blob> }).parts).toEqual({ 'image/png': blob });
    expect(statuses).toEqual(['info Chart copied']);
  });
});

describe('the chart grid capture', () => {
  it('copies every chart through the same clipboard path and says so on the active chart', async () => {
    const written = clipboard();
    const { grid } = makeGrid({ preset: '1x2' });
    const blob = new Blob(['png'], { type: 'image/png' });
    vi.spyOn(grid, 'takeScreenshot').mockReturnValue(canvas({ toBlob: done => done(blob) }));
    const toast = vi.spyOn(grid.active().widget.context, 'toast');
    press(grid.active().widget.root as unknown as FakeElement, 'Copy image of every chart');
    await Promise.resolve();
    await Promise.resolve();
    expect(written).toHaveLength(1);
    expect(toast).toHaveBeenCalledWith('Every chart copied', 'info');
  });
});
