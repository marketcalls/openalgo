import { test, expect, type Page } from '@playwright/test';

test.use({ hasTouch: true, deviceScaleFactor: 2 });

async function ready(page: Page, query = '') {
  await page.goto(`/tests/e2e/branding-watermark-fixture.html${query}`);
  await page.waitForFunction(() => (window as any).__ready);
}

async function brandPixels(page: Page) {
  return page.evaluate(async () => {
    const { chart } = (window as any).__probe;
    await (window as any).__frame();
    const before = chart.takeScreenshot();
    const a = before.getContext('2d').getImageData(0, 0, before.width, before.height).data;
    const enabled = chart.brandingOptions();
    chart.setBranding(false);
    await (window as any).__frame();
    const after = chart.takeScreenshot();
    const b = after.getContext('2d').getImageData(0, 0, after.width, after.height).data;
    let count = 0, minX = before.width, minY = before.height, maxX = -1, maxY = -1;
    for (let i = 0; i < a.length; i += 4) {
      if (a[i] === b[i] && a[i + 1] === b[i + 1] && a[i + 2] === b[i + 2] && a[i + 3] === b[i + 3]) continue;
      const x = (i / 4) % before.width, y = Math.floor(i / 4 / before.width);
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y); count++;
    }
    chart.setBranding(enabled);
    await (window as any).__frame();
    return { count, minX, minY, maxX, maxY, width: before.width, height: before.height };
  });
}

for (const theme of ['dark', 'light']) {
  test(`default logo renders in ${theme} desktop and phone charts and exported images`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width: 1100, height: 720 });
    await ready(page, `?theme=${theme}`);
    for (const [width, height] of [[1100, 720], [390, 740], [740, 390]]) {
      await page.setViewportSize({ width, height });
      await page.waitForFunction(({ width, height }) => {
        const canvas = (window as any).__probe.chart.panes()[0].base.element;
        return canvas.width === width * devicePixelRatio && canvas.height === height * devicePixelRatio;
      }, { width, height });
      const pixels = await brandPixels(page);
      expect(pixels.count).toBeGreaterThan(150);
      expect(pixels.minX).toBeGreaterThanOrEqual(0);
      expect(pixels.maxX).toBeLessThan(150);
      expect(pixels.minY).toBeGreaterThan(pixels.height - 200);
      expect(pixels.maxY).toBeLessThan(pixels.height - 20);
      await info.attach(`${theme} ${width}x${height}`, { body: await page.screenshot(), contentType: 'image/png' });
    }
    const svg = await page.evaluate(() => {
      const { chart } = (window as any).__probe;
      const on = chart.exportSVG();
      chart.setBranding(false);
      const off = chart.exportSVG();
      return { on, off, visible: chart.watermarkOptions().visible };
    });
    expect(svg.on).not.toBe(svg.off);
    expect(svg.on).not.toContain('NaN');
    expect(svg.on).not.toContain('<image');
    expect(svg.visible).toBe(false);
    expect(errors).toEqual([]);
  });
}

test('watermark settings start off and opt in through the actual widget dialog', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 740 });
  await ready(page, '?widget');
  expect(await page.evaluate(() => (window as any).__probe.lib.readChartSettings((window as any).__probe.chart)['watermark.visible'])).toBe(false);
  await page.evaluate(() => (window as any).__probe.widget.openSettings());
  await page.getByRole('tab', { name: 'Appearance', exact: true }).click();
  const show = page.getByRole('checkbox', { name: /watermark/i });
  await expect(show).not.toBeChecked();
  await show.check();
  expect(await page.evaluate(() => (window as any).__probe.chart.exportSVG())).toContain('NIFTY SIM');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__probe.chart.watermarkOptions().visible)).toBe(false);
  await page.evaluate(() => (window as any).__probe.widget.openSettings());
  await page.getByRole('tab', { name: 'Appearance', exact: true }).click();
  await show.check();
  await page.getByRole('button', { name: 'OK', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__probe.chart.watermarkOptions().visible)).toBe(true);
  await info.attach('phone watermark enabled', { body: await page.screenshot(), contentType: 'image/png' });
});

test('automatic text follows context and restored preferences keep custom text separate', async ({ page }) => {
  await ready(page, '?widget');
  const result = await page.evaluate(() => {
    const { chart, widget, lib } = (window as any).__probe;
    const initial = chart.getState();
    lib.applyChartSettings(chart, { 'watermark.visible': true });
    const first = chart.exportSVG();
    widget.setSymbol('BANK SIM');
    widget.setInterval('15m');
    const second = chart.exportSVG();
    const automatic = JSON.parse(JSON.stringify(chart.getState()));
    chart.setWatermarkOptions({ text: 'Research' });
    const custom = chart.exportSVG();
    chart.setDataContext({ symbol: 'THIRD SIM', interval: '1h' });
    const retained = chart.exportSVG();
    chart.restoreState(automatic);
    const restored = chart.exportSVG();
    chart.restoreState(initial);
    const disabled = chart.watermarkOptions().visible;
    return { first, second, custom, retained, restored, disabled };
  });
  expect(result.first).toContain('NIFTY SIM');
  expect(result.second).toContain('BANK SIM');
  expect(result.second).toContain('15m');
  expect(result.custom).toContain('Research');
  expect(result.retained).toContain('Research');
  expect(result.restored).toContain('THIRD SIM');
  expect(result.restored).not.toContain('Research');
  expect(result.disabled).toBe(false);
});

test('mobile branding link follows chart configuration and remains keyboard accessible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 740 });
  await ready(page, '?widget');
  await page.getByRole('button', { name: 'More', exact: true }).click();
  const link = page.getByRole('link', { name: 'Chart by OpenAlgo', exact: true });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await link.focus();
  await expect(link).toBeFocused();
  await page.evaluate(() => (window as any).__probe.chart.setBranding(false));
  await expect(link).toHaveCount(0);
  await page.evaluate(() => (window as any).__probe.chart.setBranding({ label: 'Research charts', href: 'https://example.com/charts' }));
  const custom = page.getByRole('link', { name: 'Research charts', exact: true });
  await expect(custom).toBeVisible();
  await expect(custom).toHaveAttribute('href', 'https://example.com/charts');
  await page.evaluate(() => (window as any).__probe.chart.setBranding({ href: 'javascript:void(0)' }));
  await expect(custom).toHaveCount(0);
});

test('a pinch started on branding never creates drawing anchors after either finger releases', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 740 });
  await ready(page);
  const pixels = await brandPixels(page);
  const point = { x: (pixels.minX + pixels.maxX) / 4, y: (pixels.minY + pixels.maxY) / 4 };
  for (const order of [[11, 12], [12, 11]]) {
    await page.evaluate(({ point, order }) => {
      const { chart } = (window as any).__probe;
      chart.setPlacementMode(true);
      const host = document.getElementById('chart')!;
      function pointer(type: string, id: number) {
        host.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId: id, pointerType: 'touch',
          isPrimary: id === 11, button: 0, buttons: type === 'pointerup' ? 0 : 1,
          clientX: id === 11 ? point.x : 230, clientY: id === 11 ? point.y : 300 }));
      }
      pointer('pointerdown', 11);
      pointer('pointerdown', 12);
      pointer('pointerup', order[0]);
      pointer('pointerup', order[1]);
    }, { point, order });
    expect(await page.evaluate(() => (window as any).__opened)).toHaveLength(0);
    expect(await page.evaluate(() => (window as any).__clicks)).toHaveLength(0);
  }
  await page.touchscreen.tap(100, 220);
  expect((await page.evaluate(() => (window as any).__clicks)).length).toBeGreaterThan(0);
});

test('logo taps open once, while drags and drawing placement remain isolated', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 740 });
  await ready(page);
  const pixels = await brandPixels(page);
  const point = { x: (pixels.minX + pixels.maxX) / 4, y: (pixels.minY + pixels.maxY) / 4 };
  await page.touchscreen.tap(point.x, point.y);
  const opened = await page.evaluate(() => (window as any).__opened);
  expect(opened).toHaveLength(1);
  expect(opened[0][0]).toMatch(/^https:\/\/openalgo\.in/);
  expect(opened[0][2]).toContain('noopener');
  expect(await page.evaluate(() => (window as any).__clicks)).toHaveLength(0);
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.mouse.move(point.x + 100, point.y - 60, { steps: 8 });
  await page.mouse.up();
  expect(await page.evaluate(() => (window as any).__opened)).toHaveLength(1);
  await page.evaluate(() => (window as any).__probe.draw.setTool('trend-line'));
  await page.touchscreen.tap(point.x, point.y);
  expect(await page.evaluate(() => (window as any).__probe.draw.drawings())).toHaveLength(0);
  await page.touchscreen.tap(100, 220);
  await page.touchscreen.tap(240, 320);
  expect(await page.evaluate(() => (window as any).__probe.draw.drawings())).toHaveLength(1);
  expect(await page.evaluate(() => (window as any).__orders)).toHaveLength(0);
});

test('branding follows visible panes and watermark pixels stay clear of both price axes', async ({ page }, info) => {
  await page.setViewportSize({ width: 740, height: 390 });
  await ready(page);
  await page.evaluate(() => {
    const { chart, bars } = (window as any).__probe;
    chart.addSeries('line', { paneIndex: 1 }).setData(bars);
    chart.maximizePane(1);
  });
  const maximized = await brandPixels(page);
  expect(maximized.count).toBeGreaterThan(150);
  expect(maximized.minY).toBeGreaterThan(maximized.height - 200);
  await page.evaluate(() => {
    const { chart, bars } = (window as any).__probe;
    chart.maximizePane(0);
    chart.addSeries('line', { priceScaleId: 'left' }).setData(bars);
    chart.setWatermarkOptions({ visible: true, text: 'A very long research watermark across the full plot', fontSize: 150, opacity: 0.35 });
  });
  await page.evaluate(() => (window as any).__frame());
  const bounds = await page.evaluate(async () => {
    const { chart } = (window as any).__probe;
    const a = chart.takeScreenshot();
    const before = a.getContext('2d').getImageData(0, 0, a.width, a.height).data;
    chart.setWatermarkOptions(false);
    await (window as any).__frame();
    const b = chart.takeScreenshot().getContext('2d').getImageData(0, 0, a.width, a.height).data;
    let minX = a.width, maxX = -1, count = 0;
    for (let i = 0; i < before.length; i += 4) {
      if (before[i] === b[i] && before[i + 1] === b[i + 1] && before[i + 2] === b[i + 2]) continue;
      const x = (i / 4) % a.width; minX = Math.min(minX, x); maxX = Math.max(maxX, x); count++;
    }
    chart.setWatermarkOptions(true);
    return { minX, maxX, count, width: a.width };
  });
  expect(bounds.count).toBeGreaterThan(100);
  expect(bounds.minX).toBeGreaterThan(100);
  expect(bounds.maxX).toBeLessThan(bounds.width - 100);
  await info.attach('maximized pane with long watermark', { body: await page.screenshot(), contentType: 'image/png' });
});

test('the standalone profile example draws histogram bars as well as default branding', async ({ page }) => {
  await page.goto('/examples/phase11-profiles.html');
  await page.waitForFunction(() => (window as any).__chart);
  for (const [kind, colors] of [
    ['Volume Profile', ['rgba(90,110,150,0.5)', 'rgba(120,150,200,0.6)']],
  ] as const) {
    await page.locator('#kind').selectOption(kind);
    const output = await page.evaluate((colors) => {
      const chart = (window as any).__chart;
      const svg = new DOMParser().parseFromString(chart.exportSVG(), 'image/svg+xml');
      const bars = [...svg.querySelectorAll('rect')].filter(rect => colors.some(color => color === rect.getAttribute('fill')));
      return {
        widths: bars.map(rect => Number(rect.getAttribute('width'))),
        branding: chart.brandingOptions(), watermark: chart.watermarkOptions(),
      };
    }, [...colors]);
    expect(output.widths.length).toBeGreaterThan(5);
    expect(output.widths.every(width => Number.isFinite(width) && width > 0)).toBe(true);
    expect(output.branding).not.toBe(false);
    expect(output.watermark.visible).toBe(false);
  }
});


test('the standalone profile selector displays actual TPO letters', async ({ page }, info) => {
  await page.goto('/examples/phase11-profiles.html');
  await page.locator('#kind').selectOption('Market Profile (TPO)');
  const demo = page.frameLocator('#profile-demo');
  await expect(demo.locator('#block')).toHaveValue('compact');
  await demo.locator('#comfortable').click();
  await demo.locator('#block').selectOption('letters');
  const frame = page.frames().find(frame => frame.url().includes('/market-profile/index.html'))!;
  await expect.poll(() => frame.evaluate(() => {
    const svg = new DOMParser().parseFromString((window as any).__chart().exportSVG(), 'image/svg+xml');
    return [...svg.querySelectorAll('text')].filter(node => /^[A-Z]$/.test(node.textContent ?? '')).length;
  })).toBeGreaterThan(50);
  await info.attach('standalone TPO letters', { body: await page.screenshot(), contentType: 'image/png' });
  await page.locator('#kind').selectOption('Volume Profile');
  await expect(page.locator('#profile-demo')).toHaveCount(0);
  await expect(page.locator('#chart canvas').first()).toBeVisible();
});

test('the standalone profile selector displays current orderflow values and optional metrics', async ({ page }, info) => {
  await page.goto('/examples/phase11-profiles.html');
  await page.locator('#kind').selectOption('Footprint');
  const demo = page.frameLocator('#profile-demo');
  await expect(demo.locator('#style')).toHaveValue('profile');
  await expect(demo.locator('#s-vol')).toHaveText(/[1-9]/);
  await expect(demo.locator('#table')).not.toBeChecked();
  await demo.locator('#play').click();
  const frame = page.frames().find(frame => frame.url().includes('/orderflow/index.html'))!;
  await expect.poll(() => frame.evaluate(() => {
    const svg = new DOMParser().parseFromString((window as any).__chart().exportSVG(), 'image/svg+xml');
    return [...svg.querySelectorAll('text')].filter(node => /^\d+$/.test(node.textContent ?? '')).length;
  })).toBeGreaterThan(20);
  await demo.locator('#table').check();
  await demo.locator('#units').selectOption('lots');
  await demo.locator('#style').selectOption('ladder');
  await demo.locator('#theme').selectOption('classic');
  await demo.locator('#text').selectOption('imbalance');
  const rendered = await frame.evaluate(() => ({
    svg: (window as any).__chart().exportSVG(),
    options: (window as any).__footprint().options(),
  }));
  expect(rendered.options.tableRows).toEqual(['delta', 'minDelta', 'maxDelta', 'cvd', 'askVolume', 'bidVolume', 'volume']);
  expect(rendered.options.volumeDivisor).toBe(65);
  expect(rendered.svg).toContain('Min Delta');
  expect(rendered.svg).toContain('Max Delta');
  expect(rendered.svg).not.toContain('NaN');
  const coveredTablePixels = await frame.evaluate(async () => {
    const chart = (window as any).__chart();
    const branding = chart.brandingOptions();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const before = chart.takeScreenshot();
    const a = before.getContext('2d').getImageData(0, 0, before.width, before.height).data;
    chart.setBranding(false);
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const after = chart.takeScreenshot();
    const b = after.getContext('2d').getImageData(0, 0, after.width, after.height).data;
    const rows = (window as any).__footprint().options().tableRows.length;
    const yStart = Math.floor((chart.panes()[0].base.element.clientHeight - 22 - rows * 19) * devicePixelRatio);
    let covered = 0;
    for (let i = Math.max(0, yStart) * before.width * 4; i < a.length; i += 4) {
      if (a[i] !== b[i] || a[i + 1] !== b[i + 1] || a[i + 2] !== b[i + 2]) covered++;
    }
    chart.setBranding(branding);
    return covered;
  });
  expect(coveredTablePixels).toBe(0);
  await info.attach('standalone orderflow values and table', { body: await page.screenshot(), contentType: 'image/png' });
});

for (const [width, height] of [[1100, 720], [390, 740]]) {
  test(`a note pinned over the corner mark takes its presses at ${width}px, and the bare mark still links`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height });
    await ready(page);
    const pixels = await brandPixels(page);
    const mark = { x: (pixels.minX + pixels.maxX) / 4, y: (pixels.minY + pixels.maxY) / 4 };
    const id = await page.evaluate(mark => {
      const { chart, draw } = (window as any).__probe;
      const rect = chart.plotRect(0);
      // The note's box starts a little up and left of the mark and covers it.
      return draw.add({ tool: 'text', paneIndex: 0, points: [], space: 'viewport', style: {},
        viewportPoints: [{ x: (mark.x - rect.left - 10) / rect.width, y: (mark.y - rect.top - 10) / rect.height }],
        text: { value: 'Pinned over the corner', fontSize: 16, background: true, backgroundColor: '#334155' } }).id;
    }, mark);
    await (page.evaluate(() => (window as any).__frame()));
    await page.screenshot({ path: info.outputPath(`note-over-mark-${width}.png`) });
    const anchor = () => page.evaluate(noteId => (window as any).__probe.draw.get(noteId).viewportPoints[0], id);
    const before = await anchor();
    // A tap selects the note instead of opening the link.
    await page.touchscreen.tap(mark.x, mark.y);
    expect(await page.evaluate(() => (window as any).__opened)).toHaveLength(0);
    expect(await page.evaluate(() => (window as any).__probe.draw.selection())).toEqual([id]);
    // A drag moves it.
    await page.mouse.move(mark.x, mark.y);
    await page.mouse.down();
    await page.mouse.move(mark.x + 90, mark.y - 70, { steps: 8 });
    await page.mouse.up();
    const after = await anchor();
    expect(after.x).toBeGreaterThan(before.x);
    expect(after.y).toBeLessThan(before.y);
    expect(await page.evaluate(() => (window as any).__opened)).toHaveLength(0);
    await page.mouse.move(2, 2);
    await (page.evaluate(() => (window as any).__frame()));
    await page.screenshot({ path: info.outputPath(`note-moved-off-mark-${width}.png`) });
    // With the note moved away the mark is bare, and a tap on it links again.
    await page.touchscreen.tap(mark.x, mark.y);
    expect(await page.evaluate(() => (window as any).__opened)).toHaveLength(1);
    expect(errors).toEqual([]);
  });
}
