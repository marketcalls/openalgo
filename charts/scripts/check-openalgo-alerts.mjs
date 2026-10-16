import assert from 'node:assert/strict';
import { expect } from '@playwright/test';

/**
 * Drive the host's alert controls against the installed candidate and real terminal.
 *
 * The host hands the terminal `cb.onAlerts`, so the chart's alert entry points
 * open the host's own alert form and list, not the widget tier's alert UI: the
 * toolbar's Alerts opens the form for the selected chart, the right rail's
 * Alerts opens the list, and a chart right-click creates the alert at the
 * clicked price, study or drawing straight away. What is checked underneath is
 * the package's: the `AlertController` sources, evaluation, persistence and
 * the replay lock.
 */
export async function checkAlerts({ page, terminal, check, reload, sendDepth, screenshot, orderCount, hostFinding }) {
  const ordersBefore = orderCount();
  const ready = () => page.waitForFunction(() => {
    const terminal = window.__compatTerminals?.findLast(t => !t.destroyed && t.chart);
    return !!terminal?.alerts && !terminal.dataUnavailable() && !terminal.preparingWorkspace
      && !!terminal.container.closest('[data-workspace-active="true"]')
      && !document.querySelector('[data-workspace-active="false"]');
  });
  const form = page.getByRole('dialog', { name: 'Create alert', exact: true });
  const panel = page.getByRole('complementary', { name: 'Alerts' });
  // The toolbar and the rail act on the selected chart, so select the one the
  // checks read before using either. The toolbar's button is named by its
  // text, the rail's by its aria-label.
  const toolbar = page.getByRole('toolbar', { name: 'Chart controls' });
  const selectChart = async () => {
    const key = await terminal(t => {
      t.container.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
      return t.sk.replace('oa-trading-', '');
    });
    await expect(toolbar).toHaveAttribute('data-toolbar-pane', key);
  };
  const openForm = async () => {
    await selectChart();
    await toolbar.getByRole('button', { name: 'Alerts', exact: true }).click();
    await expect(form).toBeVisible();
  };
  const closeForm = async () => {
    await page.keyboard.press('Escape');
    await expect(form).toHaveCount(0);
  };
  const togglePanel = async open => {
    if (open) await selectChart();
    await page.locator('button[aria-label="Alerts"]').click();
    if (open) await expect(panel).toBeVisible();
    else await expect(panel).toHaveCount(0);
  };
  // The host's list is read separately from the controller, which the checks
  // assert directly: a list that misses what the controller holds is the
  // host's view of the chart's alerts, so it is reported, not failed.
  const panelLists = async (texts, when) => {
    await togglePanel(true);
    try { for (const text of texts) await expect(panel).toContainText(text, { timeout: 10000 }); }
    catch {
      const held = await terminal(t => t.alerts.list().length);
      hostFinding(`${when} the Alerts panel lists none of the ${held} alerts the chart holds: ${(await panel.innerText()).replace(/\s+/g, ' ').slice(0, 120)}`);
    }
  };
  const choose = async (label, option) => {
    await form.getByRole('combobox', { name: label, exact: true }).click();
    await page.getByRole('option', { name: option, exact: true }).click();
  };
  const create = async ({ name, kind, study, drawing, threshold }) => {
    await openForm();
    await choose('What to watch', { price: 'Price', indicator: 'Study plot', drawing: 'Drawing level' }[kind]);
    if (study) await choose('Study', study);
    if (drawing) await choose('Drawing', drawing);
    if (threshold !== undefined) await form.getByRole('textbox', { name: 'Value', exact: true }).fill(String(threshold));
    await choose('Repeat', 'Only once');
    await choose('Evaluate', 'Intrabar touch');
    await form.getByRole('textbox', { name: 'Alert name', exact: true }).fill(name);
    await form.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(form).toHaveCount(0);
  };
  // The menu entry creates the alert where the pointer is; there is no form.
  // What the package decides is the menu's target, read from its contextmenu
  // event; what the host then does with it comes back as an alert or as the
  // host's refusal, in its own words.
  const createFromMenu = async (point, entry) => {
    const before = await terminal(t => {
      window.__alertMenuTargets = [];
      window.__offAlertMenu?.();
      window.__offAlertMenu = t.chart.on('contextmenu', event => window.__alertMenuTargets.push(event.target));
      return t.alerts.list().map(a => a.id);
    });
    await page.mouse.click(point.x, point.y, { button: 'right' });
    const toasts = page.locator('[data-sonner-toast]');
    const seen = await toasts.allInnerTexts();
    const fresh = async () => (await toasts.allInnerTexts()).filter(text => !seen.includes(text));
    await page.getByRole('button', { name: entry }).click();
    const target = await page.evaluate(() => { window.__offAlertMenu?.(); return window.__alertMenuTargets.at(-1); });
    await expect.poll(async () => (await terminal(t => t.alerts.list().length)) > before.length || (await fresh()).length > 0).toBe(true);
    const alert = await terminal((t, ids) => t.alerts.list().find(a => !ids.includes(a.id)) ?? null, before);
    return { target, alert, refusal: alert ? null : (await fresh()).join(' ') };
  };
  let identities;
  await check('alert form creates price, study and drawing sources in the real terminal', async () => {
    identities = await terminal(async t => {
      t.stopReplay();
      await t.loadSymbol({ symbol: 'NIFTY29SEP26FUT', exchange: 'NFO' });
      await t.applyIndicatorTemplate([{ indicatorId: 'ema', settings: { length: 1 }, paneIndex: 0 }], 'replace');
      await t.setDrawTool(null);
      const study = t.chart.indicators()[0];
      const drawing = t.draw.add({ id: 'alert-browser-line', tool: 'horizontal-line', paneIndex: 0,
        style: {}, points: [{ time: t.rawBars.at(-1).time, price: 1000 }] });
      // The host numbers studies and drawings in its choosers the way it lists them.
      const drawingIndex = t.draw.drawings().findIndex(one => one.id === drawing.id);
      return { study: study.id, drawing: drawing.id, studyLabel: `1: ${study.name}`, drawingLabel: `horizontal-line (${drawingIndex + 1})` };
    });
    await create({ name: 'Price breakout', kind: 'price', threshold: 120 });
    await create({ name: 'Study threshold', kind: 'indicator', study: identities.studyLabel, threshold: 1000 });
    await create({ name: 'Drawing threshold', kind: 'drawing', drawing: identities.drawingLabel });
    const alerts = await terminal(t => t.alerts.list().map(a => ({ kind: a.source.kind, price: a.source.price, instanceId: a.source.instanceId,
      drawingId: a.source.drawingId, policy: a.policy, title: a.title })));
    assert.deepEqual(alerts.map(a => a.kind), ['price', 'indicator', 'drawing']);
    assert.equal(alerts[0].price, 120);
    assert.equal(alerts[1].instanceId, identities.study);
    assert.equal(alerts[2].drawingId, identities.drawing);
    assert(alerts.every(a => a.policy === 'onTouch'));
    await panelLists(['Price breakout', 'Study threshold', 'Drawing threshold'], 'With these three alerts set,');
    if (screenshot) await page.screenshot({ path: screenshot.replace(/\.png$/, '-alerts-list.png') });
    await togglePanel(false);
  });
  await check('fired once alert survives named workspace reload with autosave disabled', async () => {
    await page.getByRole('button', { name: 'Workspaces', exact: true }).click();
    const autosave = page.getByRole('checkbox', { name: 'Autosave chart changes', exact: true });
    if (await autosave.isChecked()) await autosave.click();
    await page.getByLabel('Workspace name', { exact: true }).fill('Alerts research');
    await page.getByRole('button', { name: 'Save as', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Workspace saved' }).waitFor();
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(page.locator('[data-slot="dialog-overlay"]')).toHaveCount(0);
    await sendDepth('NIFTY29SEP26FUT', 'NFO', 130);
    await expect.poll(() => terminal(t => t.alerts.list()[0]?.state)).toBe('triggered');
    await reload();
    await ready();
    assert.deepEqual(await terminal(t => t.alerts.list().map(a => a.state)), ['triggered', 'armed', 'armed']);
    assert.equal(await terminal(t => t.chart.indicators()[0].id), identities.study);
    assert(await terminal((t, id) => !!t.draw.get(id), identities.drawing));
    // The package restored all three, the fired one included (asserted above).
    await panelLists(['Fired'], 'After a named workspace reload,');
    await togglePanel(false);
  });
  await check('alert evaluation and order entry remain locked during cancellable replay history', async () => {
    await terminal(t => {
      const alert = t.alerts.add({ id: 'replay-guard', title: 'Replay guard', source: { kind: 'price', price: 150 }, policy: 'onTouch' });
      window.__alertReplayLoader = t.loadReplaySubBars;
      t.loadReplaySubBars = () => new Promise(resolve => { window.__finishAlertReplay = resolve; });
      window.__pendingAlertReplay = t.beginReplayAt(2);
      t.price.update({ ...t.price.getData().at(-1), high: 200, close: 200 });
      return alert.id;
    });
    assert.equal(await terminal(t => t.replayLoadingBars()), true);
    assert.equal(await terminal(t => t.alerts.list().find(a => a.id === 'replay-guard').state), 'armed');
    const refusal = await terminal(async t => {
      try { await t.placeTicket({ symbol: t.sym.symbol, exchange: t.sym.exchange, action: 'BUY',
        quantity: 1, product: 'MIS', pricetype: 'MARKET' }); return ''; }
      catch (error) { return error.message; }
    });
    assert.match(refusal, /replay/i);
    await terminal(async t => {
      t.stopReplay();
      window.__finishAlertReplay(null);
      await window.__pendingAlertReplay;
      t.loadReplaySubBars = window.__alertReplayLoader;
      t.alerts.remove('replay-guard');
    });
    assert.equal(await terminal(t => t.replayActive() || t.replayLoadingBars()), false);
    assert.equal(orderCount(), ordersBefore);
  });
  await check('narrow split charts give the alert form the full viewport and release it on rebuild', async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openForm();
    const box = await form.boundingBox();
    assert(box && box.width >= 320 && box.x >= 0 && box.x + box.width <= 391 && box.y >= 0 && box.y + box.height <= 845);
    // The host's form scrolls inside itself on a phone; its confirming action
    // has to be reachable there without the page scrolling under it.
    const confirm = form.getByRole('button', { name: 'Create', exact: true });
    await confirm.scrollIntoViewIfNeeded();
    await expect(confirm).toBeInViewport();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    if (screenshot) await page.screenshot({ path: screenshot.replace(/\.png$/, '-alerts-mobile.png') });
    // A rebuild replaces the chart the form was opened for; the form must not
    // outlive it and add an alert against a chart that is gone.
    await terminal(async t => { t.buildChart(); await t.chartToolsReady; });
    if (await form.count()) {
      hostFinding('The alert form stays open across a chart rebuild, bound to the chart it was opened for');
      await closeForm();
    }
    assert.equal(await terminal(t => t.alerts.list().length), 3);
    await page.setViewportSize({ width: 1440, height: 1000 });
    assert.equal(orderCount(), ordersBefore);
  });
  await check('chart right-click creates at the clicked price and drawing instead of the selection', async () => {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const point = await terminal(t => {
      const scale = t.chart.panes()[0].priceScale;
      scale.setAutoScale(false);
      scale.setPriceRange({ min: 80, max: 160 });
      const box = t.container.getBoundingClientRect();
      return { x: box.left + box.width * 0.45, y: box.top + t.chart.priceToCoordinate(145, 0) };
    });
    const priced = await createFromMenu(point, /^Create price alert at /);
    assert(priced.alert, `price alert refused: ${priced.refusal}`);
    assert.equal(priced.alert.source.kind, 'price');
    assert(Math.abs(priced.alert.source.price - 145) < 1, `price alert at ${priced.alert.source.price}`);
    const drawingPoint = await terminal((t, selected) => {
      t.draw.add({ id: 'context-line', tool: 'horizontal-line', paneIndex: 0, style: {},
        points: [{ time: t.rawBars.at(-1).time, price: 120 }] });
      t.draw.select(selected);
      const box = t.container.getBoundingClientRect();
      return { x: box.left + box.width * 0.45, y: box.top + t.chart.priceToCoordinate(120, 0) };
    }, identities.drawing);
    const drawn = await createFromMenu(drawingPoint, 'Create drawing alert');
    // The package names the drawing under the pointer, not the selection.
    assert.equal(drawn.target?.kind, 'drawing');
    assert.match(drawn.target.id, /^draw:context-line(#|$)/);
    if (drawn.alert) {
      assert.equal(drawn.alert.source.kind, 'drawing');
      assert.equal(drawn.alert.source.drawingId, 'context-line');
    } else {
      hostFinding(`Create drawing alert on the chart menu adds no alert: ${drawn.refusal || 'nothing said'}`);
    }
    await terminal((t, ids) => {
      for (const id of ids) t.alerts.remove(id);
      t.draw.remove('context-line');
      t.chart.panes()[0].priceScale.setAutoScale(true);
    }, [priced.alert.id, drawn.alert?.id].filter(Boolean));
  });
  await check('study right-click keeps its plotted instance and empty oscillator space offers no price alert', async () => {
    const id = await terminal(t => t.chart.addIndicator('rsi', { length: 14 }).id);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const point = await terminal((t, id) => {
      const instance = t.chart.indicators().find(study => study.id === id);
      const values = instance.values().rsi;
      const range = t.chart.getVisibleLogicalRange();
      let index = Math.max(20, Math.ceil(range.from));
      // Reference-level primitives retain priority, so target an exposed section of the plot.
      while (index < Math.min(values.length - 1, range.to) && !(values[index] > 10 && values[index] < 90
        && [30, 50, 70].every(level => Math.abs(values[index] - level) > 8))) index++;
      const box = t.container.getBoundingClientRect();
      return { x: box.left + t.chart.timeToCoordinate(t.rawBars[index].time),
        y: box.top + t.chart.priceToCoordinate(values[index], instance.paneIndex),
        blankY: box.top + t.chart.priceToCoordinate(5, instance.paneIndex), blankX: box.right - 90 };
    }, id);
    const studied = await createFromMenu(point, 'Create study alert');
    // The package names the plotted instance under the pointer.
    assert.equal(studied.target?.kind, 'indicator');
    assert.equal(studied.target.instanceId, id);
    assert(studied.alert, `study alert refused: ${studied.refusal}`);
    assert.equal(studied.alert.source.kind, 'indicator');
    assert.equal(studied.alert.source.instanceId, id);
    await terminal((t, alertId) => t.alerts.remove(alertId), studied.alert.id);
    await page.mouse.click(point.blankX, point.blankY, { button: 'right' });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(page.getByRole('button', { name: /^Create (price|study) alert/ })).toHaveCount(0);
    await page.keyboard.press('Escape');
    await terminal((t, id) => t.chart.removeIndicator(id), id);
    assert.equal(orderCount(), ordersBefore);
  });
  await check('alert form isolates drawing shortcuts and follows theme and available fullscreen', async () => {
    await terminal((t, id) => t.draw.select(id), identities.drawing);
    await openForm();
    await form.getByRole('textbox', { name: 'Alert name', exact: true }).fill('Keyboard check');
    await page.keyboard.press('Delete');
    await page.keyboard.press('Control+z');
    assert(await terminal((t, id) => !!t.draw.get(id), identities.drawing));
    await closeForm();
    // The form is the host's own surface, so it follows the page theme: a
    // dark form on a dark page and a light one on a light page.
    const luminance = () => form.evaluate(el => {
      // Painted through a canvas, which reads any CSS colour space the host uses.
      const probe = document.createElement('canvas').getContext('2d');
      probe.fillStyle = getComputedStyle(el).backgroundColor;
      probe.fillRect(0, 0, 1, 1);
      const [r, g, b] = probe.getImageData(0, 0, 1, 1).data;
      return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    });
    for (const mode of ['light', 'dark']) {
      const toggle = page.getByRole('button', { name: `Switch to ${mode} mode`, exact: true });
      if (await toggle.count()) await toggle.click();
      await terminal(async t => { await t.chartToolsReady; });
      await openForm();
      const lum = await luminance();
      assert(mode === 'dark' ? lum < 0.5 : lum > 0.5, `${mode} form luminance ${lum}`);
      await closeForm();
    }
    if (await page.evaluate(() => document.fullscreenEnabled)) {
      await page.getByTitle('Full screen chart', { exact: true }).last().click();
      await page.waitForFunction(() => !!document.fullscreenElement);
      await openForm();
      // Only the fullscreen element's subtree is painted.
      if (!await form.evaluate(el => document.fullscreenElement?.contains(el) ?? true)) {
        hostFinding('The alert form opens outside the fullscreen chart, so it is not painted while the chart is fullscreen');
      }
      await page.evaluate(() => document.fullscreenElement && document.exitFullscreen());
      if (await form.count()) await closeForm();
    }
    assert.equal(orderCount(), ordersBefore);
  });
}
