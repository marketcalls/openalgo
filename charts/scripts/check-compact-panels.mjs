/** Real container-sized dialog regression, independent of desktop viewport width. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, firefox, webkit, expect } from '@playwright/test';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = resolve(process.argv[2] ?? 'artifacts/compact-panels');
const bundle = process.argv.includes('--baseline') ? 'dist-baseline' : 'dist';
await mkdir(output, { recursive: true });
const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, 'http://localhost').pathname;
    if (path === '/') {
      res.setHeader('content-type', 'text/html');
      res.end(`<!doctype html><html lang="en"><head><meta charset="utf-8"><style>body{margin:24px;background:#13141b}#host{width:350px;height:440px}</style></head><body><button id="open">Settings</button><div id="host"></div><script type="module">
      import * as base from '/${bundle}/openalgo-charts.mjs';
      import * as widgetLib from '/${bundle}/openalgo-charts.widget.mjs';
      import '/${bundle}/openalgo-charts.indicators.mjs';
      const {createWidget}=widgetLib;
      const widget = createWidget(document.querySelector('#host'),{topbar:false,statusline:false,rail:false,theme:'dark'});
      widget.series.setData(base.generateBars(1700000000,100,60));
      document.querySelector('#open').onclick=()=>widget.openSettings();
      window.compact={widget,base,widgetLib};
      </script></body></html>`);
      return;
    }
    const file = resolve(root, '.' + path);
    if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
    res.setHeader('content-type', extname(file) === '.mjs' ? 'text/javascript' : 'text/plain');
    res.end(await readFile(file));
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const url = `http://127.0.0.1:${server.address().port}`;
const failures = [];
try {
  for (const [engine, browserType] of Object.entries({ chromium, firefox, webkit })) {
    const browser = await browserType.launch();
    try {
      for (const [width, height] of [[350, 440], [700, 240], [350, 240]]) {
        const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
        try {
          await page.goto(url);
          await page.waitForFunction(() => window.compact);
          if (process.argv.includes('--source-css')) {
            const fragments = [];
            for (const [file, name] of [['src/widget/styles.ts', 'WIDGET_CSS'], ['src/widget/dialogs/index.ts', 'DIALOG_CSS']]) {
              const source = await readFile(resolve(root, file), 'utf8');
              const literal = source.match(new RegExp(`export const ${name} = (\x60[\\s\\S]*?\x60);`))[1];
              fragments.push(new Function('v', `return ${literal}`)(name => `var(--oac-${name})`));
            }
            await page.addStyleTag({ content: fragments.join('\n') });
          }
          await page.locator('#host').evaluate((node, size) => { node.style.width = size[0] + 'px'; node.style.height = size[1] + 'px'; }, [width, height]);
          await page.getByRole('button', { name: 'Settings', exact: true }).focus();
          await page.keyboard.press('Enter');
          const dialog = page.getByRole('dialog');
          await expect(dialog).toBeVisible();
          await page.screenshot({ path: `${output}/${engine}-${width}x${height}.png` });
          const bounds = await dialog.boundingBox();
          const host = await page.locator('#host').boundingBox();
          assert.ok(bounds.x >= host.x && bounds.x + bounds.width <= host.x + host.width, 'Dialog must fit host width');
          assert.ok(bounds.y >= host.y && bounds.y + bounds.height <= host.y + host.height, 'Dialog must fit host height');
          for (const tab of await dialog.getByRole('tab').all()) {
            await tab.click();
            const overflow = await dialog.evaluate(node => [...node.querySelectorAll('.oac-dialog__body,.oac-settings__pane,.oac-row')].filter(el => el.scrollWidth > el.clientWidth + 1).map(el => ({ className: el.className, text: el.textContent, width: el.clientWidth, scroll: el.scrollWidth, children: [...el.children].map(child => ({ className: child.className, width: child.getBoundingClientRect().width, min: getComputedStyle(child).minWidth })) })));
            assert.deepEqual(overflow, [], 'Every settings tab must fit without horizontal scrolling');
            const lastControl = dialog.locator('input:enabled,select:enabled,textarea:enabled').last();
            if (await lastControl.count()) {
              await lastControl.scrollIntoViewIfNeeded();
              const controlBounds = await lastControl.boundingBox();
              const bodyBounds = await dialog.locator('.oac-dialog__body').boundingBox();
              assert.ok(controlBounds.y >= bodyBounds.y - 1 && controlBounds.y + controlBounds.height <= bodyBounds.y + bodyBounds.height + 1, 'Last field remains reachable inside scrolling body');
            }
          }
          const ok = dialog.getByRole('button', { name: 'OK', exact: true });
          const foot = await ok.boundingBox();
          assert.ok(foot.y >= host.y && foot.y + foot.height <= host.y + host.height, 'Actions remain inside short host');
          if (!process.argv.includes('--baseline')) {
            const nav = dialog.getByRole('tablist');
            await expect(nav).toHaveAttribute('aria-orientation', 'horizontal');
            await nav.getByRole('tab').first().focus();
            await page.keyboard.press('ArrowRight');
            await expect(nav.getByRole('tab').nth(1)).toHaveAttribute('aria-selected', 'true');
            await page.locator('#host').evaluate(node => { node.style.width = '1000px'; });
            await expect(nav).toHaveAttribute('aria-orientation', 'vertical');
            await page.keyboard.press('ArrowUp');
            await expect(nav.getByRole('tab').first()).toHaveAttribute('aria-selected', 'true');
            await page.locator('#host').evaluate((node, value) => { node.style.width = value + 'px'; }, width);
            await expect(nav).toHaveAttribute('aria-orientation', 'horizontal');
          }
          await page.keyboard.press('Escape');
          await expect(dialog).toHaveCount(0);
          await expect(page.getByRole('button', { name: 'Settings', exact: true })).toBeFocused();
          await page.getByRole('button', { name: 'Settings', exact: true }).press('Enter');
          const before = await page.evaluate(() => window.compact.base.readChartSettings(window.compact.widget.chart));
          const color = page.getByRole('dialog').locator('input[type=color]').first();
          await color.fill('#ff0000');
          await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
          assert.deepEqual(await page.evaluate(() => window.compact.base.readChartSettings(window.compact.widget.chart)), before, 'Cancel restores live settings edits');
          await page.evaluate(() => window.compact.widget.openIndicatorPicker());
          const picker = page.locator('.oac-pick');
          const pickerBounds = await picker.boundingBox();
          assert.ok(pickerBounds.y >= host.y && pickerBounds.y + pickerBounds.height <= host.y + host.height, 'Picker fits short host');
          await expect(picker.getByRole('searchbox')).toBeVisible();
          await page.keyboard.press('Escape');
          await page.evaluate(() => {
            const {widget,widgetLib}=window.compact;
            const indicator=widget.chart.addIndicator('rsi');
            widgetLib.mountIndicatorSettings(widget.context,undefined,{instanceId:indicator.id});
          });
          const indicatorSettings = page.locator('.oac-indset');
          for (const tab of await indicatorSettings.getByRole('tab').all()) {
            await tab.click();
            assert.ok(await indicatorSettings.evaluate(node => node.scrollWidth <= node.clientWidth + 1));
          }
          await indicatorSettings.getByRole('button',{name:'OK',exact:true}).click();
          await page.evaluate(() => {
            const {widget,widgetLib}=window.compact;
            const bars=widget.series.getData();
            widget.draw.add({id:'compact-fib',tool:'fib-retracement',paneIndex:0,points:[{time:bars[20].time,price:bars[20].low},{time:bars[80].time,price:bars[80].high}]});
            widgetLib.mountLevelEditor(widget.context, undefined, {ids:['compact-fib']});
          });
          const levels = page.locator('.oac-levels');
          const levelBounds = await levels.boundingBox();
          assert.ok(levelBounds.x >= host.x && levelBounds.x + levelBounds.width <= host.x + host.width, 'Level editor fits narrow host');
          assert.ok(levelBounds.y >= host.y && levelBounds.y + levelBounds.height <= host.y + host.height, 'Level editor fits short host');
          await levels.screenshot({path: `${output}/${engine}-${width}x${height}-levels.png`});
          await page.keyboard.press('Escape');
          await page.evaluate(() => {
            const {widget,widgetLib}=window.compact;
            widgetLib.mountDrawingProperties(widget.context,undefined,{ids:['compact-fib']});
          });
          const props = page.locator('.oac-props');
          const propsBounds = await props.boundingBox();
          assert.ok(propsBounds.x >= host.x && propsBounds.x + propsBounds.width <= host.x + host.width, 'Drawing properties fit width');
          assert.ok(propsBounds.y >= host.y && propsBounds.y + propsBounds.height <= host.y + host.height, 'Drawing properties fit height');
          assert.ok(await props.evaluate(node => node.scrollWidth <= node.clientWidth + 1));
          await props.screenshot({path: `${output}/${engine}-${width}x${height}-drawing.png`});
          await page.keyboard.press('Escape');
          console.log(`${engine} ${width}x${height}: settings, indicators, picker, levels, drawing properties, Cancel and Escape focus passed`);
        } catch (error) { failures.push(`${engine} ${width}x${height}: ${error.message}`); }
        finally { await page.close(); }
      }
    } finally { await browser.close(); }
  }
} finally { await new Promise(resolve => server.close(resolve)); }
for (const failure of failures) console.error(failure);
assert.equal(failures.length, 0, 'Compact browser regressions must pass');
