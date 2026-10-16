import { test, expect, type Page } from '@playwright/test';

async function ready(page: Page) {
  await page.goto('/tests/e2e/table-layout-fixture.html');
  await page.waitForFunction(() => (window as any).__ready);
}

async function measuredBounds(page: Page, id: string, fonts: number[][]) {
  return page.evaluate(({ id, fonts }) => {
    const { entries, dpr, margin } = (window as any).__tableLayout;
    const { canvas, ctx, table, rows } = entries[id];
    const reference = document.createElement('canvas').getContext('2d')!;
    const columns = Math.max(...rows.map((row: unknown[]) => row.length));
    let mediaWidth = 0;
    for (let c = 0; c < columns; c++) {
      let widest = 0;
      for (let r = 0; r < rows.length; r++) {
        const cell = rows[r][c];
        if (!cell || cell.text === '') continue;
        reference.font = `${cell.bold ? '600 ' : ''}${fonts[r][c]}px system-ui, sans-serif`;
        widest = Math.max(widest, reference.measureText(cell.text).width / dpr);
      }
      mediaWidth += Math.max(28, widest + 10);
    }
    // Sample the top background row, clear of the glyphs, to read the actual
    // painted width without intercepting or replacing any canvas operations.
    const scan = ctx.getImageData(0, Math.round(margin * dpr), canvas.width, 1).data;
    let left = -1, right = -1;
    for (let x = 0; x < canvas.width; x++) {
      if (scan[x * 4] === 34 && scan[x * 4 + 1] === 51 && scan[x * 4 + 2] === 68 && scan[x * 4 + 3] === 255) {
        if (left < 0) left = x;
        right = x;
      }
    }
    return {
      dpr, actualWidth: right - left + 1, expectedWidth: Math.round(mediaWidth * dpr),
      left, expectedLeft: Math.round(margin * dpr),
      inside: table.hitTest(margin + mediaWidth - 0.01, margin + 1)?.externalId ?? null,
      outside: table.hitTest(margin + mediaWidth + 0.01, margin + 1),
    };
  }, { id, fonts });
}

async function followingPrimitive(page: Page, id: string) {
  return page.evaluate(id => {
    const { entries, dpr } = (window as any).__tableLayout;
    const { canvas, ctx, incomingFont, afterTable } = entries[id];
    const reference = document.createElement('canvas');
    reference.width = canvas.width;
    reference.height = canvas.height;
    const control = reference.getContext('2d')!;
    control.font = incomingFont;
    control.fillStyle = '#22cc88';
    control.textAlign = 'left';
    control.textBaseline = 'top';
    control.fillText('Following primitive', 16 * dpr, 112 * dpr);
    const top = Math.round(100 * dpr);
    const actual = ctx.getImageData(0, top, canvas.width, canvas.height - top).data;
    const expected = control.getImageData(0, top, canvas.width, canvas.height - top).data;
    let different = 0, ink = 0;
    for (let i = 0; i < actual.length; i += 4) {
      if (actual[i + 3] > 0) ink++;
      if (actual[i] !== expected[i] || actual[i + 1] !== expected[i + 1]
        || actual[i + 2] !== expected[i + 2] || actual[i + 3] !== expected[i + 3]) different++;
    }
    return { incomingFont, afterTable, different, ink };
  }, id);
}

for (const [dpr, automaticFonts, weightedFonts] of [
  [1, [[11, 11], [11, 9]], [[6, 6], [18, 8]]],
  [1.5, [[16, 16], [16, 14]], [[9, 9], [27, 12]]],
  [2, [[22, 22], [22, 18]], [[12, 12], [37, 16]]],
] as const) {
  test.describe(`table layout at DPR ${dpr}`, () => {
    test.use({ deviceScaleFactor: dpr, viewport: { width: 1000, height: 760 } });

    test('merged cells retain multiline text, spanning backgrounds and an independent frame', async ({ page }, info) => {
      await ready(page);
      const evidence = await page.evaluate(() => {
        const { entries, dpr, margin } = (window as any).__tableLayout;
        const { canvas, ctx, table, incomingFont, afterTable } = entries.formatted;
        const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        let coveredInk = 0, frameInk = 0;
        const textRows = new Set<number>();
        for (let i = 0; i < pixels.length; i += 4) {
          const [r, g, b] = pixels.slice(i, i + 3);
          if (r > 240 && g < 10 && b > 240) coveredInk++;
          if (r > 240 && g > 190 && g < 215 && b < 10) frameInk++;
          // Include partially covered glyph pixels so font antialiasing does not
          // split one text line into several disconnected rows.
          if (r < 20 && g > 80 && b > 100 && b < 215) textRows.add(Math.floor(i / 4 / canvas.width));
        }
        const rows = [...textRows].sort((a, b) => a - b);
        let blocks = 0;
        rows.forEach((row, index) => { if (index === 0 || row > rows[index - 1] + 1) blocks++; });
        const sample = (x: number, y: number) => Array.from(ctx.getImageData(Math.round(x * dpr), Math.round(y * dpr), 1, 1).data).slice(0, 3);
        return {
          coveredInk, frameInk, blocks,
          headingSeam: sample(margin + 100, margin + 4),
          rowSeam: sample(margin + 10, margin + 80),
          inside: table.hitTest(margin + 299, margin + 119)?.externalId,
          outside: table.hitTest(margin + 301, margin + 119), incomingFont, afterTable,
        };
      });
      expect(evidence.coveredInk).toBe(0);
      expect(evidence.frameInk).toBeGreaterThan(300);
      expect(evidence.blocks, JSON.stringify(evidence)).toBe(2);
      expect(evidence.headingSeam).toEqual([51, 68, 85]);
      expect(evidence.rowSeam).toEqual([18, 52, 86]);
      expect(evidence.inside).toBe('formatted');
      expect(evidence.outside).toBeNull();
      expect(evidence.afterTable).toEqual({ font: evidence.incomingFont, fillStyle: '#22cc88', textAlign: 'left', textBaseline: 'top' });
      await page.locator('#formatted').screenshot({ path: info.outputPath('formatted-table.png') });
    });

    test('automatic widths follow rendered fonts and preserve the next primitive', async ({ page }, info) => {
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await ready(page);
      for (const [id, fonts] of [['automatic', automaticFonts], ['weighted', weightedFonts]] as const) {
        const bounds = await measuredBounds(page, id, fonts.map(row => [...row]));
        expect(bounds.dpr).toBe(dpr);
        expect(bounds.actualWidth).toBe(bounds.expectedWidth);
        expect(bounds.left).toBe(bounds.expectedLeft);
        expect(bounds.inside).toBe(id);
        expect(bounds.outside).toBeNull();
        const next = await followingPrimitive(page, id);
        expect(next.afterTable).toEqual({
          font: next.incomingFont, fillStyle: '#22cc88', textAlign: 'left', textBaseline: 'top',
        });
        expect(next.ink).toBeGreaterThan(100);
        expect(next.different).toBe(0);
      }
      await info.attach(`table layout DPR ${dpr}`, { body: await page.screenshot(), contentType: 'image/png' });
      expect(errors).toEqual([]);
    });

    test('fixed columns clip long labels without hiding neighboring text', async ({ page }, info) => {
      await ready(page);
      const pixels = await page.evaluate(() => {
        const { entries, dpr, margin } = (window as any).__tableLayout;
        const { canvas, ctx } = entries.clipped;
        const data = ctx.getImageData(0, 0, canvas.width, Math.round(60 * dpr)).data;
        const boundary = Math.round((margin + 40) * dpr);
        let first = 0, escaped = 0, neighbor = 0;
        for (let i = 0; i < data.length; i += 4) {
          const x = (i / 4) % canvas.width;
          if (data[i] > 170 && data[i + 1] < 100 && data[i + 2] < 120) {
            if (x < boundary) first++; else escaped++;
          }
          if (x >= boundary && data[i] < 100 && data[i + 1] > 150 && data[i + 2] > 90) neighbor++;
        }
        return { first, escaped, neighbor };
      });
      expect(pixels.first).toBeGreaterThan(10);
      expect(pixels.escaped).toBe(0);
      expect(pixels.neighbor).toBeGreaterThan(10);
      const next = await followingPrimitive(page, 'clipped');
      expect(next.ink).toBeGreaterThan(100);
      expect(next.different).toBe(0);
      await info.attach(`clipped table DPR ${dpr}`, {
        body: await page.locator('#clipped').screenshot(), contentType: 'image/png',
      });
    });
  });
}
