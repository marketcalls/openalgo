import { getIndicator } from '/dist/openalgo-charts.mjs';
import { hasDrawingTool, sanitizeDrawing, DRAWING_STATE_VERSION } from '/dist/openalgo-charts.draw.mjs';
import { layoutFromWorkspace } from './workspace-document.js';
import { fetchBars } from './feed.js';
import { fetchExpressionBars, isExpression } from './expression.js';
import { DEFAULT_TZ } from './timezone.js';
import { requestVariant } from './session.js';

function owned(promise, signal) {
  return new Promise((resolve, reject) => {
    const cleanup = () => signal.removeEventListener('abort', cancel);
    const cancel = () => { cleanup(); reject(signal.reason); };
    Promise.resolve(promise).then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
    if (signal.aborted) cancel();
    else signal.addEventListener('abort', cancel, { once: true });
  });
}

function validateStudiesAndDrawings(state) {
  for (const study of state.indicators || []) {
    try { getIndicator(study.indicatorId); }
    catch { throw new Error(`Unavailable layout study: ${study.indicatorId}`); }
  }
  // Any document version this build reads: a save is written as the lowest
  // version that holds it, so one with no interval range is still version 2.
  const version = state.drawings?.version;
  if (state.drawings !== undefined && !Array.isArray(state.drawings)
    && !(Number.isInteger(version) && version >= 2 && version <= DRAWING_STATE_VERSION)) {
    throw new Error('Unsupported layout drawing document version');
  }
  const drawings = Array.isArray(state.drawings) ? state.drawings : state.drawings?.drawings || [];
  if (!Array.isArray(drawings)) throw new Error('Invalid layout drawings');
  const ids = new Set();
  for (const drawing of drawings) {
    if (!hasDrawingTool(drawing.tool)) throw new Error(`Unavailable layout drawing: ${drawing.tool}`);
    if (typeof drawing.id !== 'string' || !drawing.id || ids.has(drawing.id) || !sanitizeDrawing(drawing)) {
      throw new Error('Invalid layout drawing or duplicate drawing identity');
    }
    ids.add(drawing.id);
  }
}

async function sourceBars(request, options) {
  // Staged in the session the workspace names, so a saved extended chart reopens on extended bars.
  const staged = { ...options, variant: requestVariant(request) };
  return isExpression(request.symbol)
    ? (await fetchExpressionBars(request.symbol, request.interval, request.period, staged)).bars
    : fetchBars(request.symbol, request.interval, request.period, staged);
}

/** Use the same availability checks for startup and prepared live switching. */
export function validateReferenceLayout(layout) {
  for (const key of ['symbol', 'interval']) {
    if (layout.secondary && layout.linkOptions[key] && layout.request[key] !== layout.secondary.request[key]) {
      throw new Error(`Linked layout ${key} settings conflict between charts`);
    }
  }
  validateStudiesAndDrawings(layout);
  if (layout.secondary) validateStudiesAndDrawings(layout.secondary.state);
}

/** Stage raw histories without changing controls, live charts or their request slots. */
export async function prepareReferenceWorkspace(input, { signal, fetch = sourceBars } = {}) {
  const layout = layoutFromWorkspace(input);
  validateReferenceLayout(layout);
  const controller = new AbortController();
  const cancel = () => controller.abort(signal.reason);
  if (signal?.aborted) cancel();
  else signal?.addEventListener('abort', cancel, { once: true });
  try {
    controller.signal.throwIfAborted();
    const sources = [layout, ...(layout.secondary ? [layout.secondary] : [])];
    const loaded = sources.map(async source => {
      const timezone = source.state?.timezone || source.timezone || DEFAULT_TZ;
      const bars = await fetch(source.request, { timezone, signal: controller.signal });
      controller.signal.throwIfAborted();
      if (!Array.isArray(bars) || !bars.length) throw new Error(`No history bars for ${source.request.symbol}`);
      return bars.map(bar => ({ ...bar }));
    });
    return { layout, bars: await owned(Promise.all(loaded), controller.signal) };
  } catch (error) {
    controller.abort(error);
    throw error;
  } finally {
    signal?.removeEventListener('abort', cancel);
  }
}

/** The host supplies synchronous installation and an owner watch for pending work. */
export class ReferenceWorkspaceTransition {
  constructor(callbacks) {
    this.callbacks = callbacks;
    this.pending = null;
    this.closed = false;
    this.publishing = false;
  }

  async open(payload, persist = async () => {}) {
    if (this.closed) throw new Error('The layout owner is closed');
    if (this.publishing) throw new Error('A layout is being installed');
    this.cancel();
    const before = this.callbacks.capture();
    const operation = { controller: new AbortController(), unwatch: null };
    const { signal } = operation.controller;
    this.pending = operation;
    try {
      this.callbacks.setPending(true);
      operation.unwatch = this.callbacks.watch?.(() => this.cancel());
      const prepared = await owned((this.callbacks.prepare || prepareReferenceWorkspace)(payload, { signal }), signal);
      this.assertCurrent(operation, before);
      // Storage honors cancellation until commit. Once committed, await its
      // receipt so a simultaneous cancellation cannot bypass compensation.
      const receipt = await persist(signal);
      try { this.assertCurrent(operation, before); }
      catch (error) {
        try { await receipt?.rollback?.(); }
        catch (rollbackError) { throw new AggregateError([error, rollbackError], 'The layout changed and storage recovery failed'); }
        throw error;
      }
      this.unwatch(operation);
      this.publishing = true;
      try { this.callbacks.install(prepared); }
      catch (error) {
        const failures = [error];
        try { this.callbacks.install(before); } catch (rollbackError) { failures.push(rollbackError); }
        try { await receipt?.rollback?.(); } catch (rollbackError) { failures.push(rollbackError); }
        if (failures.length > 1) throw new AggregateError(failures, 'Layout installation and recovery failed');
        throw error;
      } finally { this.publishing = false; }
      return prepared;
    } catch (error) {
      operation.controller.abort(error);
      throw error;
    } finally {
      this.unwatch(operation);
      if (this.pending === operation) {
        this.pending = null;
        this.callbacks.setPending(false);
      }
    }
  }

  assertCurrent(operation, before) {
    operation.controller.signal.throwIfAborted();
    if (this.closed || this.pending !== operation || !this.callbacks.current(before)) {
      throw new Error('The current layout changed; this switch was cancelled');
    }
  }

  unwatch(operation) {
    const release = operation.unwatch;
    operation.unwatch = null;
    release?.();
  }

  cancel() {
    if (!this.pending || this.publishing) return;
    const operation = this.pending;
    this.pending = null;
    operation.controller.abort(new Error('Layout preparation was cancelled'));
    this.unwatch(operation);
    this.callbacks.setPending(false);
  }

  destroy() {
    this.closed = true;
    this.cancel();
  }
}
