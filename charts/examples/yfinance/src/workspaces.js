import { createIndexedDbWorkspaceStorage } from '/dist/openalgo-charts.workspace.mjs';
import { ReferenceWorkspaceCatalog } from './workspace-catalog.js';
import { workspaceFromLayout, needsGridView, fromGridView } from './workspace-document.js';
import { handOffToGrid, gridViewRefusal } from './grid-view.js';
import { workspaceUnavailable } from './workspace-host.js';
import { validateReferenceLayout } from './workspace-transition.js';
import { layoutSnapshot, readLayout, persistLayoutNow, parseLayoutFile, untrustedDrawings } from './persist.js';
import { magnetMode, stayMode } from './rail.js';
import { el, openOverlay, toast } from './ui.js';
import { capturePaneTarget } from './pane-target.js';
import { chartDataUnavailableReason } from './chart-data.js';
import { openChartDataControls } from './chart-data-controls.js';

/** A portable document with every pane's drawings stripped of their policies. */
function untrustedPanes(document) {
  return Array.isArray(document?.panes)
    ? { ...document, panes: document.panes.map(pane => (pane?.chart ? { ...pane, chart: untrustedDrawings(pane.chart) } : pane)) }
    : document;
}

/**
 * Older exported snapshots become named saves without inferring a live source,
 * and a layout the grid view exported is put in this page's terms. A file is
 * from elsewhere, so no drawing in it keeps a policy.
 */
export function workspaceFileDocument(text, filename) {
  const parsed = JSON.parse(text);
  if (parsed?.kind !== undefined) return untrustedPanes(fromGridView(parsed));
  const payload = workspaceFromLayout(parseLayoutFile(text));
  return { ...payload, kind: 'workspace', version: 1, id: 'legacy-file',
    name: String(filename || 'Imported layout').replace(/\.json$/i, '').trim().slice(0, 120) || 'Imported layout',
    createdAt: 0, updatedAt: 0 };
}

/** A portable document whose geometry only the grid view can show, or null for this page's own import path. */
export function gridFileDocument(text) {
  let parsed;
  try { parsed = JSON.parse(text); } catch { return null; }
  return needsGridView(parsed) ? untrustedPanes(parsed) : null;
}

/** Keep named saves durable; a storage failure never changes their backend. */
export async function initWorkspaces(app) {
  let adapter;
  const backend = () => adapter || (adapter = createIndexedDbWorkspaceStorage(window.indexedDB, 'openalgo-reference-workspaces'));
  const storage = { read: async (...args) => backend().read(...args), write: async (...args) => backend().write(...args) };
  const modal = el('workspacemodal'), picker = el('ws-select'), name = el('ws-name');
  let busy = false, selectionKey = '', pendingDelete = null, localError = '', notice = '', lastError = '';
  let pendingAutosavePreference;
  let dataTarget = null;
  // A layout file with geometry only the grid view can draw, held until the
  // user chooses to open it there.
  let gridLayout = null;
  const snapshot = () => {
    if (workspaceUnavailable(app) || app.workspaceLoading) throw new Error('Finish loading, replay or settings changes before saving layouts');
    return workspaceFromLayout(layoutSnapshot(), { magnet: magnetMode(), stay: stayMode() });
  };
  const catalog = new ReferenceWorkspaceCatalog({ storage, namespace: 'yfinance:reference', snapshot,
    open: (document, persist) => app.openWorkspace(document, persist), changed: render });
  app.workspaceCatalog = catalog;

  function render() {
    const saved = catalog.catalog, documents = saved?.workspaces || [];
    const selected = documents.some(item => item.id === picker.value) ? picker.value : catalog.currentId || documents[0]?.id || '';
    const signature = JSON.stringify(documents.map(item => [item.id, item.name]));
    if (picker.dataset.documents !== signature) {
      picker.replaceChildren(...documents.map(item => {
        const option = document.createElement('option'); option.value = item.id; option.textContent = item.name; return option;
      }));
      picker.dataset.documents = signature;
    }
    picker.value = selected;
    const selectedDocument = documents.find(item => item.id === selected);
    const key = selectedDocument ? `${selectedDocument.id}:${selectedDocument.name}` : '';
    if (key !== selectionKey) { name.value = selectedDocument?.name || ''; selectionKey = key; }
    const current = documents.find(item => item.id === catalog.currentId);
    el('ws-current').textContent = `Current: ${current?.name || 'Unnamed'}`;
    const locked = busy || catalog.busy, unavailable = workspaceUnavailable(app) || app.workspaceLoading;
    const dataReason = chartDataUnavailableReason(app, dataTarget);
    el('ws-data').disabled = Boolean(dataReason);
    el('ws-data-source').textContent = dataTarget
      ? `CSV for Chart ${dataTarget.pane}: ${dataTarget.request.symbol}, ${dataTarget.request.interval}. ${dataReason || 'Choose rows, studies and alignment before downloading.'}`
      : 'Select a chart to download its data.';
    picker.disabled = locked || !documents.length;
    name.disabled = locked;
    el('ws-new').disabled = locked || unavailable || !saved || !name.value.trim();
    el('ws-save').disabled = locked || unavailable || !current;
    el('ws-open').disabled = locked || unavailable || !selectedDocument;
    for (const id of ['ws-rename', 'ws-duplicate']) el(id).disabled = locked || !selectedDocument || !name.value.trim();
    for (const id of ['ws-delete', 'ws-export']) el(id).disabled = locked || !selectedDocument;
    el('ws-import').disabled = locked || unavailable || !saved;
    el('ws-file').disabled = locked || unavailable || !saved;
    el('ws-grid').hidden = gridLayout === null;
    el('ws-grid').disabled = locked;
    el('ws-refresh').disabled = locked;
    el('ws-autosave').disabled = locked || !saved;
    el('ws-autosave').checked = pendingAutosavePreference ?? saved?.autosave === true;
    if (pendingDelete && !documents.some(item => item.id === pendingDelete)) pendingDelete = null;
    el('ws-confirm').hidden = !pendingDelete;
    el('ws-confirm-delete').disabled = locked;
    el('ws-keep').disabled = locked;
    const recent = el('ws-recent');
    const recentSignature = JSON.stringify([saved?.recentWorkspaceIds, documents.map(item => [item.id, item.name])]);
    if (recent.dataset.documents !== recentSignature) {
      recent.replaceChildren(...(saved?.recentWorkspaceIds || []).map(id => {
        const item = documents.find(entry => entry.id === id), button = window.document.createElement('button');
        button.className = 'btn btn--ghost'; button.textContent = item.name; button.setAttribute('aria-label', `Open ${item.name}`);
        button.addEventListener('click', () => action(() => catalog.open(id), 'Layout opened'));
        return button;
      }));
      recent.dataset.documents = recentSignature;
    }
    for (const button of recent.children) button.disabled = locked || unavailable;
    el('ws-recent-row').hidden = !recent.children.length;
    const error = localError || catalog.error;
    el('ws-error').hidden = !error; el('ws-error').textContent = error;
    el('ws-notice').textContent = locked ? 'Working...' : unavailable
      ? 'Finish loading, replay or settings changes to save or open a layout.' : notice;
    if (error && error !== lastError) { toast('error', error); el('status').textContent = error; }
    lastError = error;
    app.refreshTemplateControls?.();
  }

  async function action(work, message) {
    if (busy || catalog.busy) {
      localError = 'A layout operation is already in progress. Try again when it finishes.'; render(); return false;
    }
    busy = true; localError = ''; notice = ''; render();
    try {
      const result = await work();
      if (result?.kind === 'workspace') picker.value = result.id;
      notice = message;
      return true;
    } catch (error) { localError = String(error?.message || error); return false; }
    finally { busy = false; render(); }
  }

  function close() {
    if (app.workspaceLoading) app.workspaceTransition.cancel();
    modal.hidden = true;
  }

  app.openLayouts = () => {
    dataTarget = capturePaneTarget(app);
    render(); modal.hidden = false; openOverlay(modal, { initialFocus: name });
  };
  app.refreshWorkspaceControls = render;
  app.onLayoutPersisted = () => catalog.requestAutosave();
  app.saveNamedLayout = async () => {
    if (await action(() => catalog.save(), 'Layout saved')) {
      persistLayoutNow({ retryStorage: true });
      toast('success', 'Named layout saved');
    }
  };
  el('ws-close').addEventListener('click', close);
  el('ws-data').addEventListener('click', () => openChartDataControls(app, dataTarget));
  modal.addEventListener('click', event => { if (event.target === modal) close(); });
  name.addEventListener('input', render);
  picker.addEventListener('change', () => { pendingDelete = null; render(); });
  el('ws-new').addEventListener('click', () => action(() => catalog.create(name.value), 'New layout saved'));
  el('ws-save').addEventListener('click', app.saveNamedLayout);
  el('ws-open').addEventListener('click', () => action(() => catalog.open(picker.value), 'Layout opened'));
  el('ws-rename').addEventListener('click', () => action(() => catalog.rename(picker.value, name.value), 'Layout renamed'));
  el('ws-duplicate').addEventListener('click', () => action(() => catalog.duplicate(picker.value, name.value), 'Layout duplicated'));
  el('ws-delete').addEventListener('click', () => {
    pendingDelete = picker.value; el('ws-delete-name').textContent = `Delete "${catalog.find(pendingDelete).name}"?`; render();
  });
  el('ws-keep').addEventListener('click', () => { pendingDelete = null; render(); });
  el('ws-confirm-delete').addEventListener('click', () => action(() => catalog.remove(pendingDelete), 'Layout deleted'));
  el('ws-autosave').addEventListener('change', async () => {
    const enabled = el('ws-autosave').checked;
    if (busy || catalog.busy) { render(); return; }
    pendingAutosavePreference = enabled;
    const applied = await action(async () => {
      try { await catalog.setAutosave(enabled); }
      finally { pendingAutosavePreference = undefined; }
    }, enabled ? 'Autosave enabled' : 'Autosave disabled');
    if (applied && enabled && !workspaceUnavailable(app) && !app.workspaceLoading) catalog.requestAutosave();
  });
  el('ws-refresh').addEventListener('click', () => action(() => catalog.refresh(), 'Saved layouts reloaded'));
  el('ws-export').addEventListener('click', () => action(async () => {
    const text = await catalog.export(picker.value);
    const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'openalgo-layout.json'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, 'Layout exported'));
  el('ws-import').addEventListener('click', () => { el('ws-file').value = ''; el('ws-file').click(); });
  el('ws-file').addEventListener('change', async () => {
    const file = el('ws-file').files?.[0];
    if (!file) return;
    const text = await file.text();
    const layout = gridFileDocument(text);
    // Asked before the page is left, so a layout the grid view would refuse is
    // refused here, where the file was chosen.
    const refusal = layout ? gridViewRefusal(layout) : '';
    gridLayout = refusal ? null : layout;
    if (layout) {
      localError = refusal && `${file.name} needs the grid view, which cannot open it: ${refusal}`;
      notice = refusal ? '' : `${file.name} holds ${layout.panes.length} charts in ${layout.layout.rows} rows and ${layout.layout.columns} columns. Open it in the grid view.`;
      render();
      return;
    }
    await catalog.flushAutosave();
    action(async () => catalog.import(workspaceFileDocument(text, file.name)), 'Layout imported and opened');
  });
  el('ws-grid').addEventListener('click', () => {
    if (gridLayout && handOffToGrid(gridLayout)) window.location.assign('grid.html');
    else { localError = 'The layout could not be handed to the grid view'; render(); }
  });

  const recovery = readLayout();
  const legacy = recovery ? { ...recovery, magnet: recovery.magnet ?? magnetMode(), stay: recovery.stay ?? stayMode() } : null;
  try {
    const layout = await catalog.initialize(legacy);
    if (layout) validateReferenceLayout(layout);
    return layout || legacy;
  } catch (error) {
    // A missing custom study must not become an autosaved version without it.
    catalog.error = String(error?.message || error);
    catalog.autosaveBlocked = true; catalog.currentId = null;
    render(); return legacy;
  }
}
