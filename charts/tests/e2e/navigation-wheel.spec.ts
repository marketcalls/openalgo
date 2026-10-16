import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.goto('/tests/e2e/navigation-wheel-fixture.html');
  await page.waitForFunction(() => (window as any).ready && (window as any).chart.panes()[0].priceScale.scaled);
});

test('horizontal dragging with slight vertical drift keeps the visible prices fitted', async ({ page }, info) => {
  await page.mouse.move(500, 280);
  await page.mouse.down();
  await page.mouse.move(610, 281, { steps: 5 });
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => (window as any).chart.panes()[0].priceScale.autoScale)).toBe(true);
  await expect.poll(() => page.evaluate(() => (window as any).chart.panes()[0].priceScale.priceRange().max)).toBeCloseTo(24251.25, 2);
  await info.attach('autofit after horizontal drag', {
    body: await page.screenshot({ path: info.outputPath('autofit-drag.png') }), contentType: 'image/png',
  });
});

test('holding the plot grabs both axes and release stops all mouse movement', async ({ page }, info) => {
  const host = page.locator('#chart');
  const state = () => page.evaluate(() => {
    const chart = (window as any).chart;
    return { offset: chart.timeScale.rightOffset, range: { ...chart.panes()[0].priceScale.priceRange() } };
  });
  await page.mouse.move(500, 280);
  await expect(host).not.toHaveCSS('cursor', 'grabbing');
  for (const [dx, dy] of [[70, 45], [-70, -45], [70, -45], [-70, 45]]) {
    const before = await state();
    await page.mouse.down();
    await expect(host).toHaveCSS('cursor', 'grabbing');
    await page.mouse.move(500 + dx, 280 + dy, { steps: 3 });
    const held = await state();
    expect((before.offset - held.offset) * dx).toBeGreaterThan(0);
    expect((held.range.min - before.range.min) * dy).toBeGreaterThan(0);
    await page.mouse.up();
    await expect(host).not.toHaveCSS('cursor', 'grabbing');
    const released = await state();
    await page.mouse.move(500, 280);
    await page.waitForTimeout(250);
    expect(await state()).toEqual(released);
  }
  await info.attach('plot after drag release', { body: await page.screenshot(), contentType: 'image/png' });
});

test('release outside the plot and lost capture cannot leave a mouse pan active', async ({ page }) => {
  const host = page.locator('#chart');
  await host.evaluate(el => {
    el.style.width = '900px'; el.style.height = '500px';
    el.addEventListener('pointerdown', e => { (window as any).heldPointer = (e as PointerEvent).pointerId; });
  });
  await page.waitForFunction(() => (window as any).chart.timeScale.width < 900);
  for (const end of ['outside', 'capture', 'cancel']) {
    await page.mouse.move(400, 240);
    await page.mouse.down();
    await page.mouse.move(460, 270);
    await expect(host).toHaveCSS('cursor', 'grabbing');
    if (end === 'outside') {
      await page.mouse.move(1050, 600);
      await page.mouse.up();
    } else {
      await host.evaluate((el, kind) => {
        const pointerId = (window as any).heldPointer;
        if (kind === 'capture') el.releasePointerCapture(pointerId);
        else el.dispatchEvent(new PointerEvent('pointercancel', { pointerId, pointerType: 'mouse', clientX: 460, clientY: 270 }));
      }, end);
      // Browsers process pending capture changes before the next pointer event.
      await page.mouse.move(470, 275);
    }
    await expect(host).not.toHaveCSS('cursor', 'grabbing');
    const stopped = await page.evaluate(() => (window as any).chart.timeScale.rightOffset);
    await page.mouse.move(520, 320);
    await page.mouse.up();
    await page.waitForTimeout(200);
    expect(await page.evaluate(() => (window as any).chart.timeScale.rightOffset)).toBe(stopped);
  }
});

test('trackpad magnitude, horizontal pan and price-axis wheel stay independent', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const chart = (window as any).chart;
    const host = document.getElementById('chart')!;
    const wheel = (x: number, dx: number, dy: number) => host.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX: x, clientY: 200, deltaX: dx, deltaY: dy }));
    const before = chart.timeScale.barSpacing;
    wheel(400, 0, -1);
    await new Promise(r => setTimeout(r, 450));
    const tiny = chart.timeScale.barSpacing / before;
    const from = chart.getVisibleLogicalRange().from;
    const spacing = chart.timeScale.barSpacing;
    wheel(400, 80, 0);
    await new Promise(r => setTimeout(r, 450));
    const pan = { spacing: chart.timeScale.barSpacing, from: chart.getVisibleLogicalRange().from };
    const scale = chart.panes()[0].priceScale;
    const span = scale.priceRange().max - scale.priceRange().min;
    const price = scale.yToPrice(200);
    wheel(1190, 0, -100);
    await new Promise(r => setTimeout(r, 100));
    return { tiny, from, spacing, pan, axisSpacing: chart.timeScale.barSpacing, axisSpan: scale.priceRange().max - scale.priceRange().min, span, priceY: scale.priceToY(price) };
  });
  expect(result.tiny).toBeCloseTo(1.0009535561, 8);
  expect(result.pan.spacing).toBe(result.spacing);
  expect(result.pan.from).toBeGreaterThan(result.from);
  expect(result.axisSpacing).toBe(result.spacing);
  expect(result.axisSpan).toBeLessThan(result.span);
  expect(result.priceY).toBeCloseTo(200, 7);
});

test('a newly visible extreme eases on canvas and settles on the full price range', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  const samples = await page.evaluate(async () => {
    const chart = (window as any).chart;
    const values = [chart.priceToCoordinate(23800)];
    document.getElementById('chart')!.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX: 1130, clientY: 200, deltaY: 100 }));
    const started = performance.now();
    while (performance.now() - started < 1000) {
      await new Promise(requestAnimationFrame);
      values.push(chart.priceToCoordinate(23800));
    }
    return { values, range: chart.panes()[0].priceScale.priceRange() };
  });
  const travel = Math.abs(samples.values.at(-1)! - samples.values[0]);
  const steps = samples.values.slice(1).map((y, i) => Math.abs(y - samples.values[i]));
  expect(travel).toBeGreaterThan(100);
  expect(Math.max(...steps)).toBeLessThan(travel * 0.5);
  expect(samples.range).toEqual({ min: 23738.75, max: 24251.25 });
  expect(errors).toEqual([]);
  await info.attach('settled price transition', { body: await page.screenshot(), contentType: 'image/png' });
});
