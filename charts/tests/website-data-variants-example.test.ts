import ts from 'typescript';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { STOCK_BARS_SOURCE } from '../website/components/synthetic-market';
import examplesPage from '../website/pages/examples.mdx?raw';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/widget';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, type FakeElement } from './helpers/fake-dom-widget';

// The page's data variants example, run against the real widget: each button
// asks the simulated provider for its own series, and the one it does not
// declare is reported, never fetched.

beforeAll(ensureWindowGlobal);
const flush = async (): Promise<void> => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
let widget: Widget | null = null;
afterEach(() => { widget?.destroy(); widget = null; vi.unstubAllGlobals(); });

function exampleCode(): string {
  const section = examplesPage.split('## Regular and extended hours')[1];
  expect(section).toBeDefined();
  const start = section.indexOf('code={`') + 'code={'.length;
  const end = section.indexOf('`} />', start) + 1;
  const source = ts.createSourceFile('example.ts', `const code = ${section.slice(start, end)};`, ts.ScriptTarget.Latest, true);
  let code = '';
  const visit = (node: ts.Node): void => {
    if (ts.isVariableDeclaration(node) && node.initializer && ts.isTemplateExpression(node.initializer)) {
      code = node.initializer.head.text;
      for (const span of node.initializer.templateSpans) {
        expect(span.expression.getText(source)).toBe('STOCK_BARS_SOURCE');
        code += STOCK_BARS_SOURCE + span.literal.text;
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  expect(code).not.toBe('');
  return code;
}

it('loads each session from the provider and reports the adjustment it does not serve', async () => {
  const doc = fakeWidgetDocument();
  vi.stubGlobal('document', doc);
  const el = fakeContainer(doc, 900, 500);
  const requests: unknown[] = [];
  const lib = {
    createWidget: (host: HTMLElement, options: WidgetOptions) => {
      const feed = options.feed!;
      widget = createWidget(host, { ...options, document: doc as unknown as Document, pixelRatio: () => 1,
        raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
        feed: { ...feed, getBars: request => { requests.push(request.variant ?? null); return feed.getBars(request); } } });
      widget.chart.applySize(900, 440);
      return widget;
    },
  };
  new Function('el', 'lib', exampleCode())(el, lib);
  await flush();
  const shown = (): number => widget!.series.getData().length;
  const regular = shown();
  // Three simulated days of 5-minute bars from 09:30 to 16:00 New York time.
  expect(regular).toBe(3 * 78);
  // The example wires `onclick`, which the fake document does not dispatch, so it is called as a press would.
  const press = (label: string): void => {
    const button = (el as unknown as FakeElement).querySelectorAll('button').find(item => item.textContent === label);
    (button as unknown as { onclick: () => void }).onclick();
  };
  press('Extended hours');
  await flush();
  expect(shown()).toBe(3 * 192);
  // The regular bars are the middle of the extended day, not a second derivation.
  const extendedTimes = new Set(widget!.series.getData().map(bar => bar.time));
  expect(widget!.chart.getDataContext()?.variant).toEqual({ session: 'extended' });
  press('Raw prices');
  await flush();
  expect(widget!.dataController!.getState()).toMatchObject({ status: 'unsupported', unsupported: 'adjustment' });
  expect(requests).toEqual([null, { session: 'extended' }]);
  press('Regular hours');
  await flush();
  expect(shown()).toBe(regular);
  for (const bar of widget!.series.getData()) expect(extendedTimes.has(bar.time)).toBe(true);
  expect(requests).toEqual([null, { session: 'extended' }, null]);
});
