/**
 * Symbol arithmetic: a chart of `NIFTY1!/NSE:RELIANCE`, `(A+B)/2`, `1/GOLD`.
 *
 * Two halves, deliberately separate. `parseExpression` turns a string into an
 * AST and, crucially, tells the caller which symbols it needs *before* any data
 * is fetched, so a host can resolve and load exactly those legs.
 * `evaluateExpression` then folds the legs into one synthetic bar series.
 *
 * The engine does no fetching. A host owns symbol resolution and history, the
 * same way `addComparison` takes bars rather than a symbol.
 *
 * ## Why the high and low are approximations
 *
 * A bar says where a market opened, closed, and how far it travelled, but not
 * *when* it was at each price. For `A/B` the true high of the ratio needs the
 * instant A was highest relative to B, and two OHLC bars do not record that.
 *
 * So the extremes are computed by interval arithmetic: each leg contributes
 * `[low, high]`, every operator maps intervals to intervals, and the result's
 * interval is the range the expression *could* have covered. That bound is
 * guaranteed to contain the truth and is usually wider than it, because it
 * assumes the legs hit their extremes at the worst possible moments. Open and
 * close need no such trick: they are read from the legs' own opens and closes,
 * which are simultaneous by definition, and so are exact.
 *
 * One consequence worth knowing: an interval cannot tell that two mentions of
 * the same symbol move together, so `A/A` bounds to `[low/high, high/low]`
 * rather than collapsing to 1. That is the classic dependency problem, and it
 * is why `ohlc: 'close'` (a line from exact closes) is the default.
 */
import type { Bar } from '../model/bar';

/** A parsed expression, with the symbols it needs. */
export interface SymbolExpression {
  /** The source, as typed. */
  readonly source: string;
  /** Distinct symbols, in first-seen order. The first is the default time grid. */
  readonly symbols: readonly string[];
  /** Opaque syntax tree. */
  readonly ast: ExpressionNode;
}

export interface EvaluateOptions {
  /**
   * `'close'` (default) evaluates only the closes, giving a flat bar whose four
   * values are equal: exact, and honest about what two OHLC bars can support.
   * `'interval'` additionally bounds the high and low as described above.
   */
  ohlc?: 'close' | 'interval';
  /**
   * The leg whose bars define the time grid. Defaults to the first symbol.
   * Every other leg is matched to it by timestamp; a bar with no match on some
   * leg produces a gap rather than a guess.
   */
  primary?: string;
  /**
   * Omitted by default. 'sum' reports the activity of distinct expression legs,
   * once each, without price coefficients or signs. This is combined leg
   * activity, not a traded quantity of the synthetic instrument. All matched
   * legs must have finite nonnegative volume; otherwise volume stays absent.
   */
  volume?: 'sum';
}

// ── syntax tree ───────────────────────────────────────────────────────────

/**
 * The syntax tree behind a parsed expression. Exported so the type of
 * `SymbolExpression.ast` has a name; a host builds one with `parseExpression`,
 * never by hand.
 */
export type ExpressionNode =
  | { k: 'num'; v: number }
  | { k: 'sym'; name: string }
  | { k: 'neg'; a: ExpressionNode }
  | { k: 'bin'; op: '+' | '-' | '*' | '/' | '^'; a: ExpressionNode; b: ExpressionNode }
  | { k: 'fn'; name: ExpressionFunctionName; args: ExpressionNode[] };

/**
 * Functions are limited to ones whose interval image is cheap and correct to
 * derive. Anything non-monotonic in a way that needs calculus is left out
 * rather than shipped with a bound that is quietly wrong.
 */
const FN_ARITY: Record<ExpressionFunctionName, 1 | 2> = {
  abs: 1, sqrt: 1, ln: 1, log: 1, log10: 1, exp: 1, min: 2, max: 2, pow: 2,
};
/** The functions an expression may call. */
export type ExpressionFunctionName = 'abs' | 'sqrt' | 'ln' | 'log' | 'log10' | 'exp' | 'min' | 'max' | 'pow';

export class ExpressionError extends Error {
  public constructor(message: string, public readonly position: number) {
    super(`openalgo-charts: ${message}`);
    this.name = 'ExpressionError';
  }
}

// ── tokenizer ─────────────────────────────────────────────────────────────

type Tok =
  | { t: 'num'; v: number; i: number }
  | { t: 'sym'; v: string; i: number }
  | { t: 'op'; v: string; i: number };

/**
 * A symbol is letters, digits and the punctuation exchanges actually use:
 * `NSE:RELIANCE`, `NIFTY1!`, `BTCUSDT.P`, `ES1!`. `-` is NOT among them,
 * because it is also subtraction and no amount of lookahead settles
 * `A-B` in general. A symbol that contains one is written in quotes:
 * `'BRK-B'/SPY`.
 */
const SYM_START = /[A-Za-z_]/;
const SYM_BODY = /[A-Za-z0-9_.:!#&]/;

function tokenize(src: string): Tok[] {
  const out: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    // Each read of src[i] or src[j] here sits inside a loop that tests the
    // index against src.length.
    const c = src[i]!;
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r') { i++; continue; }

    if (c === "'" || c === '"') {
      const end = src.indexOf(c, i + 1);
      if (end === -1) throw new ExpressionError(`unclosed ${c} in expression`, i);
      const name = src.slice(i + 1, end);
      if (name === '') throw new ExpressionError('empty quoted symbol', i);
      out.push({ t: 'sym', v: name, i });
      i = end + 1;
      continue;
    }

    // A number, including a bare leading dot (`.5`). The exponent form is
    // deliberately absent: `1e3` would be indistinguishable from a ticker.
    if (/[0-9]/.test(c) || (c === '.' && /[0-9]/.test(src[i + 1] ?? ''))) {
      let j = i;
      while (j < src.length && /[0-9.]/.test(src[j]!)) j++;
      const raw = src.slice(i, j);
      const v = Number(raw);
      if (!Number.isFinite(v)) throw new ExpressionError(`"${raw}" is not a number`, i);
      out.push({ t: 'num', v, i });
      i = j;
      continue;
    }

    if (SYM_START.test(c)) {
      let j = i;
      while (j < src.length && SYM_BODY.test(src[j]!)) j++;
      // A trailing ':' is an exchange prefix the user has not finished typing.
      let name = src.slice(i, j);
      while (name.endsWith(':')) { name = name.slice(0, -1); j--; }
      out.push({ t: 'sym', v: name, i });
      i = j;
      continue;
    }

    if ('+-*/^(),'.includes(c)) { out.push({ t: 'op', v: c, i }); i++; continue; }
    // The keypad prints these; accept them so a pasted expression works.
    if (c === '×') { out.push({ t: 'op', v: '*', i }); i++; continue; }
    if (c === '÷') { out.push({ t: 'op', v: '/', i }); i++; continue; }
    if (c === '−') { out.push({ t: 'op', v: '-', i }); i++; continue; }

    throw new ExpressionError(`unexpected "${c}" in expression`, i);
  }
  return out;
}

// ── parser ────────────────────────────────────────────────────────────────

/** Binding power per binary operator. `^` is right associative. */
const BP: Record<string, number> = { '+': 1, '-': 1, '*': 2, '/': 2, '^': 3 };

function parse(toks: Tok[], src: string): ExpressionNode {
  let p = 0;
  const peek = (): Tok | undefined => toks[p];
  const at = (): number => peek()?.i ?? src.length;

  function primary(): ExpressionNode {
    const t = peek();
    if (t === undefined) throw new ExpressionError('expression ended early', src.length);
    if (t.t === 'num') { p++; return { k: 'num', v: t.v }; }
    if (t.t === 'sym') {
      p++;
      const fn = t.v.toLowerCase();
      if (fn in FN_ARITY && peek()?.t === 'op' && peek()?.v === '(') {
        p++;
        const args: ExpressionNode[] = [];
        if (!(peek()?.t === 'op' && peek()?.v === ')')) {
          for (;;) {
            args.push(expr(0));
            if (peek()?.t === 'op' && peek()?.v === ',') { p++; continue; }
            break;
          }
        }
        if (!(peek()?.t === 'op' && peek()?.v === ')')) throw new ExpressionError(`${fn}( is not closed`, at());
        p++;
        const want = FN_ARITY[fn as ExpressionFunctionName];
        if (args.length !== want) {
          throw new ExpressionError(`${fn}() takes ${want} argument${want === 1 ? '' : 's'}, got ${args.length}`, t.i);
        }
        return { k: 'fn', name: fn as ExpressionFunctionName, args };
      }
      return { k: 'sym', name: t.v };
    }
    if (t.v === '(') {
      p++;
      const inner = expr(0);
      if (!(peek()?.t === 'op' && peek()?.v === ')')) throw new ExpressionError('( is not closed', t.i);
      p++;
      return inner;
    }
    if (t.v === '-') { p++; return { k: 'neg', a: unary() }; }
    if (t.v === '+') { p++; return unary(); }
    throw new ExpressionError(`unexpected "${t.v}"`, t.i);
  }

  function unary(): ExpressionNode { return primary(); }

  function expr(min: number): ExpressionNode {
    let left = unary();
    for (;;) {
      const t = peek();
      if (t === undefined || t.t !== 'op' || !(t.v in BP)) break;
      const bp = BP[t.v]!; // t.v is in BP, checked just above
      if (bp < min) break;
      p++;
      // `^` binds tighter to its right, so it recurses at the same power
      // rather than one above it: 2^3^2 is 2^(3^2).
      const right = expr(t.v === '^' ? bp : bp + 1);
      left = { k: 'bin', op: t.v as '+' | '-' | '*' | '/' | '^', a: left, b: right };
    }
    return left;
  }

  const out = expr(0);
  const extra = toks[p];
  if (extra !== undefined) throw new ExpressionError(`unexpected "${extra.v}"`, extra.i);
  return out;
}

function collect(n: ExpressionNode, into: string[]): void {
  if (n.k === 'sym') { if (!into.includes(n.name)) into.push(n.name); return; }
  if (n.k === 'neg') { collect(n.a, into); return; }
  if (n.k === 'bin') { collect(n.a, into); collect(n.b, into); return; }
  if (n.k === 'fn') { for (const a of n.args) collect(a, into); }
}

/**
 * Parse `source` into an expression and the symbols it needs.
 *
 * ```ts
 * const e = parseExpression('NIFTY1!/NSE:RELIANCE');
 * e.symbols; // ['NIFTY1!', 'NSE:RELIANCE'] -> fetch exactly these
 * ```
 *
 * Throws `ExpressionError` with the offending character's index, so a search
 * box can underline it. A bare symbol parses too, which lets one code path
 * handle both an ordinary chart and a synthetic one.
 */
export function parseExpression(source: string): SymbolExpression {
  const toks = tokenize(source);
  if (toks.length === 0) throw new ExpressionError('expression is empty', 0);
  const ast = parse(toks, source);
  const symbols: string[] = [];
  collect(ast, symbols);
  if (symbols.length === 0) throw new ExpressionError('expression names no symbol', 0);
  return { source, symbols, ast };
}

/** True when `source` is a single plain symbol, needing no arithmetic. */
export function isPlainSymbol(source: string): boolean {
  try {
    const e = parseExpression(source);
    return e.ast.k === 'sym';
  } catch { return false; }
}

// ── evaluation ────────────────────────────────────────────────────────────

/** A value and, when bounding, the range it could have covered. */
interface Iv { lo: number; hi: number }

const NA: Iv = { lo: NaN, hi: NaN };
const bad = (v: Iv): boolean => !Number.isFinite(v.lo) || !Number.isFinite(v.hi);
const span = (xs: number[]): Iv => ({ lo: Math.min(...xs), hi: Math.max(...xs) });

function mul(a: Iv, b: Iv): Iv {
  return span([a.lo * b.lo, a.lo * b.hi, a.hi * b.lo, a.hi * b.hi]);
}

function div(a: Iv, b: Iv): Iv {
  // A divisor interval straddling zero has no finite bound: the quotient runs
  // to infinity on both sides, so the bar is a gap rather than a huge spike.
  if (b.lo <= 0 && b.hi >= 0) return NA;
  return span([a.lo / b.lo, a.lo / b.hi, a.hi / b.lo, a.hi / b.hi]);
}

function pow(a: Iv, b: Iv): Iv {
  // Only a fixed exponent is bounded here. A varying one would need the
  // exponent's own interval crossed with the base's, and the cases where the
  // base turns negative have no real result at all.
  if (b.lo !== b.hi) return NA;
  const e = b.lo;
  const xs = [Math.pow(a.lo, e), Math.pow(a.hi, e)];
  // An even power over an interval containing zero bottoms out at zero, not at
  // either endpoint.
  if (a.lo < 0 && a.hi > 0 && Number.isInteger(e) && e % 2 === 0) xs.push(0);
  return span(xs);
}

function absIv(a: Iv): Iv {
  if (a.lo >= 0) return a;
  if (a.hi <= 0) return { lo: -a.hi, hi: -a.lo };
  return { lo: 0, hi: Math.max(-a.lo, a.hi) };
}

/** Monotonic increasing functions map endpoints to endpoints. */
function mono(a: Iv, f: (x: number) => number): Iv {
  return span([f(a.lo), f(a.hi)]);
}

function evalNode(n: ExpressionNode, leg: (s: string) => Iv | null): Iv {
  switch (n.k) {
    case 'num': return { lo: n.v, hi: n.v };
    case 'sym': return leg(n.name) ?? NA;
    case 'neg': { const a = evalNode(n.a, leg); return bad(a) ? NA : { lo: -a.hi, hi: -a.lo }; }
    case 'bin': {
      const a = evalNode(n.a, leg);
      const b = evalNode(n.b, leg);
      if (bad(a) || bad(b)) return NA;
      switch (n.op) {
        case '+': return { lo: a.lo + b.lo, hi: a.hi + b.hi };
        case '-': return { lo: a.lo - b.hi, hi: a.hi - b.lo };
        case '*': return mul(a, b);
        case '/': return div(a, b);
        case '^': return pow(a, b);
      }
      return NA;
    }
    case 'fn': {
      const xs = n.args.map((x) => evalNode(x, leg));
      if (xs.some(bad)) return NA;
      // The parser checked each call's argument count against FN_ARITY, so
      // a is always there and b is for the two-argument functions.
      const [a, b] = xs as [Iv, Iv];
      switch (n.name) {
        case 'abs': return absIv(a);
        case 'sqrt': return a.lo < 0 ? NA : mono(a, Math.sqrt);
        case 'ln': case 'log': return a.lo <= 0 ? NA : mono(a, Math.log);
        case 'log10': return a.lo <= 0 ? NA : mono(a, Math.log10);
        case 'exp': return mono(a, Math.exp);
        case 'min': return { lo: Math.min(a.lo, b.lo), hi: Math.min(a.hi, b.hi) };
        case 'max': return { lo: Math.max(a.lo, b.lo), hi: Math.max(a.hi, b.hi) };
        case 'pow': return pow(a, b);
      }
      return NA;
    }
  }
}

/**
 * Fold the legs into one synthetic series.
 *
 * `legs` maps each symbol in `expr.symbols` to its bars. A symbol with no
 * entry, or a bar the primary has and a leg does not, yields no output bar: the
 * series gaps there rather than carrying a stale price forward, because a
 * ratio against yesterday's close is a number that was never true.
 *
 * ```ts
 * const e = parseExpression('NIFTY1!/NSE:RELIANCE');
 * const bars = evaluateExpression(e, { 'NIFTY1!': a, 'NSE:RELIANCE': b });
 * chart.addSeries('line').setData(bars);
 * ```
 *
 * Volume is absent by default. Opt into `volume: 'sum'` to report the combined
 * activity of the matched legs, independently of the price expression.
 * Open interest is always absent: an expression has no single contract position.
 */
export function evaluateExpression(
  expr: SymbolExpression,
  legs: Readonly<Record<string, readonly Bar[]>>,
  options: EvaluateOptions = {},
): Bar[] {
  const wantRange = options.ohlc === 'interval';
  // parseExpression refuses an expression that names no symbol.
  const primaryName = options.primary ?? expr.symbols[0]!;
  const grid = legs[primaryName];
  if (grid === undefined || grid.length === 0) return [];

  // One time index per non-primary leg. Built once, so the fold stays linear
  // rather than searching every leg for every bar.
  const index = new Map<string, Map<number, Bar>>();
  for (const s of expr.symbols) {
    if (s === primaryName) continue;
    const rows = legs[s];
    if (rows === undefined) return [];
    const m = new Map<number, Bar>();
    for (const b of rows) m.set(b.time, b);
    index.set(s, m);
  }

  const out: Bar[] = [];
  const cur = new Map<string, Bar>();
  for (const pb of grid) {
    cur.clear();
    cur.set(primaryName, pb);
    let whole = true;
    for (const [s, m] of index) {
      const b = m.get(pb.time);
      if (b === undefined) { whole = false; break; }
      cur.set(s, b);
    }
    if (!whole) continue;

    const pick = (field: 'open' | 'close') => (s: string): Iv | null => {
      const b = cur.get(s);
      return b === undefined ? null : { lo: b[field], hi: b[field] };
    };
    const open = evalNode(expr.ast, pick('open'));
    const close = evalNode(expr.ast, pick('close'));
    if (bad(open) || bad(close)) continue;

    let hi = Math.max(open.hi, close.hi);
    let lo = Math.min(open.lo, close.lo);
    if (wantRange) {
      const r = evalNode(expr.ast, (s) => {
        const b = cur.get(s);
        return b === undefined ? null : { lo: b.low, hi: b.high };
      });
      if (bad(r)) continue;
      // The bound can only widen what open and close already prove.
      hi = Math.max(hi, r.hi);
      lo = Math.min(lo, r.lo);
    }
    const result: Bar = { time: pb.time, open: open.lo, high: hi, low: lo, close: close.lo };
    if (options.volume === 'sum') {
      let volume = 0;
      for (const symbol of expr.symbols) {
        const amount = cur.get(symbol)?.volume;
        if (amount === undefined || !Number.isFinite(amount) || amount < 0) {
          volume = NaN;
          break;
        }
        volume += amount;
      }
      if (Number.isFinite(volume)) result.volume = volume;
    }
    out.push(result);
  }
  return out;
}
