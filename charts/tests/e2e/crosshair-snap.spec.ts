import { expect, test } from '@playwright/test';

test('candle-center snapping paints at the bar and preserves the actual pointer', async ({ page }, info) => {
  await page.goto('/tests/e2e/fixture.html');
  await page.waitForFunction(() => Boolean((window as any).__api?.chart));
  const position = await page.evaluate(() => {
    const { chart, bars } = (window as any).__api;
    chart.setVisibleLogicalRange({ from: 230, to: 302 });
    chart.applyOptions({ crosshairSnapToBar: true });
    chart.setCanvasOptions({ crosshair: { color: '#ff00ff', width: 1, style: 'solid' } });
    const pane = chart.panes()[0];
    const paint = pane.paintTop.bind(pane);
    pane.paintTop = (cross: unknown, context: unknown) => {
      (window as any).__lastCross = cross;
      return paint(cross, context);
    };
    chart.subscribeCrosshairMove((event: unknown) => { (window as any).__lastPointer = event; });
    const center = chart.timeToCoordinate(bars[270].time);
    const spacing = chart.timeToCoordinate(bars[271].time) - center;
    return { center, pointer: center + spacing * 0.35 };
  });
  await page.mouse.move(position.pointer, 140);
  await expect.poll(() => page.evaluate(() => (window as any).__lastCross?.x)).toBeCloseTo(position.center, 5);
  const pointer = await page.evaluate(() => (window as any).__lastPointer.point.x);
  expect(pointer).toBeCloseTo(position.pointer, 0);
  const ink = await page.evaluate((center: number) => {
    const chart = (window as any).__api.chart;
    const pane = chart.panes()[0];
    const canvases = Array.from(document.querySelectorAll('canvas'));
    let pixels = 0;
    for (const canvas of canvases) {
      const context = canvas.getContext('2d');
      if (!context) continue;
      const ratio = canvas.width / canvas.getBoundingClientRect().width;
      const x = Math.floor(center * ratio);
      const height = Math.min(canvas.height, Math.floor(100 * ratio));
      const data = context.getImageData(Math.max(0, x - 1), 15, 3, height).data;
      for (let i = 0; i < data.length; i += 4) {
        if (data[i] > 200 && data[i + 1] < 80 && data[i + 2] > 200 && data[i + 3] > 100) pixels++;
      }
    }
    return { pixels, validScale: Number.isFinite(pane.priceScale.priceToY(100)) };
  }, position.center);
  expect(ink.pixels).toBeGreaterThan(30);
  expect(ink.validScale).toBe(true);
  const screenshot = info.outputPath('candle-center-crosshair.png');
  await page.screenshot({ path: screenshot });
  await info.attach('candle-center crosshair', { path: screenshot, contentType: 'image/png' });
  await page.evaluate(() => (window as any).__api.chart.applyOptions({ crosshairSnapToBar: false }));
  await expect.poll(() => page.evaluate(() => (window as any).__lastCross?.x)).toBeCloseTo(pointer, 5);
});
