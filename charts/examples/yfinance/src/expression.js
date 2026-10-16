/**
 * Symbol arithmetic in the reference host: type `AAPL/MSFT` into the symbol box
 * and get a chart of the ratio.
 *
 * The engine owns the parsing and the folding. This file owns the two things a
 * host must own: turning the symbols the expression names into bars, and
 * telling the user what went wrong when it cannot.
 *
 * Legs are fetched in parallel and the first failure wins, because a ratio with
 * one leg missing is not a chart with a gap, it is no chart at all.
 */
import {
  parseExpression, evaluateExpression, isPlainSymbol, ExpressionError,
} from '/dist/openalgo-charts.transform.mjs';
import { fetchBars } from './feed.js';
import { requestVariant } from './session.js';

export { ExpressionError, isPlainSymbol };

/**
 * Preserve supplied metadata for one instrument; an expression has no
 * position level. The session is the request's, as the engine's variant.
 */
export function referenceDataContext(request, previous) {
  const context = { symbol: request.symbol, interval: request.interval };
  if (isExpression(request.symbol)) context.hasOpenInterest = false;
  else if (previous?.symbol === request.symbol && previous.hasOpenInterest !== undefined) {
    context.hasOpenInterest = previous.hasOpenInterest;
  }
  const variant = requestVariant(request);
  if (variant) context.variant = variant;
  return context;
}

/** The operator keypad, in the order it is drawn. */
export const OPERATORS = [
  { label: '÷', insert: '/', title: 'Divide' },
  { label: '−', insert: '-', title: 'Subtract' },
  { label: '+', insert: '+', title: 'Add' },
  { label: '×', insert: '*', title: 'Multiply' },
  { label: '^', insert: '^', title: 'Power' },
  { label: '1/', insert: '1/', title: 'Reciprocal' },
];

/**
 * True when the box holds arithmetic rather than one instrument.
 *
 * Parse failures answer `false` rather than throwing: a half-typed `AAPL/`
 * arrives on every keystroke, and the plain path already knows how to say that
 * a symbol is unknown.
 */
export function isExpression(text) {
  const s = (text || '').trim();
  if (s === '') return false;
  if (isPlainSymbol(s)) return false;
  try { parseExpression(s); return true; } catch { return false; }
}

/**
 * Fetch every leg and fold them into one series.
 *
 * `ohlc` is `'close'` by default. The engine can bound a high and low by
 * interval arithmetic, but that bound assumes each leg hit its extreme at the
 * worst possible moment, so it is offered rather than assumed: a line of exact
 * closes is the honest default for a ratio.
 */
export async function fetchExpressionBars(source, interval, period, opts = {}) {
  const expr = parseExpression(source);
  // A pane-owned signal cancels all its legs together without claiming another
  // chart's slots. Legacy callers retain the primary expression slots.
  const legs = await Promise.all(expr.symbols.map((symbol, i) =>
    fetchBars(symbol, interval, period, { ...opts, slot: opts.signal ? undefined : `expr:${i}` })
      .then((bars) => [symbol, bars])));

  const bySymbol = {};
  for (const [symbol, bars] of legs) {
    if (!bars || bars.length === 0) {
      throw new ExpressionError(`no bars for ${symbol}`, source.indexOf(symbol));
    }
    bySymbol[symbol] = bars;
  }

  const bars = evaluateExpression(expr, bySymbol, { ohlc: opts.ohlc || 'close', volume: 'sum' });
  if (bars.length === 0) {
    // Every leg had data and nothing survived, so the legs never traded at the
    // same timestamps: a different session, or an interval one of them lacks.
    throw new ExpressionError(
      `${expr.symbols.join(' and ')} have no bars at the same times on ${interval}`, 0);
  }
  return { bars, expr };
}

/**
 * Draw the operator keypad inside the symbol field and keep the caret where the
 * user left it. Returns a teardown, so a re-render does not stack listeners.
 */
export function mountOperatorKeypad(input, host, onChange) {
  host.innerHTML = '';
  host.className = 'symkeys';
  const made = [];
  for (const op of OPERATORS) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'symkey';
    b.textContent = op.label;
    b.title = op.title;
    b.setAttribute('aria-label', op.title);
    // `mousedown` rather than `click`: the field must not lose focus first, or
    // the caret position we are about to write to is gone.
    const press = (ev) => {
      ev.preventDefault();
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? start;
      // `1/` wraps the whole expression instead of splicing at the caret,
      // because a reciprocal of part of it is almost never what was meant.
      if (op.insert === '1/') {
        input.value = `1/(${input.value.trim()})`;
      } else {
        input.value = input.value.slice(0, start) + op.insert + input.value.slice(end);
      }
      const caret = op.insert === '1/' ? input.value.length : start + op.insert.length;
      input.focus();
      input.setSelectionRange(caret, caret);
      if (onChange) onChange(input.value);
    };
    b.addEventListener('mousedown', press);
    host.appendChild(b);
    made.push([b, press]);
  }
  return () => { for (const [b, press] of made) b.removeEventListener('mousedown', press); host.innerHTML = ''; };
}
