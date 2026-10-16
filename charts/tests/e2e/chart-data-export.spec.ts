import { readFile } from 'node:fs/promises';
import { test, expect, type Page, type Locator } from '@playwright/test';

const ORIGIN = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;

async function reference(page: Page) {
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
}
async function csv(page: Page, button: Locator) {
  await button.click();
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download CSV', exact: true }).click()]);
  const path = await download.path();
  if (!path) throw new Error('Missing downloaded CSV');
  return { filename: download.suggestedFilename(), rows: (await readFile(path, 'utf8')).trimEnd().split('\r\n').map(row => row.split(',')) };
}

async function downloadRows(page: Page, button: Locator) {
  const [download] = await Promise.all([page.waitForEvent('download'), button.click()]);
  const path = await download.path();
  if (!path) throw new Error('Missing downloaded CSV');
  return (await readFile(path, 'utf8')).trimEnd().split('\r\n').map(row => row.split(','));
}

async function openDataDialog(page: Page, host: 'widget' | 'reference') {
  if (host === 'widget') {
    const desktopCapture = page.getByRole('button', { name: 'Capture chart', exact: true });
    if (await desktopCapture.isVisible()) await desktopCapture.click();
    else {
      await page.locator('[data-mobile-action="more"]').click();
      await page.locator('[data-mobile-action="capture"]').click();
    }
    await page.getByRole('menuitem', { name: /Download chart data \(CSV\)/ }).click();
  } else {
    await page.getByRole('button', { name: 'Chart snapshot', exact: true }).click();
    await page.locator('#snap-data').click();
  }
  const dialog = page.locator(host === 'widget' ? '.oac-csv' : '#chartdatamodal .csv-card');
  await expect(dialog).toBeVisible();
  return {
    dialog,
    from: dialog.locator(host === 'widget' ? '[data-key="from"] input' : '#csv-from'),
    to: dialog.locator(host === 'widget' ? '[data-key="to"] input' : '#csv-to'),
    alignment: dialog.locator(host === 'widget' ? '[data-key="alignment"] select' : '#csv-alignment'),
    studies: dialog.locator(host === 'widget' ? '[data-key^="study-"] input' : '#csv-studies input'),
    visible: dialog.locator(host === 'widget' ? '[data-action="csv-visible"]' : '#csv-visible'),
    all: dialog.locator(host === 'widget' ? '[data-action="csv-all"]' : '#csv-all-rows'),
    download: dialog.getByRole('button', { name: 'Download CSV', exact: true }),
    error: dialog.locator(host === 'widget' ? '.oac-csv__error' : '#csv-error'),
  };
}

/** One-minute bars from 09:15 IST on 28 September 2026. */
const T0 = Date.UTC(2026, 8, 28, 3, 45) / 1000;
const at = (index: number): number => T0 + index * 60;
/** A time as a datetime field takes it on `zone`'s clock, to the second. */
function wall(time: number, zone: string): string {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(time * 1000)).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
}
/** What the field shows for it: a browser writes whole minutes without their seconds. */
const shown = (value: string): RegExp => new RegExp(`^${value.replace(/:00$/, '')}(:00)?$`);

for (const host of ['widget', 'reference'] as const) for (const width of [1100, 390]) {
  test(`${host} selected CSV controls preserve captured choices and shifted replay at ${width}px`, async ({ page }, info) => {
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height: 820 });
    if (host === 'widget') {
      await page.goto('/tests/e2e/widget-fixture.html');
      await page.waitForFunction(() => (window as any).__loaded > 0);
    } else {
      await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
      await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
    }
    const state = await page.evaluate(([host, t0]) => {
      const chart = host === 'widget' ? (window as any).__widget.chart : (window as any).__oac.app.chart;
      chart.indicators().slice().forEach((study: any) => study.remove());
      const bars = Array.from({ length: 32 }, (_, index) => ({ time: t0 + index * 60,
        open: 10 + index, high: 11 + index, low: 9 + index, close: 10 + index, volume: index }));
      chart.primarySeries().setData(bars);
      const first = chart.addIndicator('sma', { length: 1 });
      const second = chart.addIndicator('sma', { length: 1 }); second.setVisible(false);
      second.series('ma').applyOptions({ barOffset: 1.5 });
      chart.setVisibleLogicalRange({ from: 4, to: 14 });
      const view = chart.getVisibleLogicalRange();
      const visible = bars.filter(bar => { const i = chart.dataLayer.timeToIndex(bar.time); return i >= view.from && i <= view.to; });
      (window as any).__csvFixture = { chart, bars, first, second };
      return { first: first.id, second: second.id, names: [first.name, second.name], from: visible[0].time, to: visible[visible.length - 1].time,
        zone: chart.timezone() as string };
    }, [host, T0] as const);
    const clock = (time: number): string => wall(time, state.zone);
    let controls = await openDataDialog(page, host);
    await expect(controls.studies).toHaveCount(2);
    // Repeated studies are told apart by their place among their name, never by an internal id.
    await expect(controls.dialog).toContainText(`${state.names[0]} (1)`); await expect(controls.dialog).toContainText(`${state.names[1]} (2)`);
    await expect(controls.dialog).not.toContainText(state.first);
    expect(await controls.dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);
    await page.keyboard.press('Tab');
    expect(await controls.dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);
    const lateId = await page.evaluate(() => {
      const fixture = (window as any).__csvFixture;
      fixture.chart.setVisibleLogicalRange({ from: 18, to: 28 });
      fixture.late = fixture.chart.addIndicator('sma', { length: 1 }); return fixture.late.id;
    });
    // The bounds are a date and a time on the chart's clock, the zone named with them.
    await expect(controls.dialog).toContainText(`Times are on the chart clock, ${state.zone}.`);
    await expect(controls.dialog).not.toContainText('UTC seconds');
    await controls.visible.click();
    await expect(controls.from).toHaveValue(shown(clock(state.from))); await expect(controls.to).toHaveValue(shown(clock(state.to)));
    await expect(controls.studies).toHaveCount(2);
    await controls.studies.nth(0).uncheck();
    // A browser keeps a whole minute without its seconds, so a field takes it that way.
    await controls.from.fill(clock(at(20)).slice(0, 16)); await controls.to.fill(clock(at(10)).slice(0, 16)); await controls.download.click();
    await expect(controls.error).toContainText(/before|later/); await expect(controls.dialog).toBeVisible();
    // A To written to the minute takes in the bars that open inside it.
    await controls.from.fill(clock(at(1)).slice(0, 16)); await controls.to.fill(clock(at(2)).slice(0, 16));
    const box = await controls.dialog.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
    expect(await controls.dialog.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
    await page.screenshot({ path: info.outputPath(`${host}-${width}-selected-controls.png`) });
    const source = await downloadRows(page, controls.download);
    expect(source[0]).toEqual(['time', 'open', 'high', 'low', 'close', 'volume', 'oi', `indicator:${state.second}:ma`]);
    expect(source.slice(1).map(row => [row[0], row[4], row[7]])).toEqual([[String(at(1)), '11', '11'], [String(at(2)), '12', '12']]);
    expect(source[0].join(',')).not.toContain(lateId);

    controls = await openDataDialog(page, host);
    await controls.studies.nth(0).uncheck(); await controls.studies.nth(2).uncheck();
    // To the second, so the half-bar plot position after the last bar stays out.
    await controls.alignment.selectOption('display'); await controls.from.fill(clock(at(2)).slice(0, 16)); await controls.to.fill(clock(at(4) + 1));
    const displayed = await downloadRows(page, controls.download);
    expect(displayed[0]).toEqual(['time', 'logical_index', 'time_origin', 'open', 'high', 'low', 'close', 'volume', 'oi', `indicator:${state.second}:ma`]);
    expect(displayed.slice(1).map(row => [row[0], row[2], row[6], row[9]]))
      .toEqual([[String(at(2)), 'axis', '12', ''], [String(at(2) + 30), 'interpolated', '', '11'], [String(at(3)), 'axis', '13', ''],
        [String(at(3) + 30), 'interpolated', '', '12'], [String(at(4)), 'axis', '14', '']]);

    await page.evaluate(async () => {
      const fixture = (window as any).__csvFixture;
      const path = '/dist/openalgo-charts.mjs', { ReplayController } = await import(path);
      fixture.second.series('ma').applyOptions({ barOffset: 1 });
      fixture.replay = new ReplayController(fixture.chart, { series: fixture.chart.primarySeries(), bars: fixture.bars, startIndex: 2 });
    });
    controls = await openDataDialog(page, host);
    await controls.studies.nth(0).uncheck(); await controls.studies.nth(2).uncheck();
    await controls.alignment.selectOption('display');
    const replay = await downloadRows(page, controls.download);
    expect(replay.slice(1).map(row => [row[0], row[2], row[6], row[9]]))
      .toEqual([[String(at(0)), 'axis', '10', ''], [String(at(1)), 'axis', '11', '10'], [String(at(2)), 'axis', '12', '11'], [String(at(3)), 'projected', '', '12']]);
    await page.evaluate(async () => {
      (window as any).__csvFixture.chart.fitContent();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    const ink = await page.locator(host === 'widget' ? '.oac-chart canvas' : '#chart canvas').first().evaluate(node => {
      const canvas = node as HTMLCanvasElement;
      const rgba = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
      let colored = 0;
      for (let i = 0; i < rgba.length; i += 4) if (Math.max(rgba[i], rgba[i + 1], rgba[i + 2]) - Math.min(rgba[i], rgba[i + 1], rgba[i + 2]) > 50) colored++;
      return colored;
    });
    expect(ink).toBeGreaterThan(30);
    await page.screenshot({ path: info.outputPath(`${host}-${width}-replay-chart.png`) });
    controls = await openDataDialog(page, host);
    await controls.from.focus(); await page.keyboard.press('Escape'); await expect(controls.dialog).toBeHidden();
    if (host === 'widget' && width === 390) await expect(page.locator('[data-mobile-action="more"]')).toBeFocused();
    expect(errors).toEqual([]);
  });
}

test('reference layouts download the captured chart with OI studies and aligned comparisons', async ({ page }, info) => {
  await reference(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac.app.chart2 && !(window as any).__oac.app.loading2);
  const expected = await page.evaluate(async () => {
    const app = (window as any).__oac.app, chart = app.chart2, bars = chart.primaryBars();
    chart.primarySeries().update({ ...bars.at(-1), oi: 0 });
    const study = chart.addIndicator('ema', { length: 2 });
    const path = '/dist/openalgo-charts.mjs', { addComparison } = await import(path);
    addComparison(chart, { symbol: 'COMPARED', bars: chart.primaryBars().filter((_: unknown, index: number) => index % 2 === 0)
      .map((bar: any) => ({ ...bar, close: bar.close + 50 })) });
    return { count: bars.length, first: bars[0], last: chart.primaryBars().at(-1), study: study.id };
  });
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Layouts', exact: true });
  await expect(dialog.locator('#ws-data-source')).toContainText('Chart 2: MSFT');
  await page.evaluate(() => { (window as any).__oac.app.focusPane = 1; });
  const result = await csv(page, dialog.getByRole('button', { name: 'Download chart data (CSV)', exact: true }));
  expect(result.filename).toMatch(/^MSFT-1h-candlestick-.*\.csv$/);
  expect(result.rows).toHaveLength(expected.count + 1);
  expect(result.rows[0]).toEqual(expect.arrayContaining(['time', 'oi', `indicator:${expected.study}:ma`, 'comparison:1:COMPARED:close']));
  expect(result.rows[1].slice(0, 7)).toEqual([expected.first.time, expected.first.open, expected.first.high,
    expected.first.low, expected.first.close, expected.first.volume, ''].map(String));
  expect(result.rows.at(-1)![6]).toBe('0');
  const comparison = result.rows[0].indexOf('comparison:1:COMPARED:close');
  expect(result.rows[1][comparison]).toBe(String(expected.first.close + 50));
  expect(result.rows[2][comparison]).toBe('');
  await page.screenshot({ path: info.outputPath('data-export-layout.png') });
  await page.setViewportSize({ width: 390, height: 740 });
  const button = dialog.getByRole('button', { name: 'Download chart data (CSV)', exact: true });
  await button.scrollIntoViewIfNeeded();
  const box = await button.boundingBox(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath('data-export-narrow.png') });
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.evaluate(() => {
    const app = (window as any).__oac.app;
    app.focusPane = 2; app.p2.chartType = 't:heikin-ashi'; app.rebuildSecondary({ typeChanged: true });
  });
  await page.getByRole('button', { name: 'Chart snapshot', exact: true }).click();
  const transformed = await csv(page, page.locator('#snap-data'));
  expect(transformed.filename).toMatch(/^MSFT-1h-heikin-ashi-/);
  expect(Number(transformed.rows[1][4])).toBe((expected.first.open + expected.first.high + expected.first.low + expected.first.close) / 4);
});

test('reference data downloads honor replay and reject an obsolete snapshot menu owner', async ({ page }) => {
  await reference(page);
  const prefix = await page.evaluate(async () => {
    const app = (window as any).__oac.app, path = '/examples/yfinance/src/replay.js', replay = await import(path);
    const last = app.chart.primaryBars().at(-1).time;
    replay.enterReplay(); await replay.startReplayAt(Math.floor(app.currentBars.length / 2));
    return { count: app.chart.primaryBars().length, last: app.chart.primaryBars().at(-1).time, future: last };
  });
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Layouts', exact: true });
  const result = await csv(page, dialog.getByRole('button', { name: 'Download chart data (CSV)', exact: true }));
  expect(result.filename).toContain('-replay-');
  expect(result.rows).toHaveLength(prefix.count + 1); expect(Number(result.rows.at(-1)![0])).toBe(prefix.last);
  expect(result.rows.slice(1).some(row => Number(row[0]) === prefix.future)).toBe(false);
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: 'Chart snapshot', exact: true }).click();
  await page.evaluate(() => { (window as any).__oac.app.req.symbol = 'CHANGED'; });
  await page.locator('#snap-data').click();
  await expect(page.locator('#status')).toContainText('changed');
});

for (const width of [1100, 390]) {
  test(`reference date fields wear the dialog's control style at ${width}px`, async ({ page }, info) => {
    await reference(page);
    await page.setViewportSize({ width, height: 820 });
    const controls = await openDataDialog(page, 'reference');
    // The dialog opens with From focused; the focus ring is compared nowhere here.
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    const look = (locator: Locator) => locator.evaluate(node => {
      const css = getComputedStyle(node);
      return { height: css.height, background: css.backgroundColor, border: `${css.borderTopWidth} ${css.borderTopStyle} ${css.borderTopColor}`,
        radius: css.borderTopLeftRadius, font: `${css.fontSize} ${css.fontFamily}`, color: css.color };
    });
    // The From and To fields read as the Alignment select beside them, not as the browser's own field.
    // Polled: the border eases its colour over a tenth of a second after the blur.
    const select = await look(controls.alignment);
    await expect.poll(() => look(controls.from)).toEqual(select);
    await expect.poll(() => look(controls.to)).toEqual(select);
    await controls.dialog.screenshot({ path: info.outputPath(`reference-date-fields-${width}.png`) });
  });
}

test('reference bounds refuse a year before 100 rather than read it as 19xx', async ({ page }, info) => {
  await reference(page);
  const controls = await openDataDialog(page, 'reference');
  let downloads = 0;
  page.on('download', () => { downloads++; });
  // A two-digit year typed for 2026 reaches the field as 0026.
  for (const [bound, value] of [['from', '0026-09-28T09:15'], ['to', '0099-12-31T23:59']] as const) {
    await controls.all.click();
    await controls[bound].fill(value);
    await expect(controls[bound]).toHaveValue(value);
    await controls.download.click();
    await expect(controls.error).toBeVisible();
    await expect(controls.error).toContainText('Enter a date and a time on the chart clock');
    await expect(controls.dialog).toBeVisible();
  }
  await page.screenshot({ path: info.outputPath('reference-low-year.png') });
  expect(downloads).toBe(0);
});

test('widget capture downloads actual CSV and reports browser file failures', async ({ page }, info) => {
  await page.goto('/tests/e2e/widget-fixture.html');
  await page.waitForFunction(() => (window as any).__loaded > 0);
  const expected = await page.evaluate(() => {
    const widget = (window as any).__widget, bars = widget.chart.primaryBars();
    widget.series.update({ ...bars.at(-1), oi: 0 });
    return { count: bars.length, last: bars.at(-1).time };
  });
  await page.getByRole('button', { name: 'Capture chart', exact: true }).click();
  await page.screenshot({ path: info.outputPath('widget-data-export.png') });
  const result = await csv(page, page.getByRole('menuitem', { name: /Download chart data \(CSV\)/ }));
  expect(result.filename).toMatch(/^FIXTURE-5m-.*\.csv$/);
  expect(result.rows).toHaveLength(expected.count + 1); expect(Number(result.rows.at(-1)![0])).toBe(expected.last);
  expect(result.rows.at(-1)![6]).toBe('0');
  await page.evaluate(() => { URL.createObjectURL = () => { throw new Error('Download refused'); }; });
  await page.getByRole('button', { name: 'Capture chart', exact: true }).click();
  await page.getByRole('menuitem', { name: /Download chart data \(CSV\)/ }).click();
  await page.getByRole('button', { name: 'Download CSV', exact: true }).click();
  await expect(page.locator('.oac-statusline__msg')).toContainText('Download refused');
});

test('widget refuses CSV after its capture menu source changes', async ({ page }) => {
  await page.goto('/tests/e2e/widget-fixture.html');
  await page.waitForFunction(() => (window as any).__loaded > 0);
  await page.getByRole('button', { name: 'Capture chart', exact: true }).click();
  await page.evaluate(() => (window as any).__widget.setSymbol('CHANGED'));
  await page.getByRole('menuitem', { name: /Download chart data \(CSV\)/ }).click();
  await expect(page.locator('.oac-statusline__msg')).toContainText('changed');
});
