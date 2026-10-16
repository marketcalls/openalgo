import { test, expect, type Page } from '@playwright/test';

async function openDemo(page: Page, query = '') {
  await page.goto(`/examples/orderflow/index.html?paused=1${query}`);
  await page.waitForFunction(() => typeof (window as any).__orderflowData === 'function');
  await page.waitForFunction(() => (window as any).__footprint().stats().length === 7);
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function pixels(page: Page) {
  await paint(page);
  return page.evaluate(() => {
    const canvas = (window as any).__chart().takeScreenshot() as HTMLCanvasElement;
    const image = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height);
    let red = 0, green = 0;
    for (let i = 0; i < image.data.length; i += 4) {
      const [r, g, b] = image.data.subarray(i, i + 3);
      if (r > g * 1.5 && r > b * 1.2 && r > 80) red++;
      if (g > r * 1.5 && g > b * 0.9 && g > 65) green++;
    }
    return { red, green, png: canvas.toDataURL() };
  });
}

test('classified tape preserves OHLC, volume, trade count and session CVD through grouping and trimming', async ({ page }) => {
  await openDemo(page);
  const original = await page.evaluate(() => {
    const { bars, tape, candles } = (window as any).__orderflowData();
    return { bars, tape, candles, stats: (window as any).__footprint().stats() };
  });
  expect(original.bars).toHaveLength(7);
  expect(original.tape).toHaveLength(420);
  for (let i = 0; i < original.bars.length; i++) {
    const bar = original.bars[i];
    const ticks = original.tape.filter((tick: any) => tick.time >= bar.time && tick.time < bar.time + 60);
    expect(bar.tradeCount).toBe(ticks.length);
    expect(bar.open).toBe(ticks[0].price);
    expect(bar.close).toBe(ticks.at(-1).price);
    expect(bar.high).toBe(Math.max(...ticks.map((tick: any) => tick.price)));
    expect(bar.low).toBe(Math.min(...ticks.map((tick: any) => tick.price)));
    expect(bar.cells.length).toBeGreaterThanOrEqual(8);
    expect(bar.cells.length).toBeLessThanOrEqual(15);
    expect(original.stats[i].trades).toBe(60);
    expect(original.stats[i].volume).toBe(ticks.reduce((sum: number, tick: any) => sum + tick.qty, 0));
    expect(ticks.every((tick: any) => Number.isInteger(tick.price / 1))).toBe(true);
  }
  await page.locator('#group').selectOption('4');
  const grouped = await page.evaluate(() => ({
    ...((window as any).__orderflowData()), stats:(window as any).__footprint().stats(),
  }));
  expect(grouped.tape).toEqual(original.tape);
  expect(grouped.candles).toEqual(original.candles);
  expect(grouped.bars.every((bar: any) => bar.rowSize === 4)).toBe(true);
  expect(grouped.bars[0].cells.length).toBeLessThan(original.bars[0].cells.length);
  for (let i = 0; i < 7; i++) {
    expect(grouped.stats[i].volume).toBe(original.stats[i].volume);
    expect(grouped.stats[i].delta).toBe(original.stats[i].delta);
    expect(grouped.stats[i].cvd).toBe(original.stats[i].cvd);
  }
  await page.evaluate(() => (window as any).__advanceTicks(125));
  const rolled = await page.evaluate(() => {
    const data = (window as any).__orderflowData();
    return { ...data, stats:(window as any).__footprint().stats() };
  });
  const sessionDelta = rolled.tape.reduce((sum: number, tick: any) => sum + (tick.side === 'ask' ? tick.qty : -tick.qty), 0);
  expect(rolled.bars).toHaveLength(7);
  expect(rolled.cvdOffset).toBe(original.bars.slice(0, 3).reduce((sum: number, bar: any) => sum + bar.delta, 0));
  expect(rolled.stats.at(-1).cvd).toBe(sessionDelta);
  await page.locator('#group').selectOption('2');
  expect(await page.evaluate(() => (window as any).__footprint().stats().at(-1).cvd)).toBe(sessionDelta);
  await page.getByRole('button', { name:'Reset', exact:true }).click();
  expect(await page.evaluate(() => (window as any).__orderflowData().bars)).toEqual(original.bars);
  expect(await page.evaluate(() => (window as any).__orderflowData().cvdOffset)).toBe(0);
});

test('styles paint bid and ask volumes and themes and text methods preserve the tape and viewport', async ({ page }) => {
  await page.setViewportSize({ width:1440, height:900 });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await openDemo(page);
  const before = await page.evaluate(() => ({
    data:JSON.stringify((window as any).__orderflowData()), range:(window as any).__chart().timeScale.visibleRange(),
  }));
  const profile = await pixels(page);
  expect(profile.red).toBeGreaterThan(1000);
  expect(profile.green).toBeGreaterThan(1000);
  await page.screenshot({ path:'artifacts/orderflow-profile-midnight.png' });
  for (const style of ['ladder','heatmap']) {
    await page.locator('#style').selectOption(style);
    const raster = await pixels(page);
    expect(raster.red).toBeGreaterThan(1000);
    expect(raster.green).toBeGreaterThan(1000);
    expect(raster.png).not.toBe(profile.png);
    expect(await page.evaluate(() => (window as any).__footprint().options().cellStyle)).toBe(style);
    await page.screenshot({ path:`artifacts/orderflow-${style}-midnight.png` });
  }
  await page.locator('#style').selectOption('profile');
  await page.locator('#text').selectOption('side');
  expect((await pixels(page)).png, 'text methods must affect the rendered numbers').not.toBe(profile.png);
  await page.locator('#text').selectOption('contrast');
  const themes = {
    midnight:['rgb(16, 18, 22)', '#159d87'], graphite:['rgb(26, 27, 30)', '#4cad99'],
    classic:['rgb(5, 6, 5)', '#32e600'], ocean:['rgb(8, 24, 37)', '#12b8c6'], ivory:['rgb(246, 244, 238)', '#147e71'],
  };
  for (const [theme, [background, buy]] of Object.entries(themes)) {
    await page.locator('#theme').selectOption(theme);
    await expect(page.locator('#chart')).toHaveCSS('background-color',background);
    expect(await page.evaluate(() => (window as any).__footprint().options().buyColor)).toBe(buy);
    for (const method of ['contrast','side','delta','dominant','imbalance','volume']) {
      await page.locator('#text').selectOption(method);
      expect(await page.evaluate(() => (window as any).__footprint().options().textColorMode)).toBe(method);
    }
  }
  expect(await page.evaluate(() => ({
    data:JSON.stringify((window as any).__orderflowData()), range:(window as any).__chart().timeScale.visibleRange(),
  }))).toEqual(before);
  await page.locator('#style').selectOption('profile');
  await page.locator('#text').selectOption('contrast');
  await paint(page);
  await page.screenshot({ path:'artifacts/orderflow-profile-ivory.png' });
  await page.locator('#theme').selectOption('classic');
  await page.locator('#style').selectOption('ladder');
  await paint(page);
  await page.screenshot({ path:'artifacts/orderflow-ladder-classic.png' });
  expect(errors).toEqual([]);
});

test('row and per-candle card hover use rendered geometry; display toggles and replay work', async ({ page }) => {
  await openDemo(page);
  await paint(page);
  const hits = await page.evaluate(() => {
    const fp = (window as any).__footprint();
    const chart = (window as any).__chart();
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    let cell: any = null, stats: any = null;
    for (let y = 0; y < rect.height && (!cell || !stats); y += 3) {
      for (let x = 0; x < chart.timeScale.width && (!cell || !stats); x += 3) {
        const hit = fp.hoverAt(x,y);
        if (hit?.cell && !cell) cell = { x:x + rect.left,y:y + rect.top,hit };
        if (hit && hit.cell === null && !stats) stats = { x:x + rect.left,y:y + rect.top,hit };
      }
    }
    return { cell, stats };
  });
  expect(hits.cell).not.toBeNull();
  expect(hits.stats).not.toBeNull();
  await page.mouse.move(hits.cell.x,hits.cell.y);
  await expect(page.locator('#tip')).toContainText('Bid × Ask');
  await page.mouse.move(hits.stats.x,hits.stats.y);
  await expect(page.locator('#tip')).toContainText('Session CVD');
  await expect(page.locator('#tip')).not.toContainText('Bid × Ask');
  for (const mode of ['delta','volume','bidask']) {
    await page.locator('#mode').selectOption(mode);
    expect(await page.evaluate(() => (window as any).__footprint().options().displayMode)).toBe(mode);
  }
  await page.locator('#poc').uncheck();
  await page.locator('#valuearea').uncheck();
  await page.locator('#stats').uncheck();
  const options = await page.evaluate(() => (window as any).__footprint().options());
  expect(options.showPoc).toBe(false);
  expect(options.showValueArea).toBe(false);
  expect(options.statsRows).toEqual([]);
  const count = await page.evaluate(() => (window as any).__orderflowData().tape.length);
  await page.getByRole('button', { name:'Resume', exact:true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__orderflowData().tape.length)).toBeGreaterThan(count);
  await page.getByRole('button', { name:'Pause', exact:true }).click();
  await expect(page.locator('#status')).toContainText('paused');
});

test('direct links reproduce theme, style and text selections with safe defaults', async ({ page }) => {
  await openDemo(page,'&theme=classic&style=ladder&text=imbalance');
  await expect(page.locator('#theme')).toHaveValue('classic');
  await expect(page.locator('#style')).toHaveValue('ladder');
  await expect(page.locator('#text')).toHaveValue('imbalance');
  expect(await page.evaluate(() => (window as any).__footprint().options().cellStyle)).toBe('ladder');
  await openDemo(page,'&theme=unknown&style=unknown&text=unknown');
  await expect(page.locator('#theme')).toHaveValue('midnight');
  await expect(page.locator('#style')).toHaveValue('profile');
  await expect(page.locator('#text')).toHaveValue('contrast');
});

test('fractional-DPR rendering survives zoom, pan, SVG export and a narrow viewport', async ({ browser }) => {
  const context = await browser.newContext({ deviceScaleFactor:1.25, viewport:{ width:1100,height:800 } });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await openDemo(page,'&theme=ocean');
  const before = await page.evaluate(() => JSON.stringify((window as any).__orderflowData()));
  await page.evaluate(() => (window as any).__chart().timeScale.setVisibleLogicalRange({ from:1.5,to:5.8 }));
  await paint(page);
  const report = await page.evaluate(() => {
    const chart = (window as any).__chart();
    const png = chart.takeScreenshot();
    const svg = chart.exportSVG();
    const xml = new DOMParser().parseFromString(svg,'image/svg+xml');
    return { width:png.width, cssWidth:document.getElementById('chart')!.clientWidth,
      svg, invalid:xml.querySelector('parsererror') !== null, labels:Array.from(xml.querySelectorAll('text')).map(node => node.textContent) };
  });
  expect(report.width).toBe(Math.round(report.cssWidth * 1.25));
  expect(report.invalid).toBe(false);
  expect(report.svg).not.toMatch(/NaN|Infinity/);
  expect(report.labels).toContain('Volume');
  expect(report.labels).toContain('Delta');
  const stage = await page.locator('#chart').boundingBox();
  await page.mouse.move(stage!.x + 450,stage!.y + 160);
  await page.mouse.down();
  await page.mouse.move(stage!.x + 540,stage!.y + 160,{ steps:6 });
  await page.mouse.up();
  expect(await page.evaluate(() => JSON.stringify((window as any).__orderflowData()))).toBe(before);
  await page.setViewportSize({ width:390,height:844 });
  await paint(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.locator('#theme')).toBeVisible();
  const mobile = await pixels(page);
  expect(mobile.red + mobile.green).toBeGreaterThan(200);
  await page.screenshot({ path:'artifacts/orderflow-mobile-ocean.png' });
  expect(errors).toEqual([]);
  await context.close();
});

test('optional table remembers row choices and aligns all seven metrics with the NIFTY footprint bars', async ({ page }) => {
  await page.setViewportSize({ width:1440,height:960 });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await openDemo(page);
  const rows = ['delta','minDelta','maxDelta','cvd','askVolume','bidVolume','volume'];
  const options = () => page.evaluate(() => (window as any).__footprint().options());
  await expect(page.locator('#table')).not.toBeChecked();
  expect((await options()).tableRows).toEqual([]);
  await expect(page.locator('#group')).toHaveValue('2');
  await expect(page.locator('#instrument-note')).toContainText('NIFTY simulation');
  const baseline = await page.evaluate(() => JSON.stringify((window as any).__orderflowData()));
  await page.locator('#table-options summary').click();
  await page.locator('input[name="table-row"][value="minDelta"]').uncheck();
  await page.locator('input[name="table-row"][value="askVolume"]').uncheck();
  expect((await options()).tableRows).toEqual([]);
  await page.getByRole('button', { name:'Done',exact:true }).click();
  await page.locator('#table').check();
  expect((await options()).tableRows).toEqual(rows.filter(row => !['minDelta','askVolume'].includes(row)));
  expect((await options()).statsRows).toEqual(['volume','delta','deltaPct']);
  await page.locator('#table-options summary').click();
  for (const row of rows) await page.locator(`input[name="table-row"][value="${row}"]`).check();
  await page.getByRole('button', { name:'Done',exact:true }).click();
  await paint(page);
  const rendered = await page.evaluate(() => {
    const chart = (window as any).__chart(), fp = (window as any).__footprint();
    const width = chart.timeScale.width, height = chart.panes()[0].priceScale.height;
    const xml = new DOMParser().parseFromString(chart.exportSVG(),'image/svg+xml');
    const texts = Array.from(xml.querySelectorAll('text')).map(node => ({
      text:node.textContent, x:Number(node.getAttribute('x')),y:Number(node.getAttribute('y')),
    })).filter(node => node.y > height - 7 * 19 && node.y < height && node.x < width);
    const centers = (window as any).__orderflowData().bars.map((bar: any,index: number) => ({
      x:chart.timeScale.indexToX(index),time:bar.time,
      hover:fp.hoverAt(chart.timeScale.indexToX(index),height - 10),
    }));
    return { texts,centers,labels:texts.filter(node => node.x < 150).map(node => node.text) };
  });
  expect(rendered.labels).toEqual(['Delta','Min Delta','Max Delta','Cumulative Delta','Total Ask Volume','Total Bid Volume','Total Volume']);
  for (const center of rendered.centers) {
    expect(center.x).toBeGreaterThan(150);
    expect(center.hover.time).toBe(center.time);
    expect(center.hover.cell).toBeNull();
    expect(rendered.texts.filter(node => Math.abs(node.x - center.x) < 0.01)).toHaveLength(7);
  }
  expect(await page.evaluate(() => JSON.stringify((window as any).__orderflowData()))).toBe(baseline);
  await page.screenshot({ path:'artifacts/orderflow-nifty-table-midnight.png' });
  const range = await page.evaluate(() => (window as any).__chart().timeScale.visibleRange());
  await page.locator('#theme').selectOption('ivory');
  expect(await page.evaluate(() => (window as any).__chart().timeScale.visibleRange())).toEqual(range);
  await paint(page);
  await page.screenshot({ path:'artifacts/orderflow-nifty-table-ivory.png' });
  await page.locator('#table-options summary').click();
  for (const row of rows) await page.locator(`input[name="table-row"][value="${row}"]`).uncheck();
  expect((await options()).tableRows).toEqual([]);
  expect((await options()).statsRows).toHaveLength(3);
  await expect(page.locator('#table-count')).toHaveText('0');
  await page.locator('input[name="table-row"][value="delta"]').check();
  await page.getByRole('button', { name:'Done',exact:true }).click();
  await page.locator('#table').uncheck();
  expect((await options()).tableRows).toEqual([]);
  await page.locator('#table').check();
  expect((await options()).tableRows).toEqual(['delta']);
  expect(errors).toEqual([]);
});

test('table replay reports execution delta extremes and remains usable on a narrow screen', async ({ page }) => {
  await openDemo(page,'&table=1&theme=classic&style=ladder');
  await expect(page.locator('#table')).toBeChecked();
  await page.evaluate(() => (window as any).__advanceTicks(25));
  const report = await page.evaluate(() => {
    const data = (window as any).__orderflowData();
    const stats = (window as any).__footprint().stats().at(-1);
    const tape = data.tape.filter((tick: any) => tick.time >= stats.time);
    let delta = 0,min = 0,max = 0,ask = 0,bid = 0;
    for (const tick of tape) {
      if (tick.side === 'ask') { delta += tick.qty; ask += tick.qty; }
      else { delta -= tick.qty; bid += tick.qty; }
      min = Math.min(min,delta); max = Math.max(max,delta);
    }
    return { stats,min,max,ask,bid };
  });
  expect(report.stats.minDelta).toBe(report.min);
  expect(report.stats.maxDelta).toBe(report.max);
  expect(report.stats.askVolume).toBe(report.ask);
  expect(report.stats.bidVolume).toBe(report.bid);
  await page.locator('#group').selectOption('4');
  expect(await page.evaluate(() => (window as any).__footprint().stats().at(-1))).toMatchObject({
    minDelta:report.min,maxDelta:report.max,askVolume:report.ask,bidVolume:report.bid,
  });
  await page.setViewportSize({ width:390,height:844 });
  await paint(page);
  await page.locator('#table-options summary').click();
  const chooser = await page.locator('#table-options fieldset').boundingBox();
  expect(chooser!.x).toBeGreaterThanOrEqual(0);
  expect(chooser!.x + chooser!.width).toBeLessThanOrEqual(390);
  await page.getByRole('button', { name:'Done',exact:true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator('#group').selectOption('2');
  await paint(page);
  const recentColumn = await page.evaluate(() => {
    const chart = (window as any).__chart();
    return chart.timeScale.indexToX((window as any).__orderflowData().bars.length - 1);
  });
  expect(recentColumn).toBeGreaterThan(150);
  await page.screenshot({ path:'artifacts/orderflow-nifty-table-mobile.png',fullPage:true });
});

test('raw and editable lot displays update cells, table and readouts without changing analytics or the viewport', async ({ page }) => {
  await page.setViewportSize({ width:1440,height:960 });
  await openDemo(page,'&table=1');
  const original = await page.evaluate(() => ({ data:JSON.stringify((window as any).__orderflowData()),
    stats:JSON.stringify((window as any).__footprint().stats()), range:(window as any).__chart().timeScale.visibleRange() }));
  await expect(page.locator('#units')).toHaveValue('raw');
  await expect(page.locator('#lot-size')).toHaveValue('65');
  expect(await page.evaluate(() => (window as any).__footprint().options().volumeDivisor)).toBe(1);
  const raw = await pixels(page);
  await page.locator('#units').selectOption('lots');
  expect(await page.evaluate(() => (window as any).__footprint().options().volumeDivisor)).toBe(65);
  const expectedVolume = await page.evaluate(() => String((window as any).__footprint().stats().at(-1).volume / 65));
  await expect(page.locator('#s-vol')).toHaveText(expectedVolume);
  await expect(page.locator('#volume-label')).toContainText('LOTS');
  const lots = await pixels(page);
  expect(lots.png).not.toBe(raw.png);
  await page.screenshot({ path:'artifacts/orderflow-nifty-table-lots.png' });
  await page.locator('#lot-size').fill('130');
  await page.locator('#lot-size').press('Tab');
  expect(await page.evaluate(() => (window as any).__footprint().options().volumeDivisor)).toBe(130);
  await expect(page.locator('#s-vol')).toHaveText(String(Number((Number(expectedVolume) / 2).toPrecision(3))));
  await page.locator('#lot-size').fill('0');
  await page.locator('#lot-size').press('Tab');
  await expect(page.locator('#lot-size')).toHaveAttribute('aria-invalid','true');
  expect(await page.evaluate(() => (window as any).__footprint().options().volumeDivisor)).toBe(130);
  await page.locator('#lot-size').fill('65');
  await page.locator('#lot-size').press('Tab');
  await page.locator('#units').selectOption('raw');
  expect(await page.evaluate(() => ({ data:JSON.stringify((window as any).__orderflowData()),
    stats:JSON.stringify((window as any).__footprint().stats()), range:(window as any).__chart().timeScale.visibleRange() }))).toEqual(original);
  expect((await pixels(page)).png).toBe(raw.png);
  await openDemo(page,'&units=lots&lot=65&table=1');
  await expect(page.locator('#units')).toHaveValue('lots');
  expect(await page.evaluate(() => (window as any).__footprint().options().volumeDivisor)).toBe(65);
  await openDemo(page,'&units=lots&lot=invalid');
  await expect(page.locator('#lot-size')).toHaveValue('65');
});

test('a narrow raw-quantity embed fits complete readable statistics cards', async ({ page }) => {
  await page.setViewportSize({ width:832,height:660 });
  await openDemo(page);
  await paint(page);
  const report = await page.evaluate(() => {
    const chart = (window as any).__chart();
    const xml = new DOMParser().parseFromString(chart.exportSVG(),'image/svg+xml');
    const width = chart.timeScale.width, spacing = chart.timeScale.barSpacing;
    const fullColumns = (window as any).__orderflowData().bars.filter((_: any,index: number) => {
      const x = chart.timeScale.indexToX(index);
      return x - spacing / 2 >= 0 && x + spacing / 2 <= width;
    }).length;
    const labels = Array.from(xml.querySelectorAll('text')).filter(node =>
      ['Volume','Delta','Delta %'].includes(node.textContent ?? '') &&
      Number(node.getAttribute('x')) >= 0 && Number(node.getAttribute('x')) <= width,
    ).map(node => ({ x:node.getAttribute('x'),text:node.textContent }));
    return { spacing,fullColumns,labels };
  });
  expect(report.spacing).toBeGreaterThanOrEqual(125);
  expect(report.fullColumns).toBeGreaterThanOrEqual(4);
  expect(report.fullColumns).toBeLessThan(7);
  expect(report.labels).toHaveLength(report.fullColumns * 3);
  for (const x of new Set(report.labels.map(label => label.x))) {
    expect(report.labels.filter(label => label.x === x).map(label => label.text)).toEqual(['Volume','Delta','Delta %']);
  }
  await page.screenshot({ path:'artifacts/orderflow-nifty-embed-raw.png' });
});
