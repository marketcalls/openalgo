/**
 * Consumer acceptance extension for Charts scripts/check-openalgo-compat.mjs.
 * Pass --consumer-checks <this absolute path> --frontend <isolated frontend>.
 * All HTTP and WebSocket traffic uses the parent runner's deterministic mocks.
 * The runner serves the actual application source and installed Charts package.
 */
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

export async function checkTradingWorkspace({ page, check, expect, report, reload, sendDepth, sendLtp, waitForSubscription, screenshot, output, orderCount }) {
  const startOrderCount = orderCount();
  const orderWrites = () => report.requests.filter(request => /\/(?:placeorder|placesmartorder|modifyorder|cancelorder|cancelallorder|closeposition)$/.test(request.path));
  const startWrites = orderWrites().length;
  const artifact = suffix => resolve((output ?? screenshot ?? 'consumer-workspace.json').replace(/\.(?:json|png)$/, '') + suffix);
  const evidence = report.workspaceFeatures = { startedAt: new Date().toISOString(), frames: [], downloads: [], rendering: [] };
  const toolbar = () => page.getByRole('toolbar', { name: 'Chart controls' });
  const replayBar = () => page.getByRole('region', { name: 'Workspace replay' });
  const live = (fn, arg) => page.evaluate(({ source, arg }) => {
    const terminals = window.__compatTerminals.filter(item => !item.destroyed && item.chart);
    return (0, eval)(`(${source})`)(terminals, arg);
  }, { source: fn.toString(), arg });
  const ready = () => page.waitForFunction(() => {
    const terminals = window.__compatTerminals.filter(item => !item.destroyed && item.chart);
    return terminals.length === 2 && !document.querySelector('[data-workspace-active="false"]') && terminals.every(t => {
      const context = t.chart.getDataContext();
      return !t.dataUnavailable() && t.price.getData().length > 10 && context?.symbol === t.sym.symbol && context.interval === t.interval;
    });
  });
  const focus = async index => {
    const id = await live((terminals, index) => {
      const terminal = terminals[index];
      terminal.container.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
      return terminal.sk.replace('oa-trading-', '');
    }, index);
    await expect(toolbar()).toHaveAttribute('data-toolbar-pane', id);
    return id;
  };
  const close = async () => {
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]') && getComputedStyle(document.body).pointerEvents !== 'none');
  };
  const menu = async () => {
    await page.getByRole('button', { name: 'Workspaces', exact: true }).click();
    await page.getByRole('dialog', { name: 'Chart workspaces' }).waitFor();
    await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeEnabled();
  };
  const catalog = () => page.evaluate(() => new Promise((resolve, reject) => {
    const request = indexedDB.open('openalgo-chart-workspaces', 1);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result, transaction = db.transaction('catalogs', 'readonly');
      const read = transaction.objectStore('catalogs').get('oa-trading:compat');
      transaction.oncomplete = () => { db.close(); resolve(read.result); };
      transaction.onabort = () => { db.close(); reject(transaction.error); };
    };
  }));
  const capture = () => live(terminals => terminals.map(t => t.captureWorkspacePane(t.sk.replace('oa-trading-', ''))));
  const state = () => page.evaluate(() => window.__workspaceReplayEvidence.state());
  const observeCoordinator = () => page.evaluate(async () => {
    const { WorkspaceReplayCoordinator } = await import('/src/lib/trading/workspaceReplay.ts');
    const prototype = WorkspaceReplayCoordinator.prototype;
    if (window.__workspaceOriginalStart) return;
    const original = prototype.start;
    window.__workspaceOriginalStart = original;
    prototype.start = function(...args) {
      window.__workspaceReplayEvidence = this;
      return original.apply(this, args);
    };
  });
  const render = async label => {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const samples = await live(terminals => terminals.map(t => {
      const canvases = [...t.container.querySelectorAll('canvas')].filter(canvas => canvas.width > 100 && canvas.height > 100);
      return canvases.map(canvas => {
        const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        const colors = new Set();
        for (let index = 0; index < data.length; index += 4 * 31) {
          if (data[index + 3]) colors.add(`${data[index]},${data[index + 1]},${data[index + 2]},${data[index + 3]}`);
        }
        return { width: canvas.width, height: canvas.height, colors: colors.size };
      });
    }));
    assert(samples.every(canvases => canvases.some(canvas => canvas.colors > 8)), 'Each chart must contain rendered chart pixels');
    evidence.rendering.push({ label, samples });
    if (screenshot) await page.screenshot({ path: resolve(screenshot.replace(/\.png$/, `-${label}.png`)), fullPage: true, animations: 'disabled' });
  };
  const downloadCsv = async label => {
    const expected = await live(terminals => {
      const id = document.querySelector('[data-toolbar-pane]').getAttribute('data-toolbar-pane');
      const t = terminals.find(item => item.sk === `oa-trading-${id}`);
      return { csv: t.exportDataCsv(), bars: t.chart.primaryBars().map(bar => ({ ...bar })), comparisons: t.comparisonState().items.length };
    });
    await toolbar().getByRole('button', { name: 'Chart snapshot', exact: true }).click();
    const pending = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download CSV', exact: true }).click();
    const file = await pending;
    const csv = await readFile(await file.path(), 'utf8');
    assert.equal(csv, expected.csv, 'Downloaded CSV must come from the selected real chart');
    assert.match(file.suggestedFilename(), /^[a-zA-Z0-9._-]+\.csv$/);
    const lines = csv.trimEnd().split('\r\n');
    const header = lines.shift().split(',');
    assert.deepEqual(header.slice(0, 7), ['time', 'open', 'high', 'low', 'close', 'volume', 'oi']);
    assert.equal(header.filter(value => value.startsWith('comparison:')).length, expected.comparisons);
    assert.equal(lines.length, expected.bars.length);
    for (let index = 0; index < lines.length; index++) {
      const cells = lines[index].split(',');
      for (let field = 0; field < 7; field++) {
        const value = expected.bars[index][header[field]];
        assert.equal(cells[field], Number.isFinite(value) ? String(value) : '', `CSV ${header[field]} row ${index} differs from displayed data`);
      }
    }
    const path = artifact(`-${label}.csv`);
    await writeFile(path, csv);
    evidence.downloads.push({ label, path, rows: lines.length, header });
    return { bars: expected.bars, header, lines };
  };
  const rejectTrading = async () => {
    const refusals = await live(async terminals => Promise.all(terminals.map(async t => {
      try { await t.placeTicket({}); return null; } catch (error) { return error.message; }
    })));
    assert(refusals.every(message => /Replay/.test(message)), 'Every visible chart must refuse trading throughout replay');
    assert.equal(orderWrites().length, startWrites);
  };
  // Negative persistence assertions must cross the documented 600 ms debounce.
  // This is a protocol boundary, not a chart/network readiness delay.
  const crossAutosaveDebounce = () => page.evaluate(() => new Promise(resolve => {
    setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(resolve)), 600);
  }));
  const assertFrame = async label => {
    const snapshot = await state();
    assert.equal(snapshot.phase, 'active');
    const clock = snapshot.state.time;
    assert(Number.isFinite(clock));
    const members = await live(terminals => terminals.map(t => ({
      id: t.sk.replace('oa-trading-', ''), interval: t.interval, active: t.replayActive(),
      bars: t.price.getData().map(bar => ({ ...bar })), state: t.replayState(),
      finer: t.replaySub?.bars.map(bar => ({ ...bar })) ?? [],
      comparisons: [...(t.comparisons?.entries.values() ?? [])].map(entry => ({
        bars: entry.handle.series.getData(), future: entry.handle.barAt(t.rawBars.at(-1).time),
      })),
    })));
    for (const member of members.filter(item => item.active)) {
      const seconds = Number(member.interval.slice(0, -1)) * 60;
      for (const bar of member.bars) assert(bar.time < clock, 'No bar may open at or beyond the shared UTC availability');
      for (const bar of member.bars.slice(0, -1)) assert(bar.time + seconds <= clock, 'Completed bars must be available at the shared clock');
      const last = member.bars.at(-1);
      if (last && last.time + seconds > clock) {
        // Declared fixture: 5m uses 1m observations, 15m uses 5m observations.
        const finerSeconds = { '5m': 60, '15m': 300 }[member.interval];
        assert(finerSeconds, 'The browser workload must declare each finer interval');
        const available = member.finer.filter(bar => bar.time >= last.time && bar.time + finerSeconds <= clock && bar.time < last.time + seconds);
        assert(available.length, 'A forming bar needs observed finer candles');
        assert.equal(last.close, available.at(-1).close);
        assert.equal(last.high, Math.max(...available.map(bar => bar.high)));
        assert.equal(last.low, Math.min(...available.map(bar => bar.low)));
      }
      assert.deepEqual(last ?? null, member.state.bar);
      for (const comparison of member.comparisons) {
        assert.equal(comparison.future, null, 'Comparison lookup must conceal unrevealed future data');
        assert(comparison.bars.every(bar => !last || bar.time <= last.time), 'Comparison timeline cannot extend beyond the displayed prefix');
      }
    }
    evidence.frames.push({ label, clock, index: snapshot.state.index, scope: snapshot.scope,
      members: members.map(member => ({ id: member.id, interval: member.interval, active: member.active, count: member.bars.length, last: member.bars.at(-1) })) });
    return snapshot;
  };
  let saved, originalMode, ownerId;
  try {
    await check('consumer comparison add, percentage scale and real rendering stay on the selected chart', async () => {
      await page.getByRole('button', { name: /^Chart layout:/ }).click();
      await page.getByTitle('2 columns', { exact: true }).click();
      await ready();
      await page.getByRole('button', { name: 'Chart sync', exact: true }).click();
      for (const name of ['Interval', 'Time range']) {
        const control = page.getByRole('checkbox', { name, exact: true });
        if (await control.isChecked()) await control.click();
      }
      await page.keyboard.press('Escape');
      await live(async terminals => {
        for (const [index, t] of terminals.entries()) {
          t.stopReplay();
          for (const item of t.comparisonState().items) t.removeComparison(item.id);
          await t.loadSymbol(index === 0 ? { symbol: 'BHEL', exchange: 'NSE' } : { symbol: 'NIFTY', exchange: 'NSE_INDEX' });
          t.setChartType('candlestick');
          t.setInterval(index === 0 ? '5m' : '15m');
        }
      });
      await ready();
      await live(async terminals => {
        await terminals[0].applyIndicatorTemplate([{ indicatorId: 'ema', settings: { length: 9 }, paneIndex: 0, visible: true }], 'replace');
        terminals[0].chart.setPriceScaleOptions({ mode: 'logarithmic' });
      });
      originalMode = await live(terminals => terminals[0].price.priceScale().options.mode);
      assert.equal(originalMode, 'logarithmic');
      ownerId = await focus(0);
      await toolbar().getByRole('button', { name: 'Comparisons', exact: true }).click();
      await page.getByRole('button', { name: 'Add comparison', exact: true }).click();
      await page.getByRole('textbox', { name: 'Search comparison symbol' }).fill('NIFTY');
      await page.getByRole('dialog', { name: 'Add comparison symbol' }).getByRole('button').filter({ hasText: 'Nifty 50' }).click();
      await page.waitForFunction(() => {
        const t = window.__compatTerminals.filter(item => !item.destroyed && item.chart)[0];
        return t.comparisonState().items.length === 1 && t.comparisonState().items[0].status === 'ready';
      });
      await page.getByLabel('Comparison scale', { exact: true }).selectOption('percentage');
      assert.deepEqual(await live(terminals => terminals.map(t => t.comparisonState().items.length)), [1, 0]);
      assert.equal(await live(terminals => terminals[0].price.priceScale().options.mode), 'percentage');
      await page.keyboard.press('Escape');
      // The main index chart and its independent comparison each subscribe to LTP.
      await waitForSubscription('NIFTY', 'NSE_INDEX', 1, 2);
      await sendLtp('NIFTY', 'NSE_INDEX', 123.25);
      await page.waitForFunction(() => {
        const t = window.__compatTerminals.filter(item => !item.destroyed && item.chart)[0];
        return t.comparisons.rows().some(row => row.close === 123.25);
      });
      await render('comparisons');
      const csv = await downloadCsv('live');
      assert(csv.header.some(value => value.startsWith('indicator:')));
      const compared = csv.header.findIndex(value => value.startsWith('comparison:'));
      assert.equal(Number(csv.lines.at(-1).split(',')[compared]), 123.25, 'Percentage display must export comparison prices in their original units');
    });

    await check('consumer portable comparisons round trip and removal restores the original price scale', async () => {
      await menu();
      const auto = page.getByRole('checkbox', { name: 'Autosave chart changes' });
      if (await auto.isChecked()) await auto.click();
      await page.getByLabel('Workspace name', { exact: true }).fill('Consumer comparison replay');
      await page.getByRole('button', { name: 'Save as', exact: true }).click();
      await page.getByRole('status').filter({ hasText: 'Workspace saved' }).waitFor();
      const pending = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Export JSON', exact: true }).click();
      saved = JSON.parse(await readFile(await (await pending).path(), 'utf8'));
      assert.equal(saved.panes[0].comparisons.length, 1);
      assert.equal(saved.panes[0].comparisonMode, 'percent');
      assert.equal(saved.panes[0].chart.panes[0].priceScale.mode, originalMode);
      assert(!/"(?:apikey|apiKey|armed|orders|positions)"\s*:/.test(JSON.stringify(saved)));
      await writeFile(artifact('-portable.json'), `${JSON.stringify(saved, null, 2)}\n`);
      await close();
      await toolbar().getByRole('button', { name: 'Comparisons', exact: true }).click();
      await page.getByRole('button', { name: 'Remove NSE_INDEX:NIFTY', exact: true }).click();
      assert.equal(await live(terminals => terminals[0].price.priceScale().options.mode), originalMode);
      await page.keyboard.press('Escape');
      await menu();
      await page.getByLabel('Saved workspace', { exact: true }).selectOption({ label: saved.name });
      await page.getByRole('button', { name: 'Open', exact: true }).click();
      await ready();
      await close();
      await reload();
      await ready();
      await page.waitForFunction(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart)[0].comparisonState().items[0]?.status === 'ready');
      const restored = await capture();
      assert.deepEqual(restored.map(pane => pane.comparisons), saved.panes.map(pane => pane.comparisons));
      assert.deepEqual(restored.map(pane => pane.comparisonMode), saved.panes.map(pane => pane.comparisonMode));
      assert.equal(await live(terminals => terminals[0].price.priceScale().options.mode), 'percentage');
      await focus(0);
      await toolbar().getByRole('button', { name: 'Comparisons', exact: true }).click();
      await page.getByRole('button', { name: 'Remove NSE_INDEX:NIFTY', exact: true }).click();
      assert.equal(await live(terminals => terminals[0].price.priceScale().options.mode), originalMode, 'Restored comparison must retain original scale ownership');
      await page.keyboard.press('Escape');
      await menu();
      await page.getByLabel('Saved workspace', { exact: true }).selectOption({ label: saved.name });
      await page.getByRole('button', { name: 'Open', exact: true }).click();
      await ready();
      await close();
      await page.waitForFunction(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart)[0].comparisonState().items[0]?.status === 'ready');
      ownerId = await focus(0);
    });

    await check('consumer replay picking captures owner, shades all scope, blocks trading and cancels dirty autosave', async () => {
      await observeCoordinator();
      await menu();
      const auto = page.getByRole('checkbox', { name: 'Autosave chart changes' });
      if (!(await auto.isChecked())) await auto.click();
      await expect.poll(async () => (await catalog()).autosave).toBe(true);
      await close();
      const before = await catalog();
      const volume = before.workspaces.find(item => item.id === saved.id).panes[0].volume;
      // Queue a real configuration save, then enter replay in the same event turn.
      await live((terminals, volume) => {
        terminals[0].setVolumeVisible(!volume);
        document.querySelector('[data-toolbar-pane] button[title="Replay this session from a bar you pick"]').click();
      }, volume);
      await expect(replayBar()).toBeVisible();
      assert.equal((await state()).phase, 'picking');
      assert.equal((await state()).ownerId, ownerId);
      await rejectTrading();
      await replayBar().getByLabel('Replay scope').selectOption('all');
      await live(terminals => terminals[0].moveReplayPick(12));
      assert.deepEqual(await live(terminals => terminals.map(t => t.replayPickingBar())), [true, false]);
      assert.equal(await live(terminals => terminals[1].replayShades[0]._opts.index), 3, 'Follower preview must use 15 minute availability, not the owner logical index');
      await focus(1);
      assert.equal((await state()).ownerId, ownerId, 'Toolbar focus must not transfer replay ownership');
      await toolbar().getByRole('button', { name: 'Chart snapshot', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Download CSV', exact: true })).toBeDisabled();
      await toolbar().getByRole('button', { name: 'Chart snapshot', exact: true }).click({ force: true });
      await crossAutosaveDebounce();
      assert.equal((await catalog()).revision, before.revision, 'Queued autosave must not persist during picking');
      await replayBar().getByRole('button', { name: 'Cancel replay', exact: true }).click();
      await expect(replayBar()).toHaveCount(0);
      await expect.poll(async () => (await catalog()).workspaces.find(item => item.id === saved.id).panes[0].volume).toBe(!volume);
      assert.deepEqual(await live(terminals => terminals.map(t => [t.workspaceReplayLocked, t.replayPickingBar(), t.replayActive()])), [[false, false, false], [false, false, false]]);
      assert(await live(terminals => terminals.every(t => t.replayShades.every(shade => shade._opts.index === null))));
      await focus(0);
    });

    await check('consumer shared replay aligns focused and all scope by UTC and exports only the revealed CSV prefix', async () => {
      await toolbar().getByRole('button', { name: 'Replay', exact: true }).click();
      await replayBar().getByLabel('Replay scope').selectOption('focused');
      await live(terminals => { terminals[0].moveReplayPick(12); terminals[0].commitReplayPick(); });
      await page.waitForFunction(() => window.__workspaceReplayEvidence.state().phase === 'active');
      assert.deepEqual(await live(terminals => terminals.map(t => t.replayActive())), [true, false]);
      await rejectTrading();
      await assertFrame('focused');
      const before = await catalog();
      await replayBar().getByLabel('Replay scope').selectOption('all');
      assert.deepEqual(await live(terminals => terminals.map(t => t.replayActive())), [true, true]);
      const aligned = await assertFrame('all');
      assert.equal(aligned.ownerId, ownerId);
      await replayBar().getByRole('button', { name: 'Next observation', exact: true }).click();
      const advanced = await assertFrame('all-next');
      assert(advanced.state.time > aligned.state.time);
      await replayBar().getByRole('button', { name: 'Previous observation', exact: true }).click();
      assert.equal((await assertFrame('all-previous')).state.time, aligned.state.time);
      const prefix = await downloadCsv('replay');
      assert(prefix.bars.length < await live(terminals => terminals[0].rawBars.length));
      assert(prefix.bars.every(bar => bar.time < aligned.state.time));
      await render('shared-replay');
      await replayBar().getByRole('button', { name: 'Play', exact: true }).click();
      await expect.poll(async () => (await state()).state.index).toBeGreaterThan(aligned.state.index);
      await replayBar().getByRole('button', { name: 'Pause', exact: true }).click();
      assert.equal((await state()).state.playing, false);
      await crossAutosaveDebounce();
      assert.equal((await catalog()).revision, before.revision, 'Replay transport must not autosave truncated chart state');
      const frozen = await live(terminals => terminals.map(t => t.price.getData()));
      await sendDepth('BHEL', 'NSE', 151.25);
      await sendLtp('NIFTY', 'NSE_INDEX', 152.5);
      assert.deepEqual(await live(terminals => terminals.map(t => t.price.getData())), frozen, 'Buffered live ticks must not overwrite replay');
      await replayBar().getByLabel('Replay scope').selectOption('focused');
      assert.deepEqual(await live(terminals => terminals.map(t => t.replayActive())), [true, false]);
      assert.equal(await live(terminals => terminals[1].price.getData().at(-1).close), 152.5);
      await sendLtp('NIFTY', 'NSE_INDEX', 153.75);
      await replayBar().getByLabel('Replay scope').selectOption('all');
      await assertFrame('all-reentry');
      await replayBar().getByRole('button', { name: 'Stop replay', exact: true }).click();
      await page.getByRole('dialog', { name: 'Leave replay?' }).getByRole('button', { name: 'Stay', exact: true }).click();
      assert.equal((await state()).phase, 'active');
      await replayBar().getByRole('button', { name: 'Stop replay', exact: true }).click();
      await page.getByRole('dialog', { name: 'Leave replay?' }).getByRole('button', { name: 'Leave', exact: true }).click();
      await expect(replayBar()).toHaveCount(0);
      assert.deepEqual(await live(terminals => terminals.map(t => t.price.getData().at(-1).close)), [151.25, 153.75]);
      assert.deepEqual(await live(terminals => terminals.map(t => t.workspaceReplayLocked)), [false, false]);
      await ready();
      await render('live-restored');
    });

    await check('consumer workspace interactions issue no broker writes or late replay orders', async () => {
      await crossAutosaveDebounce();
      assert.equal(orderCount(), startOrderCount);
      assert.equal(orderWrites().length, startWrites);
      assert.equal((await state()).phase, 'idle');
      evidence.finishedAt = new Date().toISOString();
    });
  } catch (error) {
    evidence.failure = error.stack ?? String(error);
    evidence.terminals = await live(terminals => terminals.map(t => ({ key: t.sk, interval: t.interval, symbol: t.sym?.symbol,
      picking: t.replayPickingBar(), loading: t.replayLoadingBars(), replay: t.replayState(), comparisons: t.comparisonState() }))).catch(() => []);
    if (screenshot) await page.screenshot({ path: resolve(screenshot.replace(/\.png$/, '-consumer-failure.png')), fullPage: true }).catch(() => {});
    throw error;
  } finally {
    await page.evaluate(async () => {
      if (window.__workspaceOriginalStart) {
        const { WorkspaceReplayCoordinator } = await import('/src/lib/trading/workspaceReplay.ts');
        WorkspaceReplayCoordinator.prototype.start = window.__workspaceOriginalStart;
        delete window.__workspaceOriginalStart;
      }
    }).catch(() => {});
  }
}
