import { expect, test, type Page } from '@playwright/test';

// Every label a person or assistive technology meets, in the widget chrome
// and the demo host, in the states the 2.5.10 label audit walked. The audit
// found a toolbar tooltip reading "[object Object]", toggles whose name said
// the opposite of their pressed state, and icon buttons with no name; this
// spec keeps that class of defect from coming back. It reads each visible
// control's accessible name and the attributes and text around it, and fails
// on a leaked value ("[object", undefined, null, NaN, an unfilled {key}), an
// icon-only control with no name, or a toggle named for the state it is not
// in. Fixture data only: the widget pages are static, the demo runs its
// server in --fixture mode (skipped, like its own spec, without Python).

const DEMO = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || 8124}`;
const DEMO_PAGE = `${DEMO}/examples/yfinance/index.html?test=1`;

/** Runs in the page: what is wrong with the labels under `scope`, one line per problem. */
function audit(scope: string | null): string[] {
  const LEAK = /\[object|\bundefined\b|\bnull\b|\bNaN\b|\{[a-zA-Z_]+\}/;
  // A toggle named for the other state: "Unlock" pressed, "Show" checked on a hidden drawing,
  // "Remove X from selection" pressed.
  const OPPOSITE = /^(Unlock|Unpin|Unhide|Show|Deselect|Restore)\b|\bfrom selection$/i;
  const CONTROL = 'button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=menuitem], '
    + '[role=menuitemcheckbox], [role=menuitemradio], [role=tab], [role=switch], [role=checkbox], [role=radio], [role=slider], [role=option]';
  const shown = (n: Element): boolean => {
    const r = n.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    for (let a: Element | null = n; a !== null; a = a.parentElement) {
      if ((a as HTMLElement).hidden || a.getAttribute('aria-hidden') === 'true') return false;
      const style = getComputedStyle(a);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    }
    return true;
  };
  const collapse = (s: string | null | undefined): string => (s ?? '').replace(/\s+/g, ' ').trim();
  const content = (n: Element): string => {
    let out = '';
    for (const c of Array.from(n.childNodes)) {
      if (c.nodeType === 3) { out += ' ' + c.nodeValue; continue; }
      if (c.nodeType !== 1) continue;
      const el = c as Element;
      if (el.getAttribute('aria-hidden') === 'true') continue;
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      if (el.getAttribute('aria-label')) { out += ' ' + el.getAttribute('aria-label'); continue; }
      if (el.tagName === 'svg') { out += ' ' + (el.querySelector(':scope > title')?.textContent ?? ''); continue; }
      out += ' ' + content(el);
    }
    return collapse(out);
  };
  const byIds = (ids: string | null): string => collapse((ids ?? '').split(/\s+/).map(id => document.getElementById(id)?.textContent ?? '').join(' '));
  const nameOf = (n: Element): string => {
    const labelled = byIds(n.getAttribute('aria-labelledby'));
    if (labelled) return labelled;
    const aria = collapse(n.getAttribute('aria-label'));
    if (aria) return aria;
    if (n instanceof HTMLInputElement || n instanceof HTMLSelectElement || n instanceof HTMLTextAreaElement) {
      const label = n.id ? document.querySelector(`label[for="${CSS.escape(n.id)}"]`) : null;
      const text = collapse((label ?? n.closest('label'))?.textContent);
      if (text) return text;
      if (n instanceof HTMLInputElement && ['button', 'submit', 'reset'].includes(n.type)) return collapse(n.value);
      return collapse(n.getAttribute('title') ?? n.getAttribute('placeholder'));
    }
    return content(n) || collapse(n.getAttribute('title'));
  };
  const where = (n: Element): string => {
    const cls = typeof n.className === 'string' ? n.className.split(/\s+/).filter(Boolean).slice(0, 2).join('.') : '';
    return `${n.tagName.toLowerCase()}${n.id ? '#' + n.id : ''}${cls ? '.' + cls : ''}${n.getAttribute('data-act') ? `[data-act=${n.getAttribute('data-act')}]` : ''}`;
  };
  const root = scope === null ? document.body : document.querySelector(scope);
  if (root === null) return [`${scope}: not on the page`];
  const problems: string[] = [];
  for (const n of Array.from(root.querySelectorAll(CONTROL))) {
    if (!shown(n)) continue;
    const name = nameOf(n);
    if (name === '') problems.push(`${where(n)}: no accessible name`);
    for (const [what, value] of [['name', name], ['title', n.getAttribute('title')], ['aria-label', n.getAttribute('aria-label')],
      ['aria-description', n.getAttribute('aria-description')], ['placeholder', n.getAttribute('placeholder')]] as const) {
      if (value && LEAK.test(value)) problems.push(`${where(n)}: ${what} "${value}"`);
    }
    const on = n.getAttribute('aria-pressed') === 'true' || n.getAttribute('aria-checked') === 'true';
    if (on && OPPOSITE.test(name)) problems.push(`${where(n)}: "${name}" names the state it is not in`);
  }
  // The words on screen besides the controls: status lines, tips, headings.
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const parent = node.parentElement;
    if (parent === null || parent.closest('script, style, noscript, template') || !LEAK.test(node.nodeValue ?? '') || !shown(parent)) continue;
    problems.push(`${where(parent)}: text "${collapse(node.nodeValue).slice(0, 80)}"`);
  }
  return problems;
}

/** Audit the page as it is now, under a name for the report; every state reports, not only the first. */
async function check(page: Page, found: string[], state: string, scope: string | null = null): Promise<void> {
  const problems = await page.evaluate(audit, scope);
  expect.soft(problems, state).toEqual([]);
  for (const problem of problems) found.push(`${state}: ${problem}`);
}

test.describe('the widget chrome', () => {
  test('names every control, leaks no value, and keeps toggle names true to their state', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.setViewportSize({ width: 1280, height: 760 });
    await page.goto('/tests/e2e/widget-drawing-ui-fixture.html');
    await page.waitForFunction(() => (window as any).__drawUi?.ready === true);
    const found: string[] = [];
    await check(page, found, 'at rest');

    await page.evaluate(() => { const { widget, ids } = (window as any).__drawUi; widget.draw.update(ids.box, { locked: true }); widget.draw.select(ids.trend); });
    await expect(page.locator('.oac-drawbar')).toBeVisible();
    await check(page, found, 'a drawing selected');
    await page.evaluate(() => { const { widget, ids } = (window as any).__drawUi; widget.draw.select(ids.box); });
    await check(page, found, 'a locked drawing selected');
    await page.locator('.oac-drawbar [data-drawbar="more"]').click();
    await check(page, found, 'the drawing toolbar more menu');
    await page.getByRole('menuitem', { name: 'Properties...' }).click();
    await expect(page.locator('.oac-props')).toBeVisible();
    await check(page, found, 'drawing properties');
    await page.keyboard.press('Escape');

    // The right-click menu on the trend line itself.
    const at = await page.evaluate(() => {
      const { widget, ids } = (window as any).__drawUi;
      const [a, b] = widget.draw.get(ids.trend).points;
      const box = widget.root.querySelector('.oac-chart').getBoundingClientRect();
      return { x: box.left + (widget.chart.timeToCoordinate(a.time) + widget.chart.timeToCoordinate(b.time)) / 2,
        y: box.top + (widget.chart.priceToCoordinate(a.price) + widget.chart.priceToCoordinate(b.price)) / 2 };
    });
    await page.mouse.click(at.x, at.y, { button: 'right' });
    await check(page, found, 'the right-click menu on a drawing');
    await page.keyboard.press('Escape');
    // The same menu on a hidden drawing, which the pointer cannot reach: its Hide row is checked.
    await page.evaluate(async () => {
      const { widget, ids } = (window as any).__drawUi;
      const { mountContextMenu } = await import('/dist/openalgo-charts.widget.mjs' as string);
      widget.draw.update(ids.trend, { visible: false });
      mountContextMenu(widget.context, undefined, { event: { paneIndex: widget.chart.primaryPaneIndex(), point: { x: 200, y: 200 },
        price: null, time: null, index: null, target: { kind: 'drawing', id: 'draw:' + ids.trend }, preventDefault: () => {} } });
    });
    await expect(page.locator('.oac-ctx [aria-checked="true"]').first()).toBeVisible();
    await check(page, found, 'the right-click menu on a hidden drawing');
    await page.keyboard.press('Escape');
    await page.evaluate(() => { const { widget, ids } = (window as any).__drawUi; widget.draw.update(ids.trend, { visible: true }); });

    await page.locator('.oac-rail__group').first().dispatchEvent('contextmenu');
    await check(page, found, 'a rail flyout');
    await page.keyboard.press('Escape');

    for (const [state, open] of [['objects', 'openObjects'], ['chart settings', 'openSettings'], ['alerts', 'openAlerts']] as const) {
      await page.evaluate(open => (window as any).__drawUi.widget[open](), open);
      await page.waitForTimeout(100);
      await check(page, found, state);
      await page.evaluate(() => (window as any).__drawUi.widget.context.overlays.closeAll());
    }
    await page.locator('.oac-chart').focus();
    await page.keyboard.press('Shift+Slash');
    await expect(page.locator('.oac-keys-dialog')).toBeVisible();
    await check(page, found, 'the shortcuts panel');
    expect(found).toEqual([]);
    expect(errors).toEqual([]);
  });

  test('names every control of the phone layout', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/tests/e2e/widget-mobile-fixture.html');
    await page.waitForFunction(() => (window as any).__ready === true && (window as any).__loaded > 0);
    const found: string[] = [];
    await check(page, found, 'phone at rest');
    await page.evaluate(() => {
      const widget = (window as any).__widget;
      const bars = widget.chart.primaryBars();
      const d = widget.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, locked: true, points: [{ time: bars[bars.length - 20].time, price: bars[bars.length - 20].close }] });
      widget.draw.select(d.id);
    });
    await check(page, found, 'phone with a locked drawing selected');
    await page.locator('[data-mobile-action="more"]').click();
    await check(page, found, 'phone more sheet');
    expect(found).toEqual([]);
  });
});

test.describe('the demo host', () => {
  let demoUp: boolean | null = null;
  test.beforeEach(async ({ request }) => {
    if (demoUp === null) demoUp = await request.get(`${DEMO}/api/history?symbol=AAPL&interval=1d&period=1mo`).then(r => r.ok(), () => false);
    test.skip(!demoUp, 'the yfinance demo server is not up (playwright.config.ts starts it when a Python 3 is on PATH)');
  });

  const open = async (page: Page, width: number, height: number): Promise<void> => {
    await page.setViewportSize({ width, height });
    await page.goto(DEMO_PAGE);
    await page.waitForFunction(() => Boolean((window as any).__oac?.app.currentBars.length));
  };
  const select = (page: Page, tool: string, extra: Record<string, unknown> = {}) => page.evaluate(([tool, extra]) => {
    const { draw, app } = (window as any).__oac;
    const bars = app.currentBars;
    const a = bars[bars.length - 40], b = bars[bars.length - 10];
    const points = tool === 'text' ? [{ time: a.time, price: a.high }] : [{ time: a.time, price: a.low }, { time: b.time, price: b.high }];
    draw.select(draw.add({ tool, paneIndex: 0, style: {}, points, ...extra }).id);
  }, [tool, extra] as const);

  test('names every control, leaks no value, and keeps toggle names true to their state', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    await open(page, 1440, 900);
    const found: string[] = [];
    await check(page, found, 'at rest');
    await select(page, 'trend-line', { locked: true });
    await expect(page.locator('#propbar')).toBeVisible();
    await check(page, found, 'a locked trend line selected');
    await select(page, 'text', { text: { value: 'Breakout' } });
    await check(page, found, 'a text drawing selected');
    await select(page, 'horizontal-line', { policy: { editable: false } });
    await check(page, found, 'a read-only drawing selected');
    await select(page, 'rectangle');
    await page.locator('#propbar [data-path="style.fillColor"]').click();
    await check(page, found, 'the fill popover');
    await page.keyboard.press('Escape');

    const box = (await page.locator('#chart').boundingBox())!;
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.35, { button: 'right' });
    await check(page, found, 'the chart menu');
    await page.keyboard.press('Escape');
    await page.mouse.click(box.x + box.width - 20, box.y + box.height * 0.3, { button: 'right' });
    await check(page, found, 'the price axis menu');
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: /^Chart type/ }).click();
    await check(page, found, 'the chart type menu');
    await page.keyboard.press('Escape');
    await page.locator('#account').click();
    await check(page, found, 'the sandbox broker');
    await page.keyboard.press('Escape');
    expect(found).toEqual([]);
    expect(errors).toEqual([]);
  });

  test('names every control on a phone', async ({ page }) => {
    await open(page, 390, 844);
    const found: string[] = [];
    await check(page, found, 'phone at rest');
    expect(found).toEqual([]);
  });
});
