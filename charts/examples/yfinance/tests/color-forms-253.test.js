import { describe, expect, it } from 'vitest';
import { installDom } from './fake-dom.js';
import { renderInputRows, collectInputRows } from '../src/indicators.js';

describe('reference settings colors', () => {
  it('uses the shared picker and retains alpha in generated settings', () => {
    const { document } = installDom();
    const host = document.createElement('div');
    host.id = 'set-body';
    document.body.appendChild(host);
    renderInputRows(host, [{ key: 'plot.color', label: 'Plot color', type: 'color' }],
      { 'plot.color': '#12345680' });
    expect(host.querySelector('.oac-color')).not.toBeNull();
    expect(collectInputRows(host)['plot.color']).toBe('#12345680');
  });
});
