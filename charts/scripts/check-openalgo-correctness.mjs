import assert from 'node:assert/strict';

/** Deterministic regressions for issue 2077, using the actual host and engine. */
export async function checkChartCorrectness({ page, terminal, report, sendDepth, screenshot }) {
  const failures = [];
  const check = async (name, run) => {
    try {
      await run();
      report.checks.push(name);
      console.log(`PASS ${name}`);
    } catch (error) {
      failures.push({ name, message: error.message });
      console.log(`FAIL ${name}: ${error.message}`);
    }
  };
  const moveToBar = async (back = 10) => {
    await page.mouse.move(0, 0);
    const point = await terminal((t, back) => {
      const bars = t.price.getData();
      const index = bars.length - back;
      const box = t.container.getBoundingClientRect();
      return { x: box.left + t.chart.timeScale.indexToX(index), y: box.top + 180, time: bars[index].time };
    }, back);
    await page.mouse.move(point.x, point.y);
    return point;
  };
  await page.mouse.move(0, 0);
  await terminal(async t => {
    t.link?.setOptions({ symbol: false, interval: false, viewport: false, crosshair: true });
    t.stopReplay();
    await t.loadSymbol({ symbol: 'BHEL', exchange: 'NSE' });
    t.setVolumeVisible(true);
    t.chart.resetScale();
  });
  await check('positive volume has a readable legend value', async () => {
    const value = await terminal(t => t.legendEl.querySelector('[data-legend-action="volume"]')?.textContent);
    assert.match(value ?? '', /^V \d/);
  });
  await check('zero volume remains a readable value', async () => {
    const value = await terminal(t => {
      const bar = { ...t.price.getData().at(-1), volume: 0 };
      return t.legendModel(bar).find(run => run.action === 'volume')?.text;
    });
    assert.match(value ?? '', /^V 0/);
  });
  await check('live ticks preserve the hovered candle readout', async () => {
    await terminal(t => t.addIndicatorById('compat-close'));
    const hovered = await moveToBar();
    assert.equal(await terminal(t => t.legendBar?.time), hovered.time, 'pointer must select a historical candle');
    const study = () => terminal(t => t.chart.indicators().find(i => i.indicatorId === 'compat-close').legend()._values);
    const before = await study();
    assert(before.length > 0, 'the study must have a visible value');
    await sendDepth('BHEL', 'NSE', 123.45);
    assert.equal(await terminal(t => t.legendBar?.time), hovered.time);
    assert.deepEqual(await study(), before, 'live ticks must preserve hovered study values');
    await page.mouse.move(0, 0);
    assert.equal(await terminal(t => t.legendBar?.time), await terminal(t => t.price.getData().at(-1).time));
  });
  await check('plot dragging preserves automatic price fitting', async () => {
    const drag = async (dx, dy) => {
      await terminal(t => t.chart.setAutoScale(true));
      const point = await moveToBar(15);
      await page.mouse.down();
      await page.mouse.move(point.x + dx, point.y + dy, { steps: 5 });
      await page.mouse.up();
      return terminal(t => t.chart.panes()[0].priceScale.autoScale);
    };
    // Moving through time alone never takes the price axis off Auto-fit.
    assert.equal(await drag(35, 0), true);
    // A drag that also moves vertically pans price only where the host's
    // "Mouse drag" setting says so. The host decides: OpenAlgo pinned it to
    // horizontal until it left the engine default, both, to the trader.
    const mousePan = await terminal(t => t.chart.navigationOptions().mousePan);
    assert.equal(await drag(35, 25), mousePan === 'horizontal', `mousePan is ${mousePan}`);
    await terminal(t => t.chart.setAutoScale(true));
  });
  await check('touchpad time panning preserves Auto-fit and the price axis still adjusts manually', async () => {
    await terminal(t => t.chart.setAutoScale(true));
    await moveToBar();
    await page.mouse.wheel(35, 0);
    assert.equal(await terminal(t => t.chart.panes()[0].priceScale.autoScale), true);
    const axis = await terminal(t => {
      const box = t.container.getBoundingClientRect();
      return { x: box.right - 15, y: box.top + 180 };
    });
    await page.mouse.move(axis.x, axis.y);
    await page.mouse.down();
    await page.mouse.move(axis.x, axis.y + 40, { steps: 5 });
    await page.mouse.up();
    assert.equal(await terminal(t => t.chart.panes()[0].priceScale.autoScale), false);
  });
  await check('index volume and its average stay hidden after settings and rebuild', async () => {
    await page.mouse.move(0, 0);
    await terminal(async t => {
      await t.loadSymbol({ symbol: 'NIFTY', exchange: 'NSE_INDEX' });
      await t.applyChartSettings({ 'volume.showMA': true });
      t.setVolumeVisible(true);
    });
    const view = await terminal(t => ({
      visible: t.chart.getState().series.filter(s => s.priceScaleId === '').map(s => s.style.visible),
      legend: t.legendModel(t.price.getData().at(-1)).some(run => run.action === 'volume'),
    }));
    assert(view.visible.length >= 2);
    assert(view.visible.every(value => value === false), JSON.stringify(view));
    assert.equal(view.legend, false);
    if (screenshot) await page.screenshot({ path: screenshot.replace(/\.png$/, '-index.png') });
  });
  await check('combined symbols retain the sum of distinct leg volumes', async () => {
    // A combination carries no exchange of its own: each leg names its own. The
    // host folds only an exchange-free request; with one, it asks the history
    // API for the expression as if it were a single instrument.
    await terminal(t => t.loadSymbol({ symbol: 'NSE:BHEL+NFO:NIFTY29SEP26FUT', exchange: '' }));
    await page.waitForFunction(() => window.__compatTerminals.some(t => !t.destroyed && t.sym?.symbol === 'NSE:BHEL+NFO:NIFTY29SEP26FUT'
      && !t.dataUnavailable() && Object.keys(t.exprFeed?.legBars ?? {}).length === 2));
    const view = await terminal(t => {
      const study = t.chart.addIndicator('volume');
      study.setSettings({ showMA: true, maPeriod: 3 });
      const values = study.values();
      const bars = t.price.getData();
      const result = {
        combined: bars.at(-1).volume,
        legs: Object.values(t.exprFeed.legBars).map(rows => rows.at(-1).volume),
        study: values.volume.at(-1), average: values.ma.at(-1),
        expectedAverage: bars.slice(-3).reduce((sum, bar) => sum + bar.volume, 0) / 3,
      };
      study.remove();
      return result;
    });
    assert(view.legs.every(value => Number.isFinite(value) && value > 0));
    assert.equal(view.combined, view.legs.reduce((sum, value) => sum + value, 0));
    assert.equal(view.study, view.combined);
    assert(Math.abs(view.average - view.expectedAverage) < 1e-8);
  });
  await check('linked crosshair updates the follower candle readout', async () => {
    await page.evaluate(() => {
      for (const t of window.__compatTerminals.filter(t => !t.destroyed)) t.setInterval('5m');
    });
    await page.waitForFunction(() => window.__compatTerminals.filter(t => !t.destroyed)
      .every(t => t.chart?.getDataContext()?.interval === '5m'));
    await page.evaluate(async () => {
      for (const t of window.__compatTerminals.filter(t => !t.destroyed)) {
        t.stopReplay();
        await t.loadSymbol({ symbol: 'BHEL', exchange: 'NSE' });
        t.chart.resetScale();
        await t.addIndicatorById('compat-close');
      }
    });
    await moveToBar();
    const views = await page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed).map(t => {
      const index = t.link.crosshairIndex(t.chart);
      const study = t.chart.indicators().find(i => i.indicatorId === 'compat-close');
      return { index, expected: index === null ? null : t.chart.dataLayer.indexToTime(index), actual: t.legendBar?.time,
        value: study.legend()._values[0]?.text, expectedValue: t.chart.panes()[0].priceScale.format(t.legendBar.close) };
    }));
    const followers = views.filter(view => view.index !== null);
    assert(followers.length > 0, `fixture must contain a linked follower: ${JSON.stringify(views)}`);
    for (const follower of followers) {
      assert.equal(follower.actual, follower.expected);
      assert.equal(follower.value, follower.expectedValue);
    }
    await page.mouse.move(0, 0);
    assert.equal(await page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed)
      .every(t => t.legendBar?.time === t.price.getData().at(-1).time)), true);
  });
  report.correctnessFailures = failures;
  assert.equal(failures.length, 0, JSON.stringify(failures, null, 2));
}
