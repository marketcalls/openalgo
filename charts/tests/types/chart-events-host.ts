/**
 * A host's use of the chart's event bus, as a type check with nothing to run.
 *
 * It is compiled twice. `npm run typecheck` compiles it against src, like the
 * rest of `tests`. scripts/check-dts.mjs compiles it against the built
 * declarations in dist, which is the check that matters for the draw tier:
 * its `draw:*` and `drawing:*` names reach `ChartEventMap` by declaration
 * merging, and that merge has to survive bundling into dist/draw/index.d.ts.
 *
 * The second half holds the shapes a trading host already writes against the
 * untyped bus of 2.5 (casts inside a listener, a listener typed `unknown`, a
 * name from a string array, an event of its own, `emit` from a test), so a
 * change that stops one of them compiling fails here first.
 */
import {
  AlertController, ReplayController, createChart, createLinkGroup,
  type ChartClickEvent, type ChartViewportEvent, type ContextMenuEvent, type CrosshairMoveEvent, type EmptyEvent,
} from 'openalgo-charts';
import { DrawingController, type DrawingEvent, type DrawingIdsEvent } from 'openalgo-charts/draw';

declare module 'openalgo-charts' {
  interface ChartEventMap {
    'probe:signal': { price: number };
  }
}

export function typedBus(el: HTMLElement): void {
  const chart = createChart(el);
  const offs: (() => void)[] = [
    chart.on('click', (e) => { const click: ChartClickEvent = e; void click; }),
    chart.once('pan', (e) => { const range: ChartViewportEvent = e; void range; }),
    chart.on('objects:change', (e) => { const none: EmptyEvent = e; void none; }),
    chart.on('draw:add', (e) => { const added: DrawingEvent = e; void added.drawing.id; }),
    chart.on('drawing:select', (e) => { const selection: DrawingIdsEvent = e; void selection.ids; }),
    chart.on('probe:signal', ({ price }) => { const n: number = price; void n; }),
  ];
  // @ts-expect-error `draw:add` carries one drawing, not a list of ids.
  offs.push(chart.on('draw:add', (e) => e.ids));
  chart.off('click');
  for (const off of offs) off();
}

export function hostPatterns(el: HTMLElement): void {
  const chart = createChart(el);
  new DrawingController(chart);
  new AlertController(chart);
  new ReplayController(chart);
  createLinkGroup().add(chart);

  chart.on('contextmenu', (payload) => { const event = payload as ContextMenuEvent; event.preventDefault(); });
  chart.on('indicatorSettings', (p) => { void (p as { instanceId: string }).instanceId; });
  chart.on('indicatorSource', (p) => { void String((p as { indicatorId?: unknown }).indicatorId ?? ''); });
  chart.on('draw:add', (p) => { void (p as { drawing?: { id: string; tool: string; text?: { value?: string } } }).drawing; });
  chart.on('dblclick', (p) => { (p as { handled?: boolean }).handled = true; });
  chart.on('crosshair:move', (payload) => { const e = payload as CrosshairMoveEvent; void e.point?.x; });
  chart.on('alerts:changed', (payload: unknown) => { void (payload as { id?: unknown } | undefined)?.id; });

  const deliver = (payload: unknown): void => { void payload; };
  chart.on('alert:triggered', deliver);
  chart.on('indicator:alert', deliver);
  // A name of the host's own that it has not declared: the deprecated string form.
  const HOST_EVENT = 'host:alert';
  chart.on(HOST_EVENT, deliver);
  for (const event of ['alert:created', 'alert:updated', 'alert:removed']) chart.on(event, () => {});
  chart.emit('contextmenu', { paneIndex: 0, point: { x: 1, y: 2 }, price: 1, time: 1, index: 0, target: { kind: 'empty', id: null }, preventDefault() {} });
  chart.emit('symbol', { symbol: 'RELIANCE', exchange: 'NSE' });
}
