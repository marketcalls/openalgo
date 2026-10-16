import { describe, expect, it } from 'vitest';
import { installDom, type FakeElement } from './widget-form.test';
import { renderForm, type FormControl } from '../src/widget/form';
import { createColorPicker } from '../src/widget/color-picker';

const controls: FormControl[] = [
  { key: 'up', kind: 'color', label: 'Up' },
  { key: 'down', kind: 'color', label: 'Down' },
];

function mount(values: Record<string, unknown>, live = false) {
  const dom = installDom();
  const host = dom.doc.createElement('div');
  dom.root.appendChild(host);
  const changes: Array<[string, unknown]> = [];
  const form = renderForm(host as unknown as HTMLElement, controls, {
    values, live, idPrefix: 'color', onChange: (key, value) => changes.push([key, value]),
  });
  return { dom, host, form, changes };
}

describe('shared colour picker', () => {
  it('preserves supported hex, comma and space/slash colours and their alpha', () => {
    const { doc } = installDom();
    const changes: string[] = [];
    const picker = createColorPicker(doc as unknown as Document, {
      id: 'formats', label: 'Color', value: undefined, onChange: value => changes.push(value),
    });
    const samples = [
      ['#AbC', '#aabbcc', '#aabbcc'],
      ['#AbC8', '#aabbcc', '#aabbcc88'],
      ['#12345678', '#123456', '#12345678'],
      ['rgb(38, 166, 154)', '#26a69a', '#26a69a'],
      ['RGBA(38,166,154,.4)', '#26a69a', 'rgba(38,166,154,0.4)'],
      ['rgba(38,166,154)', '#26a69a', '#26a69a'],
      ['rgb(38 166 154)', '#26a69a', '#26a69a'],
      ['rgba(38 166 154 / .4)', '#26a69a', 'rgba(38,166,154,0.4)'],
      ['rgb(38 166 154 / 1.)', '#26a69a', 'rgba(38,166,154,1)'],
      ['\trgb(38\t166\n154 / 0)\n', '#26a69a', 'rgba(38,166,154,0)'],
      ['rgb(000 001 255)', '#0001ff', '#0001ff'],
    ];
    for (const [raw, hex, painted] of samples) {
      picker.write(raw);
      expect(picker.read()).toBe(raw);
      expect(picker.input.value).toBe(hex);
      expect(picker.trigger.style.backgroundColor).toBe(painted);
    }
    expect(changes).toEqual([]);
    picker.destroy();
  });

  it('retains malformed and missing raw colours without interpreting incomplete components', () => {
    const { doc } = installDom();
    const changes: string[] = [];
    const picker = createColorPicker(doc as unknown as Document, {
      id: 'invalid', label: 'Color', value: undefined, onChange: value => changes.push(value),
    });
    const invalid = [
      undefined, null, 42, '', 'rgb(1,2,3,)', 'rgb(1 2 3 /)',
      'rgb(1,2 3)', 'rgb(1 2,3)', 'rgba(1 2 3 .4)', 'rgb(1,2,300)',
      'rgb(1 2 3 /.4.2)', 'rgb(1 2 3 /1.1)', 'rgb(1 2 3 /NaN)',
      'rgb(1 2 3 /0x1)', 'rgb(1 2 3 /1e-1)', 'rgb(1 2 3 / .5 / .6)',
    ];
    for (const raw of invalid) {
      picker.write(raw);
      expect(picker.read()).toBe(raw);
      expect(picker.input.value, String(raw)).toBe('#000000');
    }
    expect(changes).toEqual([]);
    picker.destroy();
  });

  it('rejects oversized colour input before parsing or trimming while retaining the raw value', () => {
    const { doc } = installDom();
    const picker = createColorPicker(doc as unknown as Document, {
      id: 'bounded', label: 'Color', value: '#123456', onChange: () => {},
    });
    for (const raw of [`rgb(38,166,154${' '.repeat(300)})`, `${' '.repeat(300)}#123456`, `rgba(38 166 154 / .${'0'.repeat(300)}4)`]) {
      picker.write(raw);
      expect(picker.read()).toBe(raw);
      expect(picker.input.value).toBe('#000000');
    }
    picker.destroy();
  });

  it('paints the visible face and palette independently of native colour input support', () => {
    const { doc } = installDom();
    const changes: string[] = [];
    const picker = createColorPicker(doc as unknown as Document, {
      id: 'paint', label: 'Color', value: 'rgba(38,166,154,0.4)', onChange: value => changes.push(value),
    });
    expect(picker.trigger.style.backgroundColor).toBe('rgba(38,166,154,0.4)');
    picker.write('#e6b53c');
    expect(picker.trigger.style.backgroundColor).toBe('#e6b53c');
    expect(picker.input.value).toBe('#e6b53c');
    picker.input.value = '#112233';
    (picker.input as unknown as FakeElement).fire('change');
    expect(picker.trigger.style.backgroundColor).toBe('#112233');
    expect(changes).toEqual(['#112233']);
    picker.trigger.click();
    const choice = picker.el.querySelector('.oac-color__palette button') as HTMLElement;
    expect(choice.style.backgroundColor).toBe('#4f8cff');
    expect(picker.input.tabIndex).toBe(-1);
  });

  it('preserves alpha and the original value while opening and cancelling', () => {
    const { host, form, changes } = mount({ up: 'rgba(38,166,154,0.4)', down: '#ef5350' });
    expect(form.values().up).toBe('rgba(38,166,154,0.4)');
    const trigger = host.querySelector('.oac-color__trigger') as FakeElement;
    expect((host.querySelector('.oac-row__label') as FakeElement).htmlFor).toBe(trigger.id);
    trigger.click();
    expect(host.querySelector('.oac-color__popover')?.hidden).toBe(false);
    const opacity = host.querySelector('.oac-color__opacity input') as FakeElement;
    expect(opacity.value).toBe('40');
    opacity.value = '75';
    opacity.fire('input');
    expect(changes).toEqual([]);
    opacity.fire('keydown', { key: 'Escape' });
    expect(form.values().up).toBe('rgba(38,166,154,0.4)');
    expect(changes).toEqual([]);
  });

  it('applies palette colours with existing alpha and bounds recent choices', () => {
    const { host, form, changes } = mount({ up: '#12345680', down: '#ffffff' });
    const trigger = host.querySelector('.oac-color__trigger') as FakeElement;
    trigger.click();
    const palette = host.querySelector('.oac-color__palette button') as FakeElement;
    palette.click();
    expect(changes).toEqual([['up', '#4f8cff80']]);
    expect(form.values().up).toBe('#4f8cff80');
    const custom = host.querySelector('#color-up') as FakeElement;
    for (let i = 0; i < 10; i++) {
      custom.value = `#${(i + 1).toString(16).padStart(6, '0')}`;
      custom.fire('change');
    }
    trigger.click();
    expect(host.querySelectorAll('.oac-color__recent button').length).toBe(6);
    (host.querySelector('.oac-color__recent button') as FakeElement).click();
    expect(form.values().up).toBe('#00000a80');
  });

  it('commits on release and previews on input only when live', () => {
    const quiet = mount({ up: '#123456', down: '#ffffff' });
    const custom = quiet.host.querySelector('#color-up') as FakeElement;
    custom.value = '#abcdef';
    custom.fire('input');
    expect(quiet.changes).toEqual([]);
    custom.fire('change');
    expect(quiet.changes).toEqual([['up', '#abcdef']]);
    const live = mount({ up: '#123456', down: '#ffffff' }, true);
    const liveInput = live.host.querySelector('#color-up') as FakeElement;
    liveInput.value = '#abcdef';
    liveInput.fire('input');
    liveInput.fire('change');
    expect(live.changes).toEqual([['up', '#abcdef']]);
  });

  it('keeps paired triggers in one row and disables an unavailable colour', () => {
    const dom = installDom();
    const host = dom.doc.createElement('div');
    const form = renderForm(host as unknown as HTMLElement, [{
      key: 'pair', kind: 'colorPair', label: 'Body', pair: {
        up: { key: 'up', label: 'Up' }, down: { key: 'down', label: 'Down' },
      },
    }], { values: { up: '#fff', down: '#000' }, idPrefix: 'pair', onChange: () => {}, unavailable: (key) => key === 'up' ? 'No data' : null });
    const row = host.querySelector('.oac-row') as FakeElement;
    expect(row.querySelectorAll('.oac-color__trigger').length).toBe(2);
    const up = row.querySelectorAll('.oac-color__trigger')[0];
    expect(up.disabled).toBe(true);
    expect(up.title).toContain('No data');
    up.click();
    expect(row.querySelectorAll('.oac-color__popover').every(popover => popover.hidden)).toBe(true);
    expect(row.querySelectorAll('.oac-color__popover').length).toBe(2);
    expect(form.focusFirst()).toBe(true);
    expect(dom.doc.activeElement).toBe(row.querySelectorAll('.oac-color__trigger')[1]);
  });
});
