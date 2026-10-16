/**
 * The chart's typed event bus, checked from both ends.
 *
 * `ChartEventMap` names every event the engine puts on `chart.on(...)` with the
 * payload a listener receives. A map is only worth having while it is true, and
 * nothing at runtime ties an `emit('name', payload)` call to it: most of the
 * engine's emits go through a tier's own structural host, whose `emit` takes a
 * string. So the inventory is checked with the compiler over the whole of src:
 * every name a chart-bus emit call gives is a key, the payload it passes fits
 * the declaration, every name a subscriber in src listens for is a key, and no
 * code in src subscribes through the deprecated string overload.
 *
 * The overloads themselves are checked by type: this file is type-checked with
 * the rest of `tests` (tests/tsconfig.json), so an `expectTypeOf` that does
 * not hold, or a `@ts-expect-error` over a line that compiles, fails
 * `npm run typecheck`.
 */
/// <reference types="vite/client" />
import ts from 'typescript';
import { afterEach, describe, expect, expectTypeOf, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { TradingController, type TradingHost } from '../src/core/trading-controller';
import { ShortcutManager } from '../src/input/shortcuts';
import type {
  AlertChartHost, ChartClickEvent, ChartEventMap, ChartViewportEvent, CrosshairMoveEvent, EmptyEvent, LinkChart,
  PickHost, ReplayChartHost, ReplayGroupChartHost,
} from '../src/index';
import type { DrawingChartHost, DrawingEvent } from '../src/draw/index';
import { fakeDocument } from './helpers/fake-dom';

// Same root derivation as deprecation-policy.test.ts: the suite carries no
// Node typings.
const ROOT = decodeURIComponent(new URL('..', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1');

function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  return chart;
}

describe('the typed overloads', () => {
  it('type a listener by the name it subscribes to', () => {
    const chart = makeChart();
    const offs = [
      chart.on('click', (e) => { expectTypeOf(e).toEqualTypeOf<ChartClickEvent>(); }),
      chart.on('crosshair:move', (e) => { expectTypeOf(e).toEqualTypeOf<CrosshairMoveEvent>(); }),
      chart.once('pan', (e) => { expectTypeOf(e).toEqualTypeOf<ChartViewportEvent>(); }),
      chart.on('objects:change', (e) => { expectTypeOf(e).toEqualTypeOf<EmptyEvent>(); }),
      // The draw tier's names arrive by declaration merging from src/draw/events.ts.
      chart.on('draw:add', (e) => { expectTypeOf(e).toEqualTypeOf<DrawingEvent>(); }),
      chart.on('drawing:select', (e) => { expectTypeOf(e.ids).toEqualTypeOf<string[]>(); }),
    ];
    // A name union types the payload as the union of theirs.
    const viewport: 'pan' | 'zoom' = 'zoom';
    offs.push(chart.on(viewport, (e) => { expectTypeOf(e).toEqualTypeOf<ChartViewportEvent>(); }));
    // @ts-expect-error `resize` carries a size, not a pane.
    offs.push(chart.on('resize', (e) => e.paneIndex));
    // A listener written for a wider payload still fits a typed name.
    const wide = (payload: unknown): void => { void payload; };
    offs.push(chart.on('click', wide));
    chart.off('click', wide);
    chart.off('click');
    for (const off of offs) off();
    expectTypeOf<ChartEventMap['resize']>().toEqualTypeOf<{ width: number; height: number }>();
  });

  it('keep a name outside the map compiling through the deprecated string overload', () => {
    const chart = makeChart();
    const seen: unknown[] = [];
    const name: string = 'host:custom';
    const off = chart.on(name, (payload) => { expectTypeOf(payload).toEqualTypeOf<unknown>(); seen.push(payload); });
    chart.emit(name, 7);
    off();
    chart.emit(name, 8);
    expect(seen).toEqual([7]);
  });

  it('leave Chart assignable to every structural host that takes event names as strings', () => {
    expectTypeOf<Chart>().toExtend<AlertChartHost>();
    expectTypeOf<Chart>().toExtend<PickHost>();
    expectTypeOf<Chart>().toExtend<LinkChart>();
    expectTypeOf<Chart>().toExtend<ReplayGroupChartHost>();
    expectTypeOf<Chart>().toExtend<TradingHost>();
    expectTypeOf<Chart>().toExtend<DrawingChartHost>();
    expectTypeOf<Pick<Chart, 'on' | 'emit'>>().toExtend<Pick<ReplayChartHost, 'emit'>>();
  });
});

describe('payload shapes', () => {
  it('objects:change always carries an empty object, the navigation switches included', () => {
    const chart = makeChart();
    const payloads: unknown[] = [];
    chart.on('objects:change', (p) => payloads.push(p));
    chart.setNavigationOptions({ panEnabled: false });
    chart.setIndicatorLegendCollapsed(true);
    expect(payloads.length).toBeGreaterThanOrEqual(2);
    for (const p of payloads) expect(p).toEqual({});
  });
});

describe('a listener that throws', () => {
  const reported: unknown[] = [];
  const g = globalThis as { reportError?: (error: unknown) => void };
  const install = (): void => { g.reportError = (error: unknown) => { reported.push(error); }; };
  afterEach(() => { delete g.reportError; reported.length = 0; });

  it('on the chart bus: the others still run, and the error is reported rather than swallowed', () => {
    install();
    const chart = makeChart();
    const boom = new Error('host listener');
    let reached = false;
    chart.on('resize', () => { throw boom; });
    chart.on('resize', () => { reached = true; });
    expect(() => chart.applySize(900, 600)).not.toThrow();
    expect(reached).toBe(true);
    expect(reported).toEqual([boom]);
  });

  it('on the chart bus with no reporter: the others still run and nothing escapes', () => {
    const chart = makeChart();
    let reached = false;
    chart.on('resize', () => { throw new Error('host listener'); });
    chart.on('resize', () => { reached = true; });
    expect(() => chart.applySize(900, 600)).not.toThrow();
    expect(reached).toBe(true);
  });

  it('on the trading bus: the other listeners and the chart-bus copy still run', () => {
    install();
    let click: (id: string) => void = () => {};
    const mirrored: unknown[] = [];
    const host: TradingHost = {
      addPrimitive: () => {}, removePrimitive: () => {},
      subscribeClick: (cb) => { click = cb; }, subscribeDrag: () => {},
      emit: (event, payload) => { mirrored.push([event, payload]); },
    };
    const trading = new TradingController(host);
    trading.setOrders([{ id: 'o1', type: 'limit', side: 'buy', price: 10, size: 1 }]);
    const boom = new Error('host listener');
    const seen: unknown[] = [];
    trading.on('trading:order_cancel', () => { throw boom; });
    trading.on('trading:order_cancel', (p) => seen.push(p));
    expect(() => click('ord:o1::close')).not.toThrow();
    expect(seen).toEqual([{ orderId: 'o1' }]);
    expect(mirrored).toEqual([['trading:order_cancel', { orderId: 'o1' }]]);
    expect(reported).toEqual([boom]);
  });

  it('on the shortcut manager: the other listeners still run', () => {
    install();
    const shortcuts = new ShortcutManager();
    const boom = new Error('host listener');
    const seen: string[] = [];
    shortcuts.on(() => { throw boom; });
    shortcuts.on((e) => seen.push(e.command));
    expect(() => shortcuts.emitTrigger('resetScale')).not.toThrow();
    expect(seen).toEqual(['resetScale']);
    expect(reported).toEqual([boom]);
  });
});

/**
 * The declarations whose `emit` puts a (name, payload) pair on the chart bus:
 * the chart itself, and each structural host a tier drives it through.
 */
const EMITTERS = new Set([
  'Chart.emit', 'Chart._emit', 'AlertChartHost.emit', 'ReplayChartHost.emit', 'DrawingChartHost.emit',
  'PickHost.emit', 'IndicatorHost.emit', 'GestureHost.emit', 'TradingController._emit',
]);
/** Emitters handed only the name; they build the payload themselves. */
const NAME_ONLY = new Set(['Chart._emitViewport', 'ReplayGroup._emit']);
/** The declarations whose `on`, `once` or `off` subscribe to the chart bus. */
const SUBSCRIBERS = new Set([
  'Chart.on', 'AlertChartHost.on', 'DrawingChartHost.on', 'PickHost.on', 'LinkChart.on', 'ReplayChartHost.on',
  'ReplayGroupChartHost.on', 'InstrumentDrawingsChart.on', 'ComparisonChartHost.on',
]);
/** Names a host emits and the engine only listens for; nothing in src emits them. */
const HOST_ONLY = ['chartType', 'interval'];

interface Site { file: string; line: number; via: string; names: string[]; payload?: ts.Expression; call: ts.CallExpression }

/** The string literals an event-name argument can evaluate to, or null when it is not literal. */
function literalNames(arg: ts.Expression | undefined): string[] | null {
  if (arg === undefined) return null;
  if (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) return [arg.text];
  if (ts.isParenthesizedExpression(arg)) return literalNames(arg.expression);
  if (ts.isConditionalExpression(arg)) {
    const a = literalNames(arg.whenTrue), b = literalNames(arg.whenFalse);
    return a !== null && b !== null ? [...a, ...b] : null;
  }
  return null;
}

describe('the event inventory', () => {
  const parsed = ts.getParsedCommandLineOfConfigFile(`${ROOT}tsconfig.json`, {}, {
    ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {},
  });
  if (parsed === undefined) throw new Error('tsconfig.json did not parse');
  const rootNames = parsed.fileNames.filter((f) => f.replace(/\\/g, '/').includes('/src/'));
  const program = ts.createProgram({ rootNames, options: parsed.options });
  const checker = program.getTypeChecker();

  const entry = program.getSourceFile(`${ROOT}src/index.ts`);
  const mapAlias = entry && checker.getExportsOfModule(checker.getSymbolAtLocation(entry)!).find((s) => s.name === 'ChartEventMap');
  const mapSymbol = mapAlias && (mapAlias.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(mapAlias) : mapAlias);
  const mapType = mapSymbol && checker.getDeclaredTypeOfSymbol(mapSymbol);
  const keys = new Set(mapType ? checker.getPropertiesOfType(mapType).map((p) => p.name) : []);

  const emits: Site[] = [];
  const subscriptions: Site[] = [];
  const deprecatedCalls: string[] = [];
  for (const source of program.getSourceFiles()) {
    const file = source.fileName.replace(/\\/g, '/');
    if (!file.includes('/src/') || file.endsWith('.d.ts')) continue;
    const visit = (node: ts.Node): void => {
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
        const method = node.expression.name.text;
        if (['emit', '_emit', '_emitViewport', 'on', 'once', 'off'].includes(method)) {
          const declaration = checker.getResolvedSignature(node)?.declaration;
          const owner = declaration && ts.getNameOfDeclaration(declaration.parent as ts.Declaration);
          const via = `${owner?.getText() ?? '?'}.${method}`;
          const names = literalNames(node.arguments[0]);
          const line = source.getLineAndCharacterOfPosition(node.getStart()).line + 1;
          const site = { file: file.slice(file.indexOf('/src/') + 1), line, via, names: names ?? [], payload: node.arguments[1], call: node };
          if (EMITTERS.has(via) || NAME_ONLY.has(via)) { if (names !== null) emits.push(site); }
          else if (SUBSCRIBERS.has(via)) {
            if (names !== null) subscriptions.push(site);
            if (via.startsWith('Chart.') && declaration !== undefined
              && ts.getJSDocTags(declaration).some((tag) => tag.tagName.text === 'deprecated')) deprecatedCalls.push(`${site.file}:${line}`);
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }

  it('finds the map and every emitter and subscriber it is told about', () => {
    expect(keys.size).toBeGreaterThan(80);
    const vias = new Set([...emits, ...subscriptions].map((s) => s.via));
    expect([...EMITTERS, ...NAME_ONLY, ...SUBSCRIBERS].filter((v) => !vias.has(v))).toEqual([]);
  });

  it('declares every name a chart-bus emit gives, with a payload the declaration accepts', () => {
    const undeclared: string[] = [];
    const mistyped: string[] = [];
    for (const site of emits) {
      for (const name of site.names) {
        const prop = mapType?.getProperty(name);
        if (prop === undefined) { undeclared.push(`${name} at ${site.file}:${site.line}`); continue; }
        if (NAME_ONLY.has(site.via) || site.payload === undefined) continue;
        const declared = checker.getTypeOfSymbolAtLocation(prop, site.call);
        const given = checker.getTypeAtLocation(site.payload);
        if (!checker.isTypeAssignableTo(given, declared)) {
          mistyped.push(`${name} at ${site.file}:${site.line}: ${checker.typeToString(given)} is not ${checker.typeToString(declared)}`);
        }
      }
    }
    expect(undeclared).toEqual([]);
    expect(mistyped).toEqual([]);
  });

  it('declares nothing src never emits, apart from the names a host emits', () => {
    const emitted = new Set(emits.flatMap((s) => s.names));
    expect([...keys].filter((k) => !emitted.has(k)).sort()).toEqual(HOST_ONLY);
  });

  it('subscribes in src only to declared names, and never through the deprecated string overload', () => {
    const unknownNames = subscriptions.flatMap((s) => s.names.filter((n) => !keys.has(n)).map((n) => `${n} at ${s.file}:${s.line}`));
    expect(unknownNames).toEqual([]);
    expect(deprecatedCalls).toEqual([]);
  });
}, 120_000);
