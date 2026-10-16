import { expect, test, type Page } from '@playwright/test';
import type { Bar, Chart, IndicatorApi, PaneLegend } from '../../src/index';
import type { Widget } from '../../src/widget/widget';
import type * as Charts from '../../src/index';
import type * as Widgets from '../../src/widget/index';

test.use({ hasTouch: true });

declare global {
  interface Window {
    __chartPreferences: {
      widget: Widget; chart: Chart; studies: IndicatorApi[]; bars: Bar[]; hostLegend: PaneLegend;
      settings(tab: 'axes'|'readout'): void;
    };
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function initialize(page: Page) {
  await page.evaluate(async () => {
    const baseUrl='/dist/openalgo-charts.mjs',widgetUrl='/dist/openalgo-charts.widget.mjs';
    const lib=await import(baseUrl) as typeof Charts,widgets=await import(widgetUrl) as typeof Widgets;
    lib.registerIndicator({ id:'preference-near',name:'Nearby study',placement:'onchart',inputs:[],
      plots:[{key:'upper',title:'Upper',type:'line',style:{color:'#ffcc44',lineWidth:3}},
        {key:'lower',title:'Lower',type:'line',style:{color:'#ffcc44',lineWidth:3}}],
      calc:bars=>({upper:bars.map(bar=>bar.close+3),lower:bars.map(bar=>bar.close-3)}),
    });
    lib.registerIndicator({ id:'preference-far',name:'Distant study',placement:'onchart',inputs:[],
      plots:[{key:'far',title:'Far',type:'line',style:{color:'#dd66cc',lineWidth:3}}],
      calc:bars=>({far:bars.map(bar=>bar.close+10000)}),
    });
    const widget=widgets.createWidget(document.getElementById('host')!,{
      persist:'browser-chart-preferences',rail:false,symbol:'SYNTH',interval:'1m',
      branding:false,animZoom:false,animAutoscale:false,timeNavigator:false,
      mobile:window.innerWidth<=640?'auto':'never',
    });
    // The saved preferences land once the widget's store (IndexedDB) has answered.
    await widget.ready;
    const chart=widget.chart;
    const bars=Array.from({length:96},(_,index)=>{
      const close=100+index*3+(index>=48?250:0);
      return {time:1700000040+index*60,open:close-4,high:close+2,low:close-6,close};
    });
    widget.series.applyOptions({upColor:'#33aaff',downColor:'#33aaff'});
    widget.series.setData(bars);
    const hostLegend=new lib.PaneLegend({id:'preference-host',title:'Host quote',actions:[]});
    hostLegend.setValues([{text:'O 631 H 637 L 629 C 635',field:'ohlc'}]);
    chart.addPrimitive(hostLegend);
    if (!chart.indicators().length) {
      chart.addIndicator('preference-near'); chart.addIndicator('preference-far');
    }
    chart.setVisibleLogicalRange({from:4,to:28});
    window.__chartPreferences={widget,chart,bars,hostLegend,studies:[...chart.indicators()],
      settings:tab=>{ widgets.mountSettingsDialog(widget.context,undefined,{tab}); }};
  });
  await paint(page);
}

async function mount(page: Page,width: number) {
  const errors: string[]=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.setViewportSize({width,height:820});
  await page.route('**/native-chart-preferences.html',route=>route.fulfill({contentType:'text/html',body:
    '<!doctype html><html><head><style>html,body{margin:0;background:#111318}#host{height:800px;width:100%}</style></head><body><div id="host"></div></body></html>'}));
  await page.goto('/native-chart-preferences.html');
  await initialize(page);
  return errors;
}

async function measurements(page: Page) {
  return page.evaluate(()=>{
    const {chart,studies,widget}=window.__chartPreferences,pane=chart.panes()[0],canvas=pane.base.element;
    const scale=canvas.width/canvas.getBoundingClientRect().width;
    const pixels=canvas.getContext('2d')!.getImageData(0,0,canvas.width,canvas.height).data;
    let blue=0,yellow=0,minY=Infinity,maxY=-Infinity;
    for (let y=Math.ceil(105*scale);y<canvas.height-30*scale;y++) {
      for (let x=Math.ceil(3*scale);x<(chart.timeScale.width-3)*scale;x++) {
        const i=4*(y*canvas.width+x),r=pixels[i],g=pixels[i+1],b=pixels[i+2];
        if (r===51&&g===170&&b===255) { blue++;minY=Math.min(minY,y);maxY=Math.max(maxY,y); }
        if (r===255&&g===204&&b===68) yellow++;
      }
    }
    return {range:widget.series.priceScale().priceRange(),view:chart.getVisibleLogicalRange(),
      priceOnly:chart.priceOnlyAutoScale(),collapsed:chart.indicatorLegendCollapsed(),
      blue,yellow,blueSpan:blue?(maxY-minY)/scale:0,
      retained:chart.indicators().every((study,index)=>study===studies[index]),
      visible:studies.map(study=>study.visible()),base:canvas.toDataURL()};
  });
}

async function legendTexts(page: Page) {
  return page.evaluate(()=>{
    const chart=window.__chartPreferences.chart;
    const svg=new DOMParser().parseFromString(chart.exportSVG(),'image/svg+xml').documentElement as unknown as SVGSVGElement;
    svg.style.cssText='position:absolute;left:0;top:0;visibility:hidden;pointer-events:none'; document.body.appendChild(svg);
    try {
      return [...svg.querySelectorAll<SVGTextElement>('text')].map(text=>{
        const box=text.getBBox(),matrix=text.getCTM()!;
        const point=new DOMPoint(box.x+Math.min(box.width/2,20),box.y+box.height/2).matrixTransform(matrix);
        return {text:text.textContent??'',x:point.x,y:point.y};
      });
    } finally { svg.remove(); }
  });
}

async function tapCount(page: Page) {
  const count=(await legendTexts(page)).find(row=>row.text==='Indicators 2');
  expect(count).toBeDefined();
  const rect=await page.locator('.oac-chart').boundingBox();
  await page.touchscreen.tap(rect!.x+count!.x,rect!.y+count!.y);
  await paint(page);
}

for (const width of [1100,390]) {
  test(`price-only fit uses primary pixels and follows navigation at ${width}px`,async ({page},info)=>{
    const errors=await mount(page,width),combined=await measurements(page);
    expect(combined.range.max).toBeGreaterThan(10000);
    const axis=await page.evaluate(()=>{
      const chart=window.__chartPreferences.chart,slot=chart.priceAxisLayout(0).find(axis=>axis.scaleId==='right')!;
      const rect=chart.panes()[0].base.element.getBoundingClientRect();
      return {x:rect.left+slot.x+slot.width/2,y:rect.top+230};
    });
    await page.mouse.click(axis.x,axis.y,{button:'right'});
    const choice=page.getByRole('menuitemcheckbox',{name:'Fit primary prices only',exact:true});
    await expect(choice).toHaveAttribute('aria-checked','false'); await choice.click();
    await expect(choice).toHaveAttribute('aria-checked','true'); await page.keyboard.press('Escape');
    await paint(page);
    const fitted=await measurements(page);
    expect(fitted.priceOnly).toBe(true); expect(fitted.range.max).toBeLessThan(250);
    expect(fitted.blueSpan).toBeGreaterThan(combined.blueSpan+150);
    expect(fitted.blue).toBeGreaterThan(100); expect(fitted.yellow).toBeGreaterThan(100);
    expect(fitted.retained).toBe(true); expect(fitted.visible).toEqual([true,true]);
    await page.screenshot({path:info.outputPath(`price-only-${width}.png`)});
    await page.evaluate(()=>window.__chartPreferences.chart.setVisibleLogicalRange({from:54,to:78}));
    await paint(page);
    const later=await measurements(page);
    expect(later.range.min).toBeGreaterThan(fitted.range.max+100); expect(later.range.max).toBeLessThan(1000);
    const box=await page.locator('.oac-chart').boundingBox();
    await page.mouse.move(box!.x+width*0.6,box!.y+300);
    await page.mouse.down(); await page.mouse.move(box!.x+width*0.3,box!.y+300,{steps:8}); await page.mouse.up();
    await paint(page);
    const panned=await measurements(page);
    expect(panned.view.from).not.toBe(later.view.from); expect(panned.range).not.toEqual(later.range);
    expect(panned.range.max).toBeLessThan(1000); expect(panned.retained).toBe(true);
    await page.screenshot({path:info.outputPath(`price-only-panned-${width}.png`)});
    await page.evaluate(()=>window.__chartPreferences.chart.setPriceOnlyAutoScale(false)); await paint(page);
    expect((await measurements(page)).range.max).toBeGreaterThan(10000);
    expect(errors).toEqual([]);
  });

  test(`touch count collapses only study rows and keeps live plots at ${width}px`,async ({page},info)=>{
    const errors=await mount(page,width);
    await page.evaluate(()=>{
      const chart=window.__chartPreferences.chart; chart.setPriceOnlyAutoScale(true);
      chart.setVisibleLogicalRange({from:68,to:98});
    });
    await paint(page);
    const initial=await measurements(page),texts=await legendTexts(page);
    const old=texts.find(row=>row.text==='Nearby study')!;
    expect(old).toBeDefined(); expect(texts.some(row=>row.text==='Indicators 2')).toBe(true);
    expect(await page.evaluate(point=>window.__chartPreferences.studies[0].legend()!.hitTest(point.x,point.y)!==null,old)).toBe(true);
    await page.screenshot({path:info.outputPath(`expanded-legends-${width}.png`)});
    await tapCount(page);
    const collapsed=await measurements(page),hidden=await legendTexts(page);
    expect(collapsed.collapsed).toBe(true); expect(collapsed.base).toBe(initial.base);
    expect(collapsed.retained).toBe(true); expect(collapsed.visible).toEqual(initial.visible);
    expect(hidden.some(row=>row.text==='Nearby study'||row.text==='Distant study')).toBe(false);
    expect(hidden.some(row=>row.text==='Indicators 2')).toBe(true);
    expect(hidden.some(row=>row.text==='Host quote')).toBe(true);
    expect(hidden.some(row=>row.text==='O 631 H 637 L 629 C 635')).toBe(true);
    expect(await page.evaluate(point=>window.__chartPreferences.studies[0].legend()!.hitTest(point.x,point.y),old)).toBeNull();
    const rect=await page.locator('.oac-chart').boundingBox();
    await page.touchscreen.tap(rect!.x+old.x,rect!.y+old.y);
    await paint(page);
    expect((await measurements(page)).view).toEqual(initial.view);
    await expect(page.locator('.oac-indset')).toHaveCount(0);
    await page.evaluate(()=>{
      const state=window.__chartPreferences,last=state.bars[state.bars.length-1];
      state.widget.series.update({...last,close:last.close+12,high:last.high+12});
      state.hostLegend.setValues([{text:'O 631 H 649 L 629 C 647',field:'ohlc'}]);
    });
    await paint(page);
    const updated=await measurements(page);
    await page.screenshot({path:info.outputPath(`collapsed-live-legends-${width}.png`)});
    await info.attach('updated-chart-measurements',{body:JSON.stringify({...updated,base:undefined}),contentType:'application/json'});
    expect(updated.collapsed).toBe(true); expect(updated.base).not.toBe(collapsed.base);
    expect(updated.blue).toBeGreaterThan(100); expect(updated.yellow).toBeGreaterThan(100);
    expect(await page.evaluate(()=>{
      const values=window.__chartPreferences.studies[0].values().upper; return values[values.length-1];
    })).toBe(650);
    expect((await legendTexts(page)).some(row=>row.text==='O 631 H 649 L 629 C 647')).toBe(true);
    await tapCount(page); expect((await measurements(page)).collapsed).toBe(false);
    expect((await legendTexts(page)).some(row=>row.text==='Nearby study')).toBe(true);
    expect(errors).toEqual([]);
  });

  test(`keyboard settings cancel and reload preserve chart preferences at ${width}px`,async ({page},info)=>{
    const errors=await mount(page,width);
    const open=async ()=>{ await page.evaluate(()=>window.__chartPreferences.settings('axes')); };
    await open();
    const dialog=page.locator('.oac-settings');
    let fit=dialog.getByLabel('Fit primary prices only',{exact:true});
    await fit.focus(); await fit.press('Space');
    await expect.poll(()=>page.evaluate(()=>window.__chartPreferences.chart.priceOnlyAutoScale())).toBe(true);
    await dialog.getByRole('tab',{name:'Readout',exact:true}).click();
    let collapse=dialog.getByLabel('Collapse indicator legends',{exact:true});
    await collapse.focus(); await collapse.press('Space');
    await expect.poll(()=>page.evaluate(()=>window.__chartPreferences.chart.indicatorLegendCollapsed())).toBe(true);
    await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
    expect((await measurements(page)).priceOnly).toBe(false); expect((await measurements(page)).collapsed).toBe(false);
    await open(); fit=dialog.getByLabel('Fit primary prices only',{exact:true});
    await fit.focus(); await fit.press('Space');
    await dialog.getByRole('tab',{name:'Readout',exact:true}).click();
    collapse=dialog.getByLabel('Collapse indicator legends',{exact:true});
    await collapse.focus(); await collapse.press('Space');
    await page.screenshot({path:info.outputPath(`preference-settings-${width}.png`)});
    await dialog.getByRole('button',{name:'OK',exact:true}).click();
    await expect.poll(()=>page.evaluate(()=>{
      const saved=window.__chartPreferences.widget.context.storage.get('state') as {chart?:{priceOnlyAutoScale?:boolean;indicatorLegendCollapsed?:boolean}}|null;
      return [saved?.chart?.priceOnlyAutoScale,saved?.chart?.indicatorLegendCollapsed];
    })).toEqual([true,true]);
    await page.reload(); await initialize(page);
    const restored=await measurements(page);
    expect(restored.priceOnly).toBe(true); expect(restored.collapsed).toBe(true);
    expect(restored.range.max).toBeLessThan(250); expect(restored.visible).toEqual([true,true]);
    const texts=await legendTexts(page);
    expect(texts.some(row=>row.text==='Indicators 2')).toBe(true);
    expect(texts.some(row=>row.text==='Nearby study')).toBe(false);
    await page.screenshot({path:info.outputPath(`preference-reload-${width}.png`)});
    expect(errors).toEqual([]);
  });
}
