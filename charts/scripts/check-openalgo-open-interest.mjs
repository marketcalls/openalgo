import assert from 'node:assert/strict';
import { expect } from '@playwright/test';

/** Exercise host metadata and persistence through the installed package and real page. */
export async function checkOpenInterest({ page, terminal, check, reload, sendDepth, screenshot, orderCount }) {
  const ordersBefore = orderCount();
  const closeDialog = async () => {
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-slot="dialog-overlay"]')).toHaveCount(0);
  };
  const openSettings = async () => {
    const point = await terminal(t => {
      const rect = t.container.getBoundingClientRect();
      return { x: rect.left + 120, y: rect.top + 120 };
    });
    await page.mouse.click(point.x, point.y, { button: 'right' });
    await page.getByText('Chart settings...', { exact: true }).click();
    await page.getByRole('button', { name: 'Readout', exact: true }).click();
  };
  const hoverZero = async () => {
    const point = await terminal(t => {
      const bars = t.price.getData(), index = bars.findIndex(bar => bar.oi === 0);
      if (index < 0) throw new Error('No genuine zero fixture');
      t.chart.resetScale();
      const rect = t.container.getBoundingClientRect();
      return { x: rect.left + t.chart.timeScale.indexToX(index), y: rect.top + 150, time: bars[index].time };
    });
    await page.mouse.move(point.x, point.y);
    await expect.poll(() => terminal(t => t.legendBar?.time)).toBe(point.time);
    assert.match(await terminal(t => t.legendEl.textContent), / OI 0(?:\s|$)/);
  };
  const studyIds = ['open-interest', 'open-interest-change', 'open-interest-buildup'];
  await check('OI history removes cash placeholders and preserves futures zero and gaps', async () => {
    await terminal(async t => { t.stopReplay(); await t.loadSymbol({ symbol: 'BHEL', exchange: 'NSE' }); });
    assert.deepEqual(await terminal(t => ({ capability: t.chart.hasOpenInterest, any: t.rawBars.some(bar => 'oi' in bar) })), { capability: false, any: false });
    await terminal(t => t.addIndicatorById('open-interest'));
    const unavailable = page.locator('[data-sonner-toast]').filter({ hasText: 'Open interest is not available for this instrument.' });
    await expect(unavailable).toBeVisible();
    assert.doesNotMatch(await unavailable.innerText(), /needs more history|Widen the range/);
    await unavailable.locator('[data-close-button]').click();
    await terminal(async (t, ids) => {
      await t.loadSymbol({ symbol: 'NIFTY29SEP26FUT', exchange: 'NFO' });
      t.setChartType('candlestick');
      await t.applyIndicatorTemplate(ids.map((indicatorId, index) => ({
        indicatorId, settings: {}, visible: true, paneIndex: index === 2 ? 0 : index + 1,
      })), 'replace');
    }, studyIds);
    const reading = await terminal(t => ({ capability: t.chart.hasOpenInterest,
      zero: t.rawBars.some(bar => bar.oi === 0), missing: t.rawBars.some(bar => !('oi' in bar)),
      raw: t.chart.indicators().find(study => study.indicatorId === 'open-interest').values().oi,
    }));
    assert.equal(reading.capability, true);
    assert(reading.zero && reading.missing && reading.raw.includes(null) && reading.raw.includes(0));
    await openSettings();
    const setting = page.getByRole('checkbox', { name: 'Open interest', exact: true });
    await setting.check();
    await page.getByRole('button', { name: 'Ok', exact: true }).click();
    await closeDialog();
    await hoverZero();
    if (screenshot) await page.screenshot({ path: screenshot.replace(/\.png$/, '-oi-studies.png') });
  });

  await check('OI live gaps do not overwrite the hovered historical reading', async () => {
    await sendDepth('NIFTY29SEP26FUT', 'NFO', 123.45);
    assert.match(await terminal(t => t.legendEl.textContent), / OI 0(?:\s|$)/);
    await page.mouse.move(0, 0);
    assert.equal(await terminal(t => t.price.getData().at(-1).oi), undefined);
    assert.doesNotMatch(await terminal(t => t.legendEl.textContent), / OI /);
    assert.equal(await terminal(t => t.chart.hasOpenInterest), true);
  });

  await check('OI settings survive unsupported cash and crypto spot instrument changes', async () => {
    await terminal(t => t.loadSymbol({ symbol: 'BHEL', exchange: 'NSE' }));
    await openSettings();
    const setting = page.getByRole('checkbox', { name: 'Open interest', exact: true });
    await expect(setting).toBeChecked();
    await expect(setting).toBeDisabled();
    if (screenshot) await page.screenshot({ path: screenshot.replace(/\.png$/, '-oi-unavailable.png') });
    await closeDialog();
    await terminal(t => t.loadSymbol({ symbol: 'BTCUSD', exchange: 'CRYPTO' }));
    assert.deepEqual(await terminal(t => ({ capability: t.chart.hasOpenInterest, any: t.rawBars.some(bar => 'oi' in bar) })), { capability: false, any: false });
    await terminal(t => t.loadSymbol({ symbol: 'BTCUSD.P', exchange: 'CRYPTO' }));
    assert.deepEqual(await terminal(t => ({ capability: t.chart.hasOpenInterest, zero: t.rawBars.some(bar => bar.oi === 0) })), { capability: true, zero: true });
    await hoverZero();
  });

  await check('OI studies and preferences restore through a complete named workspace', async () => {
    await terminal(t => t.loadSymbol({ symbol: 'NIFTY29SEP26FUT', exchange: 'NFO' }));
    await expect.poll(() => terminal(t => t.chart.indicators().map(study => study.indicatorId))).toEqual(studyIds);
    await page.getByRole('button', { name: 'Workspaces', exact: true }).click();
    await page.getByLabel('Workspace name', { exact: true }).fill('Open interest research');
    await page.getByRole('button', { name: 'Save as', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Workspace saved' }).waitFor();
    await closeDialog();
    await reload();
    await page.waitForFunction(() => {
      const t = window.__compatTerminals?.findLast(t => !t.destroyed && t.chart);
      return document.querySelector('[data-workspace-active="true"]') && t?.chart.indicators().some(study => study.indicatorId === 'open-interest');
    });
    assert.deepEqual(await terminal(t => t.chart.indicators().map(study => study.indicatorId)), studyIds);
    assert.equal(await terminal(t => t.chart.hasOpenInterest), true);
    assert.equal(await terminal(t => t.chart.statusLineOptions().openInterest), true);
    await hoverZero();
    if (screenshot) await page.screenshot({ path: screenshot.replace(/\.png$/, '-oi-workspace.png') });
    assert.equal(orderCount(), ordersBefore);
  });
}
