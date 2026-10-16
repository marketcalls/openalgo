import { describe, expect, it } from 'vitest';
import { installDom } from './fake-dom.js';
import { directEntryEnabled } from '../src/inspection.js';

describe('reference host direct entry ownership', () => {
  it('requires the focused chart and suspends entry during replay or loading', () => {
    const { chart, document } = installDom();
    const host = { focusPane: 1 };
    expect(directEntryEnabled(host, 1, chart, chart)).toBe(true);
    expect(directEntryEnabled(host, 1, chart, document.body)).toBe(false);
    host.replayPicking = true;
    expect(directEntryEnabled(host, 1, chart, chart)).toBe(false);
    host.replayPicking = false;
    host.workspaceLoading = true;
    expect(directEntryEnabled(host, 1, chart, chart)).toBe(false);
    host.workspaceLoading = false;
    host.loadFailed = true;
    expect(directEntryEnabled(host, 1, chart, chart)).toBe(false);
  });

  it('lets only the selected pane consume a direct entry key', () => {
    const { chart, document, stage } = installDom();
    const second = document.createElement('div');
    stage.appendChild(second);
    const host = { focusPane: 2 };
    expect(directEntryEnabled(host, 1, chart, chart)).toBe(false);
    expect(directEntryEnabled(host, 2, second, second)).toBe(true);
    host.loading2 = true;
    expect(directEntryEnabled(host, 2, second, second)).toBe(false);
  });
});
