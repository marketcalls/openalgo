import ts from 'typescript';
import { afterEach, expect, it, vi } from 'vitest';
import { STOCK_BARS_SOURCE } from '../website/components/synthetic-market';
import examplesPage from '../website/pages/examples.mdx?raw';
import { WatchlistRepository, createMemoryWatchlistStorage } from '../src/workspace/index';
import type { Bar, BarsRequest, QuoteFeed, QuoteSnapshot } from '../src/index';

/** The runnable code of the page's watchlist example, with its template spans filled in. */
function exampleCode(): string {
  const section = examplesPage.split('## Watchlists and news')[1];
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

interface ExampleFeed {
  getBars(request: BarsRequest): Promise<Bar[]>;
  subscribeBars?(request: BarsRequest, onBar: (bar: Bar) => void): () => void;
}

/** Run the example against the real list store and a recording createWidget; count every simulated bar series built. */
function runExample() {
  const built = { series: 0 };
  // The example's bar generator, wrapped so a quote that reads a candle is caught building one.
  const code = exampleCode().replace('function stockBars(', 'function simulatedBars(')
    + '\n;function stockBars(...args) { built.series++; return simulatedBars(...args); }';
  let options: { feed: ExampleFeed; watchlist: { quotes: QuoteFeed } } | null = null;
  const lib = {
    WatchlistRepository, createMemoryWatchlistStorage,
    createWidget: (_el: unknown, given: typeof options) => { options = given; return { openWatchlist: () => true }; },
  };
  new Function('el', 'lib', 'built', code)({}, lib, built);
  expect(options).not.toBeNull();
  return { built, options: options! };
}

afterEach(() => { vi.useRealTimers(); });

it('prices the watchlist example\'s rows from its quote source, never from a candle', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(Date.UTC(2026, 8, 25, 6, 30));
  const { built, options } = runExample();
  const quotes = options.watchlist.quotes;
  const nova = { symbol: 'NOVA', exchange: 'DEMO' };
  built.series = 0;
  const [snapshot] = await quotes.getQuotes({ instruments: [nova] });
  const ticks: QuoteSnapshot[] = [];
  const stop = quotes.subscribeQuotes!([nova], { onQuote: quote => ticks.push(quote) });
  await vi.advanceTimersByTimeAsync(2100);
  stop();
  expect(ticks.length).toBeGreaterThan(0);
  expect(built.series).toBe(0);
  expect(snapshot.previousClose).toBeGreaterThan(0);
  expect(snapshot.last).toBeGreaterThan(0);
});

it('keeps the example\'s chart and rows on one simulated market, so they agree', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(Date.UTC(2026, 8, 25, 6, 30));
  const { options } = runExample();
  const request = { symbol: 'ORBIT', exchange: 'DEMO', interval: '5m' } as BarsRequest;
  const history = await options.feed.getBars(request);
  const [quote] = await options.watchlist.quotes.getQuotes({ instruments: [{ symbol: 'ORBIT', exchange: 'DEMO' }] });
  expect(history[history.length - 1].close).toBe(quote.last);
  // As the simulated market moves, the forming bar and the row move together.
  const formed: Bar[] = [];
  const ticks: QuoteSnapshot[] = [];
  const stopBars = options.feed.subscribeBars!(request, bar => formed.push(bar));
  const stopQuotes = options.watchlist.quotes.subscribeQuotes!([{ symbol: 'ORBIT', exchange: 'DEMO' }], { onQuote: q => ticks.push(q) });
  await vi.advanceTimersByTimeAsync(7000);
  stopBars(); stopQuotes();
  expect(formed.length).toBeGreaterThan(0);
  expect(formed[formed.length - 1].time).toBe(history[history.length - 1].time);
  expect(formed[formed.length - 1].close).toBe(ticks[ticks.length - 1].last);
  expect(new Set(ticks.map(tick => tick.last)).size).toBeGreaterThan(1);
});
