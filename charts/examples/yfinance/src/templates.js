import { parseIndicatorTemplate } from '/dist/openalgo-charts.workspace.mjs';
import { captureIndicatorTemplate, applyIndicatorTemplate, templateUnavailableReason } from './indicator-templates.js';
import { capturePaneTarget } from './pane-target.js';
import { renderIndicatorChips } from './indicators.js';
import { autosave } from './persist.js';
import { el, openOverlay, toast } from './ui.js';

/** Templates share the layout catalog and its revision guard, never a second cache. */
export function initTemplates(app) {
  const catalog = app.workspaceCatalog, modal = el('templatemodal'), picker = el('tp-select'), name = el('tp-name');
  let target = null, busy = false, selectionKey = '', pendingDelete = null, error = '', notice = '';
  const transact = work => catalog.run(() => work(catalog.repository), { recover: false });
  const selected = () => {
    const document = catalog.catalog?.templates.find(item => item.id === picker.value);
    if (!document) throw new Error('The saved template no longer exists');
    return document;
  };

  function render() {
    const templates = catalog.catalog?.templates || [], selectedId = picker.value;
    const signature = JSON.stringify(templates.map(item => [item.id, item.name]));
    if (picker.dataset.documents !== signature) {
      picker.replaceChildren(...templates.map(item => {
        const option = document.createElement('option'); option.value = item.id; option.textContent = item.name; return option;
      }));
      picker.dataset.documents = signature;
    }
    picker.value = templates.some(item => item.id === selectedId) ? selectedId : templates[0]?.id || '';
    const chosen = templates.find(item => item.id === picker.value);
    const key = chosen ? `${chosen.id}:${chosen.name}` : '';
    if (key !== selectionKey) { name.value = chosen?.name || ''; selectionKey = key; }
    el('tp-owner').textContent = target ? `Chart ${target.pane}: ${target.request.symbol}, ${target.request.interval}` : 'Select a chart to capture its studies';
    el('tp-summary').textContent = chosen ? `${chosen.indicators.length} studies` : 'No saved templates';
    const locked = busy || catalog.busy, reason = templateUnavailableReason(app, target);
    picker.disabled = locked || !templates.length; name.disabled = locked;
    for (const id of ['tp-scale-policy', 'tp-range-policy']) el(id).disabled = locked || Boolean(reason) || !chosen;
    el('tp-new').disabled = locked || Boolean(reason) || !catalog.catalog || !name.value.trim();
    el('tp-update').disabled = locked || Boolean(reason) || !chosen;
    for (const id of ['tp-replace', 'tp-append']) el(id).disabled = locked || Boolean(reason) || !chosen;
    for (const id of ['tp-rename', 'tp-duplicate']) el(id).disabled = locked || !chosen || !name.value.trim();
    for (const id of ['tp-delete', 'tp-export']) el(id).disabled = locked || !chosen;
    for (const id of ['tp-import', 'tp-file']) el(id).disabled = locked || !catalog.catalog;
    el('tp-refresh').disabled = locked;
    if (pendingDelete && !templates.some(item => item.id === pendingDelete)) pendingDelete = null;
    el('tp-confirm').hidden = !pendingDelete;
    el('tp-confirm-delete').disabled = locked; el('tp-keep').disabled = locked;
    el('tp-error').textContent = error || catalog.error; el('tp-error').hidden = !(error || catalog.error);
    el('tp-notice').textContent = locked ? 'Working...' : reason || notice;
  }

  async function action(work, message) {
    if (busy || catalog.busy) { error = 'Another layout or template operation is in progress. Try again when it finishes.'; render(); return; }
    busy = true; error = ''; notice = ''; render();
    try {
      const result = await work();
      if (result?.kind === 'indicator-template') picker.value = result.id;
      notice = message;
    } catch (failure) {
      error = failure instanceof AggregateError ? `${failure.message}: ${failure.errors.map(item => item.message).join('; ')}` : String(failure?.message || failure);
      if (modal.hidden) toast('error', error);
    } finally { busy = false; render(); }
  }

  app.openTemplates = () => {
    target = capturePaneTarget(app); pendingDelete = null; notice = ''; error = '';
    render(); modal.hidden = false; openOverlay(modal, { initialFocus: name });
  };
  app.refreshTemplateControls = render;
  el('tp-close').addEventListener('click', () => { modal.hidden = true; });
  modal.addEventListener('click', event => { if (event.target === modal) modal.hidden = true; });
  name.addEventListener('input', render);
  picker.addEventListener('change', () => { pendingDelete = null; render(); });
  el('tp-new').addEventListener('click', () => action(() => {
    const payload = captureIndicatorTemplate(app, target);
    return transact(repository => repository.createTemplate(name.value, payload));
  }, 'Template saved'));
  el('tp-update').addEventListener('click', () => action(() => {
    const payload = captureIndicatorTemplate(app, target), id = selected().id;
    return transact(repository => repository.saveTemplate(id, payload));
  }, 'Template updated'));
  el('tp-rename').addEventListener('click', () => action(() => transact(repository => repository.rename('indicator-template', picker.value, name.value)), 'Template renamed'));
  el('tp-duplicate').addEventListener('click', () => action(() => transact(repository => repository.duplicate('indicator-template', picker.value, name.value)), 'Template duplicated'));
  el('tp-delete').addEventListener('click', () => {
    pendingDelete = selected().id; el('tp-delete-name').textContent = `Delete "${selected().name}"?`; render();
  });
  el('tp-keep').addEventListener('click', () => { pendingDelete = null; render(); });
  el('tp-confirm-delete').addEventListener('click', () => action(() => transact(repository => repository.remove('indicator-template', pendingDelete)), 'Template deleted'));
  el('tp-refresh').addEventListener('click', () => action(() => catalog.refresh(), 'Saved templates reloaded'));
  for (const mode of ['replace', 'append']) el(`tp-${mode}`).addEventListener('click', () => action(() => {
    try { applyIndicatorTemplate(app, target, selected(), mode, {
      scalePolicy: el('tp-scale-policy').value, rangePolicy: el('tp-range-policy').value,
    }); }
    finally { renderIndicatorChips(); }
    autosave();
  }, 'Template applied'));
  el('tp-export').addEventListener('click', () => action(async () => {
    const text = await transact(repository => repository.exportDocument('indicator-template', picker.value));
    const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'openalgo-indicator-template.json'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, 'Template exported'));
  el('tp-import').addEventListener('click', () => { el('tp-file').value = ''; el('tp-file').click(); });
  el('tp-file').addEventListener('change', async () => {
    const file = el('tp-file').files?.[0]; if (!file) return;
    await catalog.flushAutosave();
    action(async () => {
      const document = parseIndicatorTemplate(await file.text());
      return transact(repository => repository.importDocument(document));
    }, 'Template imported. Choose Replace or Append to apply it.');
  });
  render();
}
