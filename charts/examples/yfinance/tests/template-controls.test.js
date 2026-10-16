import fs from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { installDom } from './fake-dom.js';
const actions = vi.hoisted(() => ({ capture: vi.fn(), apply: vi.fn(), autosave: vi.fn() }));
vi.mock('../src/indicator-templates.js', () => ({
  captureIndicatorTemplate: actions.capture, applyIndicatorTemplate: actions.apply,
  templateUnavailableReason: () => null,
}));
vi.mock('../src/indicators.js', () => ({ renderIndicatorChips: () => {} }));
vi.mock('../src/persist.js', () => ({ autosave: actions.autosave }));
vi.mock('../src/ui.js', () => ({ el: id => document.getElementById(id), openOverlay: () => {}, toast: () => {} }));
import { initTemplates } from '../src/templates.js';

const payload = () => ({ indicators: [{ indicatorId: 'custom', instanceId: 'source', settings: {}, paneIndex: 0 }],
  layout: { panes: [], plots: [], primaryScaleId: 'right' } });
const saved = () => ({ kind: 'indicator-template', version: 1, id: 'saved', name: 'Saved', createdAt: 0, updatedAt: 0, ...payload() });
function mount() {
  const { document } = installDom();
  const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8').split('<div id="templatemodal" hidden>')[1].split('<div id="workspacemodal"')[0];
  const modal = document.createElement('div'); modal.id = 'templatemodal'; document.body.appendChild(modal);
  for (const [, tag, id] of html.matchAll(/<([a-z]+)[^>]*\bid="([^"]+)"/g)) {
    const node = document.createElement(tag); node.id = id;
    node.replaceChildren = (...children) => { node.textContent = ''; node.append(...children); };
    if (tag === 'select') {
      const options = html.split('id="' + id + '"')[1].split('</select>')[0];
      node.value = options.match(/<option value="([^"]+)"/)?.[1] || '';
    }
    modal.appendChild(node);
  }
  const chosen = saved(), captured = payload();
  actions.capture.mockReturnValue(captured);
  const repository = { createTemplate: vi.fn(async () => chosen), saveTemplate: vi.fn(async () => chosen) };
  const catalog = { catalog: { templates: [chosen] }, busy: false, error: '', repository,
    run: async work => work(), refresh: async () => {}, flushAutosave: async () => {} };
  const chart = { getDataContext: () => ({ symbol: 'A', interval: '1m' }) };
  const app = { workspaceCatalog: catalog, chart, req: { symbol: 'A', interval: '1m', period: '1d' } };
  initTemplates(app); app.openTemplates();
  return { app, catalog, repository, chosen, captured, get: id => document.getElementById(id), html };
}
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
beforeEach(() => vi.clearAllMocks());

describe('template modal payload and application controls', () => {
  it('declares independent-copy and reset-view defaults using the existing select rows', () => {
    const h = mount();
    expect(h.get('tp-scale-policy')).not.toBeNull();
    expect(h.get('tp-range-policy')).not.toBeNull();
    expect(h.get('tp-scale-policy').value).toBe('copy');
    expect(h.get('tp-range-policy').value).toBe('auto');
    expect(h.html).toContain('Independent copies'); expect(h.html).toContain('Share existing scales');
    expect(h.html).toContain('Reset manual view'); expect(h.html).toContain('Keep saved view');
  });

  it('passes the complete selected document and both explicit choices to apply', async () => {
    const h = mount();
    if (h.get('tp-scale-policy')) h.get('tp-scale-policy').value = 'share';
    if (h.get('tp-range-policy')) h.get('tp-range-policy').value = 'preserve';
    h.get('tp-append').click(); await settle();
    expect(actions.apply).toHaveBeenCalledWith(h.app, expect.objectContaining({ chart: h.app.chart }), h.chosen,
      'append', { scalePolicy: 'share', rangePolicy: 'preserve' });
    expect(actions.autosave).toHaveBeenCalledOnce();
  });

  it('saves and updates the complete captured payload', async () => {
    const h = mount(); h.get('tp-name').value = 'New name';
    h.get('tp-new').click(); await settle();
    expect(h.repository.createTemplate).toHaveBeenCalledWith('New name', h.captured);
    h.get('tp-update').click(); await settle();
    expect(h.repository.saveTemplate).toHaveBeenCalledWith('saved', h.captured);
  });

  it('locks application choices while a catalog operation owns the modal', () => {
    const h = mount(); h.catalog.busy = true; h.app.refreshTemplateControls();
    expect(h.get('tp-scale-policy')).not.toBeNull();
    expect(h.get('tp-range-policy')).not.toBeNull();
    expect(h.get('tp-scale-policy').disabled).toBe(true);
    expect(h.get('tp-range-policy').disabled).toBe(true);
  });
});
