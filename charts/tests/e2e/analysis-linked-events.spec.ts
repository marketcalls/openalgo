import { expect, test, type Page } from '@playwright/test';

async function mount(page: Page) {
  await page.setViewportSize({ width: 1280, height: 760 });
  await page.goto('/tests/e2e/analysis-linked-events-fixture.html');
  await page.waitForFunction(() => !!(window as any).analysis252);
}
async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

test('reference host preserves linked drawings across interval rebuilds and removes old instrument copies', async ({ page, request }) => {
  const base = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;
  const up = await request.get(base + '/api/history?symbol=AAPL&interval=1d&period=1mo').then(r => r.ok(), () => false);
  test.skip(!up, 'Reference fixture server needs Python 3');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(base + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  const before = await page.evaluate(async () => {
    const { app } = (window as any).__oac;
    const path = '/examples/yfinance/src/split.js';
    const { openSplit } = await import(path);
    app.p2.symbol = app.req.symbol;
    app.p2.interval = '5m'; app.p2.period = '1d';
    await openSplit();
    app.drawingLinkGroup.setOptions({enabled:true});
    const bar = app.chart.primaryBars()[10];
    const drawing = app.draw.add({tool:'horizontal-line',paneIndex:0,style:{color:'#123456'},points:[{time:bar.time,price:bar.close}]});
    app.p2.interval='15m';
    await app.loadSecondary();
    app.draw.update(drawing.id,{style:{color:'#abcdef'}});
    return {count:app.draw2.drawings().length,color:app.draw2.drawings()[0]?.style.color,
      exchange:app.chart.getDataContext().exchange};
  });
  expect(before).toEqual({count:1,color:'#abcdef',exchange:undefined});
  const remaining = await page.evaluate(async () => {
    const { app } = (window as any).__oac;
    app.p2.symbol='OTHER';
    await app.loadSecondary();
    return {source:app.draw.drawings().length,follower:app.draw2.drawings().length};
  });
  expect(remaining).toEqual({source:1,follower:0});
  expect(errors).toEqual([]);
});

test('volume studies place through pointer input, synchronize and undo', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page);
  for (const [tool, indices] of [['anchored-vwap', [20]], ['fixed-range-volume-profile', [45, 85]]] as const) {
    const points = await page.evaluate(({ tool, indices }) => {
      const { first, bars } = (window as any).analysis252;
      first.draw.setTool(tool);
      const rect = document.querySelector('#first .oac-chart')!.getBoundingClientRect();
      return indices.map(i => ({ x: rect.left + first.chart.timeToCoordinate(bars[i].time),
        y: rect.top + first.chart.priceToCoordinate(bars[i].close) }));
    }, { tool, indices: [...indices] });
    for (const point of points) await page.mouse.click(point.x, point.y);
    await settle(page);
    const state = await page.evaluate(() => {
      const { first, second } = (window as any).analysis252;
      return { a: first.draw.drawings(), b: second.draw.drawings() };
    });
    expect(state.a.some((drawing: any) => drawing.tool === tool)).toBe(true);
    expect(state.b.map((drawing: any) => ({ tool: drawing.tool, points: drawing.points })))
      .toEqual(state.a.map((drawing: any) => ({ tool: drawing.tool, points: drawing.points })));
  }
  await page.screenshot({ path: info.outputPath('linked-volume-studies.png') });
  expect(await page.evaluate(() => (window as any).analysis252.first.draw.undo())).toBe(true);
  expect(await page.evaluate(() => (window as any).analysis252.second.draw.drawings().length)).toBe(1);
  await page.evaluate(() => (window as any).analysis252.first.draw.redo());
  expect(await page.evaluate(() => (window as any).analysis252.second.draw.drawings().length)).toBe(2);
  expect(errors).toEqual([]);
});

test('appearance follows independently and drawing sync stops across instruments', async ({ page }) => {
  await mount(page);
  const result = await page.evaluate(() => {
    const { first, second, bars, applyChartSettings, readChartSettings } = (window as any).analysis252;
    applyChartSettings(first.chart, { 'symbol.upColor':'#abcdef', 'time.timezone':'UTC' });
    second.chart.setDataContext({symbol:'OTHER',exchange:'DEMO',interval:'1m'});
    first.draw.add({tool:'horizontal-line',paneIndex:0,style:{},points:[{time:bars[20].time,price:100}]});
    return {color:readChartSettings(second.chart)['symbol.upColor'], timezone:second.chart.timezone(), drawings:second.draw.drawings().length};
  });
  expect(result).toEqual({color:'#abcdef',timezone:'Asia/Kolkata',drawings:0});
});

test('cluster clicks open safe details and ancestor filters remove the marker', async ({ page }, info) => {
  await mount(page);
  await settle(page);
  const point = await page.evaluate(() => {
    const { first } = (window as any).analysis252;
    const rect = document.querySelector('#first .oac-chart')!.getBoundingClientRect();
    const markers = first.chart.eventMarkers();
    for (let y = rect.height - 60; y < rect.height; y++) {
      for (let x = 0; x < rect.width; x++) {
        const hit = markers.hitTest(x,y);
        if (hit && markers.detailsForHit(hit.externalId)?.events.length === 2) return {x:rect.left+x,y:rect.top+y};
      }
    }
    return null;
  });
  expect(point).not.toBeNull();
  await page.mouse.click(point!.x, point!.y);
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Sample results');
  await expect(dialog).toContainText('Sample call');
  await page.screenshot({ path: info.outputPath('timeline-details.png') });
  await dialog.getByRole('button', { name: 'Sample call', exact: true }).click();
  await expect(dialog).toContainText('<script>Untrusted text</script>');
  await expect(dialog.locator('script')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await page.evaluate(() => (window as any).analysis252.first.chart.setEventGroupVisible('company',false));
  await settle(page);
  const hit = await page.evaluate(point => {
    const rect = document.querySelector('#first .oac-chart')!.getBoundingClientRect();
    return (window as any).analysis252.first.chart.eventMarkers().hitTest(point.x-rect.left,point.y-rect.top);
  }, point!);
  expect(hit).toBeNull();
});
