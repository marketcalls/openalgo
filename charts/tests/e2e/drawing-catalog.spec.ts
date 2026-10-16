import { expect, test, type Page } from '@playwright/test';

async function mount(page: Page) {
  await page.setViewportSize({ width: 1200, height: 760 });
  await page.goto('/examples/drawings/index.html');
  await page.waitForFunction(() => (window as any).drawingGallery);
}

async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

test('the gallery exposes every registered drawing in both its picker and rail', async ({ page }) => {
  await mount(page);
  const ids = await page.evaluate(() => (window as any).drawingGallery.tools.map((t: any) => t.id));
  expect(ids.length).toBe(87);
  expect(new Set(ids).size).toBe(87);
  expect(await page.locator('#tool option').count()).toBe(87);
  const missing = await page.evaluate(async () => {
    const path = '/dist/openalgo-charts.widget.mjs';
    const module = await import(path);
    const listed = module.RAIL_GROUPS.flatMap((g: any) => (g.items ?? []).map((i: any) => i.tool).filter(Boolean));
    return (window as any).drawingGallery.tools.map((t: any) => t.id).filter((id: string) => !listed.includes(id));
  });
  expect(missing).toEqual([]);
});

test('the status line says what opens the properties of a drawing, and double-click is not it', async ({ page }) => {
  await mount(page);
  // Right-click or the drawing's toolbar opens them; a double-click resets the scale.
  await expect(page.locator('#status')).toContainText('Right-click a drawing, or use its toolbar, for properties.');
  await expect(page.locator('#status')).not.toContainText('Double-click a drawing');
});

test('every drawing paints, restores and stays clipped inside the chart', async ({ page }, info) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await mount(page);
  const tools = await page.evaluate(() => (window as any).drawingGallery.tools.map((t: any) => ({ id: t.id, name: t.name })));
  for (const tool of tools) {
    await page.evaluate(() => {
      const { widget } = (window as any).drawingGallery;
      widget.draw.fromJSON({ version: 2, drawings: [] });
    });
    await settle(page);
    await page.evaluate(() => {
      const canvas = document.querySelectorAll('#chart canvas')[1] as HTMLCanvasElement;
      (window as any).__cleanDrawingPixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
    });
    await page.selectOption('#tool', tool.id);
    await settle(page);
    const result = await page.evaluate(() => {
      const { widget } = (window as any).drawingGallery;
      const canvas = document.querySelectorAll('#chart canvas')[1] as HTMLCanvasElement;
      const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
      const clean = (window as any).__cleanDrawingPixels;
      const dpr = canvas.width / canvas.getBoundingClientRect().width;
      const width = Math.round(widget.chart.timeScale.width * dpr);
      const height = Math.round((canvas.getBoundingClientRect().height - 22) * dpr);
      let changed = 0, outside = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] === clean[i] && pixels[i + 1] === clean[i + 1] && pixels[i + 2] === clean[i + 2] && pixels[i + 3] === clean[i + 3]) continue;
        const x = (i / 4) % canvas.width, y = Math.floor((i / 4) / canvas.width);
        if (x >= width || y >= height) outside++; else changed++;
      }
      const savedDocument = widget.draw.toJSON();
      widget.draw.fromJSON(JSON.parse(JSON.stringify(savedDocument)));
      return { changed, outside, saved: savedDocument, restored: widget.draw.toJSON() };
    });
    expect(result.changed, tool.id + ' paints a visible drawing').toBeGreaterThan(8);
    expect(result.outside, tool.id + ' clips to the plot').toBe(0);
    expect(result.restored, tool.id + ' persists').toEqual(result.saved);
    if (['pitchfork', 'fib-spiral', 'gartley', 'gann-square', 'dedekind-tessellation'].includes(tool.id)) {
      await page.screenshot({ path: info.outputPath(tool.id + '.png') });
    }
  }
  expect(errors).toEqual([]);
});

test('every tool can be placed with pointer input and undone', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await mount(page);
  const tools = await page.evaluate(() => (window as any).drawingGallery.tools.map((t: any) => ({ id: t.id, points: t.points, freehand: t.freehand })));
  for (const tool of tools) {
    await page.keyboard.press('Escape');
    const points = await page.evaluate((id: string) => {
      const api = (window as any).drawingGallery;
      api.widget.draw.setTool(null);
      api.widget.draw.fromJSON({ version: 2, drawings: [] });
      api.widget.draw.setTool(id);
      const tool = api.tools.find((t: any) => t.id === id);
      const points = api.samplePoints(tool);
      const rect = document.querySelectorAll('#chart canvas')[1].getBoundingClientRect();
      return points.map((p: any) => ({
        x: rect.left + api.widget.chart.timeToCoordinate(p.time),
        y: rect.top + api.widget.chart.priceToCoordinate(p.price),
      }));
    }, tool.id);
    if (tool.freehand) {
      await page.mouse.move(points[0].x, points[0].y);
      await page.mouse.down();
      for (const p of points.slice(1)) await page.mouse.move(p.x, p.y);
      await page.mouse.up();
    } else {
      const selected = tool.points === 0 ? points.slice(0, 5) : points.slice(0, tool.points);
      for (const p of selected) await page.mouse.click(p.x, p.y);
      if (tool.points === 0) await page.mouse.dblclick(selected.at(-1).x, selected.at(-1).y);
    }
    const result = await page.evaluate(() => {
      const draw = (window as any).drawingGallery.widget.draw;
      const drawings = draw.toJSON().drawings;
      const undo = draw.undo();
      const afterUndo = draw.drawings().length;
      const redo = draw.redo();
      return { drawings, undo, afterUndo, redo, afterRedo: draw.toJSON().drawings };
    });
    expect(result.drawings.length, tool.id + ' placed').toBe(1);
    expect(result.drawings[0].points.every((p: any) => Number.isFinite(p.time) && Number.isFinite(p.price)), tool.id).toBe(true);
    expect(result.undo, tool.id).toBe(true);
    expect(result.afterUndo, tool.id).toBe(0);
    expect(result.redo, tool.id).toBe(true);
    expect(result.afterRedo, tool.id).toEqual(result.drawings);
  }
  expect(errors).toEqual([]);
});

test('every sample exposes a movable anchor with one-step undo', async ({ page }) => {
  test.setTimeout(180_000);
  await mount(page);
  const tools = await page.evaluate(() => (window as any).drawingGallery.tools.map((t: any) => t.id));
  for (const id of tools) {
    await page.evaluate((id: string) => (window as any).drawingGallery.sample(id), id);
    await settle(page);
    const anchor = await page.evaluate(() => {
      const { widget } = (window as any).drawingGallery;
      const drawing = widget.draw.drawings()[0];
      widget.draw.select(drawing.id);
      const p = drawing.points[0], rect = document.querySelectorAll('#chart canvas')[1].getBoundingClientRect();
      return { x: rect.left + widget.chart.timeToCoordinate(p.time), y: rect.top + widget.chart.priceToCoordinate(p.price), before: JSON.stringify(drawing.points) };
    });
    await page.mouse.move(anchor.x, anchor.y);
    await page.mouse.down();
    await page.mouse.move(anchor.x + 18, anchor.y + 12, { steps: 3 });
    await page.mouse.up();
    const result = await page.evaluate(() => {
      const draw = (window as any).drawingGallery.widget.draw;
      const moved = JSON.stringify(draw.drawings()[0].points);
      draw.undo();
      return { moved, restored: JSON.stringify(draw.drawings()[0].points) };
    });
    expect(result.moved, id + ' moved').not.toEqual(anchor.before);
    expect(result.restored, id + ' undo').toEqual(anchor.before);
  }
});

test('every drawing can be moved by its painted body without changing its shape', async ({ page }) => {
  test.setTimeout(240_000);
  await mount(page);
  const tools = await page.evaluate(() => (window as any).drawingGallery.tools.map((t: any) => t.id));
  for (const id of tools) {
    await page.evaluate((id: string) => (window as any).drawingGallery.sample(id), id);
    await settle(page);
    const target = await page.evaluate(() => {
      const { widget } = (window as any).drawingGallery;
      const { chart, draw } = widget;
      draw.select(null);
      const drawing = draw.drawings()[0];
      const pane = chart._panes[0], rc = chart._renderContext(0);
      const anchors = drawing.points.map((p: any) => ({ x: chart.timeToCoordinate(p.time), y: chart.priceToCoordinate(p.price) }));
      const canvas = document.querySelectorAll('#chart canvas')[1].getBoundingClientRect();
      const points: { x: number; y: number }[] = [];
      for (const p of anchors) for (const radius of [24, 12, 4]) for (let angle = 0; angle < 6.28; angle += .3) points.push({ x: p.x + Math.cos(angle) * radius, y: p.y + Math.sin(angle) * radius });
      for (let y = 25; y < canvas.height - 50; y += 8) for (let x = 20; x < chart.timeScale.width - 25; x += 8) points.push({ x, y });
      for (const p of points) {
        // Mouse drivers in some browsers quantize client coordinates. Choose
        // a real integer pixel before probing the same location for a hit.
        p.x = Math.floor(canvas.left + p.x) - canvas.left;
        p.y = Math.floor(canvas.top + p.y) - canvas.top;
        if (p.x < 15 || p.x > chart.timeScale.width - 25 || p.y < 15 || p.y > canvas.height - 50) continue;
        if (anchors.length > 1 && anchors.some((a: any) => Math.hypot(a.x - p.x, a.y - p.y) < 10)) continue;
        const hit = pane.hitTestPrimitives(p.x, p.y, rc);
        if (hit?.externalId !== 'draw:' + drawing.id) continue;
        if ([[-.75, 0], [.75, 0], [0, -.75], [0, .75]].some(([dx, dy]) => pane.hitTestPrimitives(p.x + dx, p.y + dy, rc)?.externalId !== hit.externalId)) continue;
        return { x: canvas.left + p.x, y: canvas.top + p.y, before: JSON.stringify(drawing.points) };
      }
      return null;
    });
    expect(target, id + ' has a selectable body').not.toBeNull();
    await page.mouse.move(target!.x, target!.y);
    await page.mouse.down();
    await page.mouse.move(target!.x + 14, target!.y + 10, { steps: 3 });
    await page.mouse.up();
    const moved = await page.evaluate(() => {
      const draw = (window as any).drawingGallery.widget.draw;
      const after = JSON.stringify(draw.drawings()[0].points);
      draw.undo();
      return { after, restored: JSON.stringify(draw.drawings()[0]?.points) };
    });
    expect(moved.after, id + ' body moves').not.toEqual(target!.before);
    const original = JSON.parse(target!.before), translated = JSON.parse(moved.after);
    expect(translated.length, id + ' retains every anchor').toBe(original.length);
    for (let i = 1; i < original.length; i++) {
      expect(translated[i].time - translated[0].time, id + ' retains time offsets').toBeCloseTo(original[i].time - original[0].time, 3);
      expect(translated[i].price - translated[0].price, id + ' retains price offsets').toBeCloseTo(original[i].price - original[0].price, 6);
    }
    expect(moved.restored, id + ' body undo').toEqual(target!.before);
  }
});

test.describe('touch drawing catalog', () => {
  test.use({ hasTouch: true });

  test('all tools support phone placement and touch anchor adjustment', async ({ page, browserName }, info) => {
    test.setTimeout(240_000);
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/examples/drawings/index.html');
    await page.waitForFunction(() => (window as any).drawingGallery);
    // Chromium exposes native touch drags; the other engines support taps only
    // through Playwright, so their drag checks exercise touch pointer handlers.
    const touch = browserName === 'chromium' ? await page.context().newCDPSession(page) : null;
    async function dragTouch(points: { x: number; y: number }[]) {
      for (let i = 0; i < points.length; i++) {
        await touch!.send('Input.dispatchTouchEvent', {
          type: i === 0 ? 'touchStart' : 'touchMove',
          touchPoints: [{ ...points[i], id: 31 }],
        });
      }
      await touch!.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    }
    const tools = await page.evaluate(() => (window as any).drawingGallery.tools.map((t: any) => ({ id: t.id, points: t.points, freehand: t.freehand })));
    for (const tool of tools) {
      await page.evaluate((id: string) => {
        const api = (window as any).drawingGallery;
        const { draw } = api.widget;
        draw.setTool(null);
        draw.fromJSON({ version: 2, drawings: [] });
        draw.setTool(id);
      }, tool.id);
      await settle(page);
      const points = await page.evaluate((id: string) => {
        const api = (window as any).drawingGallery;
        const { chart } = api.widget;
        const rect = document.querySelectorAll('#chart canvas')[1].getBoundingClientRect();
        return api.samplePoints(api.tools.find((t: any) => t.id === id)).map((p: any) => ({
          x: rect.left + chart.timeToCoordinate(p.time), y: rect.top + chart.priceToCoordinate(p.price),
        }));
      }, tool.id);
      if (tool.freehand) {
        if (touch) await dragTouch(points);
        else await page.evaluate(points => {
          const target = document.elementFromPoint(points[0].x, points[0].y)!;
          points.forEach((p: any, i: number) => target.dispatchEvent(new PointerEvent(i === 0 ? 'pointerdown' : 'pointermove', {
            bubbles: true, pointerId: 31, pointerType: 'touch', isPrimary: true, button: 0, buttons: 1, clientX: p.x, clientY: p.y,
          })));
          const p = points.at(-1);
          target.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 31, pointerType: 'touch', isPrimary: true, button: 0, buttons: 0, clientX: p.x, clientY: p.y }));
        }, points);
      } else {
        for (const p of (tool.points === 0 ? points.slice(0, 5) : points.slice(0, tool.points))) await page.touchscreen.tap(p.x, p.y);
        if (tool.points === 0) await page.evaluate(() => (window as any).drawingGallery.widget.draw.finish());
      }
      expect(await page.evaluate(() => (window as any).drawingGallery.widget.draw.drawings().length), tool.id + ' touch placement').toBe(1);
      const before = await page.evaluate(() => {
        const api = (window as any).drawingGallery;
        const drawing = api.widget.draw.drawings()[0];
        api.widget.draw.select(drawing.id);
        return JSON.stringify(drawing.points);
      });
      await settle(page);
      const anchor = await page.evaluate(() => {
        const { widget } = (window as any).drawingGallery;
        const p = widget.draw.drawings()[0].points[0];
        const rect = document.querySelectorAll('#chart canvas')[1].getBoundingClientRect();
        const x = rect.left + widget.chart.timeToCoordinate(p.time), y = rect.top + widget.chart.priceToCoordinate(p.price);
        return { x, y };
      });
      if (touch) await dragTouch([anchor, { x: anchor.x + 9, y: anchor.y + 6 }, { x: anchor.x + 18, y: anchor.y + 12 }]);
      else await page.evaluate(({ x, y }) => {
        const target = document.elementFromPoint(x, y)!;
        for (const [type, dx, dy] of [['pointerdown', 0, 0], ['pointermove', 18, 12], ['pointerup', 18, 12]] as const) {
          target.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId: 32, pointerType: 'touch', isPrimary: true, button: 0, buttons: type === 'pointerup' ? 0 : 1, clientX: x + dx, clientY: y + dy }));
        }
      }, anchor);
      const after = await page.evaluate(() => JSON.stringify((window as any).drawingGallery.widget.draw.drawings()[0].points));
      expect(after, tool.id + ' touch handle').not.toEqual(before);
      if (['fib-circles', 'pitchfork', 'gartley'].includes(tool.id)) await page.screenshot({ path: info.outputPath('phone-' + tool.id + '.png') });
    }
    await touch?.detach();
    expect(errors).toEqual([]);
  });
});
