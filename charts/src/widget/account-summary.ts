/**
 * The account summary: the selected account, its equity and margin, and
 * whether those figures are current. Apart from switching account it is
 * read-only, with no order control beside it, so choosing an account is never
 * one misplaced click away from sending something.
 *
 * It shows what the source reports and nothing it does not. A source whose
 * provider declares no account data renders disabled with that provider's
 * reason, the way a control with no data in the current context is shown.
 * Figures from before a dropped connection stay visible, marked stale, rather
 * than vanishing or passing for current ones.
 */
import type { AccountSnapshot, AccountStateSource } from 'openalgo-charts/trade';
import { chromeIconSvg } from 'openalgo-charts/draw';
import { h, type WidgetContext } from './context';
import { errorText, widgetText } from './localization';
import { openMenu } from './menu';

export interface AccountSummaryOptions {
  /** Usually an `AccountManager` from the trade tier. */
  source: AccountStateSource;
  /** BCP 47 tag for the figures. Default: the widget's. */
  locale?: string | undefined;
}

export interface AccountSummaryHandle {
  readonly el: HTMLElement;
  /** Re-read the source and repaint. */
  refresh(): void;
  destroy(): void;
}

/** Mount the summary into `host`, before its timezone readout when it has one. */
export function mountAccountSummary(ctx: WidgetContext, host: HTMLElement, options: AccountSummaryOptions): AccountSummaryHandle {
  const doc = ctx.document;
  const source = options.source;
  const locale = options.locale ?? ctx.locale;
  const el = h(doc, 'span', 'oac-account', { role: 'group', 'aria-label': widgetText(ctx, 'Account') });
  const pick = h(doc, 'button', 'oac-account__pick', { type: 'button', 'aria-haspopup': 'menu' });
  const name = h(doc, 'span', 'oac-account__name');
  const chevron = h(doc, 'span', 'oac-chev');
  chevron.innerHTML = chromeIconSvg('chevron-down');
  pick.appendChild(name);
  pick.appendChild(chevron);
  el.appendChild(pick);
  const field = (cls: string, label: string): { el: HTMLElement; val: HTMLElement } => {
    const f = h(doc, 'span', `oac-account__field ${cls}`);
    const i = h(doc, 'i');
    i.textContent = label;
    const b = h(doc, 'b');
    f.appendChild(i);
    f.appendChild(b);
    el.appendChild(f);
    return { el: f, val: b };
  };
  const equity = field('oac-account__equity', widgetText(ctx, 'Equity'));
  const used = field('oac-account__used', widgetText(ctx, 'Margin used'));
  const available = field('oac-account__available', widgetText(ctx, 'Available'));
  const state = h(doc, 'span', 'oac-account__state');
  el.appendChild(state);
  const tz = host.querySelector('.oac-statusline__tz');
  if (tz !== null && tz.parentNode === host) host.insertBefore(el, tz);
  else host.appendChild(el);
  // Lets a crowded status line give the summary room before its hover time.
  host.classList.add('oac-has-account');

  const formats = new Map<string, Intl.NumberFormat>();
  const money = (value: number, currency: string | undefined): string => {
    const key = currency ?? '';
    let format = formats.get(key);
    if (format === undefined) {
      const plain = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
      try {
        format = new Intl.NumberFormat(locale, currency === undefined ? plain : { ...plain, style: 'currency', currency });
      } catch {
        // A code the runtime does not know is still a number worth showing.
        format = new Intl.NumberFormat(locale, plain);
      }
      formats.set(key, format);
    }
    return format.format(value);
  };
  const write = (node: HTMLElement, text: string): void => { if (node.textContent !== text) node.textContent = text; };
  const show = (node: HTMLElement, on: boolean): void => { if (node.hidden === on) node.hidden = !on; };
  const figure = (f: { el: HTMLElement; val: HTMLElement }, value: number | undefined, snapshot: AccountSnapshot | null): void => {
    show(f.el, snapshot !== null && value !== undefined);
    if (snapshot !== null && value !== undefined) write(f.val, money(value, snapshot.currency));
  };
  let tag: HTMLElement | null = null;

  const render = (): void => {
    const s = source.getState();
    el.dataset.status = s.status;
    const unsupported = s.status === 'unsupported';
    el.classList.toggle('is-disabled', unsupported);
    if (unsupported) el.setAttribute('aria-disabled', 'true');
    else el.removeAttribute('aria-disabled');
    const account = s.accounts.find(a => a.id === s.selectedId);
    const label = account === undefined ? widgetText(ctx, 'Account') : (account.name ?? account.id);
    write(name, label);
    pick.setAttribute('aria-label', account === undefined ? label : widgetText(ctx, 'Account: {name}', { name: label }));
    pick.disabled = unsupported || s.accounts.length === 0;
    // The ledger is named whenever it is the sandbox one, so a sandbox balance
    // can never be read as money in the live account.
    const analyzer = !unsupported && s.mode === 'analyzer';
    if (analyzer && tag === null) {
      tag = h(doc, 'span', 'oac-account__tag');
      tag.textContent = widgetText(ctx, 'Analyzer');
      el.insertBefore(tag, equity.el);
    } else if (!analyzer && tag !== null) {
      tag.remove();
      tag = null;
    }
    const snapshot = unsupported ? null : s.snapshot;
    figure(equity, snapshot?.equity, snapshot);
    figure(used, snapshot?.marginUsed, snapshot);
    figure(available, snapshot?.marginAvailable, snapshot);
    // A narrow status line drops the figures; the picker still carries them.
    pick.title = [equity, used, available].filter(f => !f.el.hidden)
      .map(f => `${f.el.firstChild?.textContent ?? ''} ${f.val.textContent ?? ''}`).join(', ');
    const text = unsupported || s.status === 'error' ? s.reason ?? ''
      : s.status === 'stale' ? widgetText(ctx, 'Stale')
        : s.status === 'loading' ? widgetText(ctx, 'Loading account') : '';
    write(state, text);
    state.title = s.reason ?? '';
    state.classList.toggle('is-error', s.status === 'error');
    state.classList.toggle('is-stale', s.status === 'stale');
    show(state, text !== '');
  };

  const onPick = (): void => {
    const s = source.getState();
    if (s.status === 'unsupported' || s.accounts.length === 0) return;
    openMenu(ctx, pick, s.accounts.map(account => ({
      label: account.name ?? account.id,
      sub: account.id,
      on: account.id === s.selectedId,
      onSelect: () => {
        const failed = (reason: string): void => { ctx.toast(widgetText(ctx, 'Could not switch account: {error}', { error: reason }), 'error'); };
        void source.select(account.id).then(
          result => { if (!result.ok && result.cancelled !== true) failed(result.reason); },
          (error: unknown) => failed(errorText(ctx, error)),
        );
      },
    })), { ariaLabel: widgetText(ctx, 'Accounts') });
  };
  pick.addEventListener('click', onPick);
  const off = source.subscribe(render);
  render();

  return {
    el,
    refresh: render,
    destroy: () => {
      off();
      pick.removeEventListener('click', onPick);
      host.classList.remove('oac-has-account');
      el.remove();
    },
  };
}

// In a crowded status line the hover time yields first, then the figures in
// order of importance. Narrower still, the summary moves up beside the title,
// so what the row clips is a bar reading, never the account or its ledger.
export const ACCOUNT_SUMMARY_CSS = `
.oac-widget .oac-statusline.oac-has-account{container:oac-status/inline-size}
.oac-widget .oac-statusline.oac-has-account .oac-statusline__time{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis}
.oac-widget .oac-statusline .oac-account{flex:none}
.oac-widget .oac-account>.oac-account__pick,.oac-widget .oac-account>.oac-account__tag,.oac-widget .oac-account>.oac-account__field{flex:none}
.oac-widget .oac-account{display:inline-flex;align-items:center;gap:10px;min-width:0;white-space:nowrap;font-variant-numeric:tabular-nums}
.oac-widget .oac-account__pick{display:inline-flex;align-items:center;gap:4px;max-width:180px;height:20px;padding:0 6px;border:1px solid var(--oac-bd);border-radius:5px;background:var(--oac-elev);color:var(--oac-tx-strong);font-size:11.5px;font-weight:600}
.oac-widget .oac-account__pick:hover:not(:disabled){border-color:var(--oac-bd-hover)}
.oac-widget .oac-account__pick:disabled{cursor:not-allowed;color:var(--oac-faint)}
.oac-widget .oac-account__name{min-width:0;overflow:hidden;text-overflow:ellipsis}
.oac-widget .oac-account__pick .oac-chev{display:inline-grid;width:10px;height:10px;color:var(--oac-mut)}
.oac-widget .oac-account__tag{padding:0 5px;border:1px solid var(--oac-bd-soft);border-radius:4px;color:var(--oac-amber);font-size:10px;font-weight:600;letter-spacing:.5px;text-transform:uppercase}
.oac-widget .oac-account__field{display:inline-flex;align-items:center;gap:4px}
.oac-widget .oac-account__field>i{font-style:normal;color:var(--oac-faint)}
.oac-widget .oac-account__field>b{font-weight:500;color:var(--oac-tx)}
.oac-widget .oac-account__state{min-width:0;max-width:320px;overflow:hidden;text-overflow:ellipsis;color:var(--oac-mut)}
.oac-widget .oac-account__state.is-stale{color:var(--oac-amber)}
.oac-widget .oac-account__state.is-error{color:var(--oac-danger)}
.oac-widget .oac-account.is-disabled .oac-account__state{color:var(--oac-faint)}
.oac-widget .oac-account[data-status="stale"] .oac-account__field>b{color:var(--oac-mut)}
@container oac-status (max-width:1180px){.oac-widget .oac-account__used{display:none}}
@container oac-status (max-width:1000px){.oac-widget .oac-account__equity{display:none}}
@container oac-status (max-width:860px){.oac-widget .oac-account__available{display:none}
.oac-widget .oac-statusline .oac-statusline__title{order:-2}.oac-widget .oac-statusline .oac-account{order:-1}}
`;
