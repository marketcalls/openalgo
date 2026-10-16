/**
 * The shape of a form in one of the engine's dialogs.
 *
 * Reported from an application whose own controls are 32px at an 8px corner:
 * the engine's dialogs read as a window from somewhere else. Two things were
 * behind it, and only one of them was a matter of taste.
 *
 * The taste part is that the defaults are a step smaller than that application
 * wanted. A host can say so, and the tokens are how: `--oac-ctl-h`, `--oac-fs`,
 * `--oac-radius`. Except that every field hardcoded its own 6px corner, so
 * setting `--oac-radius` rounded the panel and left the fields inside it on the
 * old corner. That is a theming surface that does not reach what it claims to.
 *
 * The other part was not taste. A row's control column was one width, a lone
 * number sat at 72px against its right edge, and one row widened the column for
 * itself. Reading down the form the left edge of the controls stepped in and
 * out by ninety pixels. Nothing was out by a pixel, which is the sort of thing
 * that gets noticed; it was out by a lot, which somehow is not.
 *
 * Asserted against the stylesheet the engine emits, because that is the whole
 * of what these rules are. A screenshot would say the same and would never fail
 * on a machine without a browser.
 */
import { describe, expect, it } from 'vitest';
import { WIDGET_CSS } from '../src/widget/styles';
import { DIALOG_CSS } from '../src/widget/dialogs/index';
import { selectBox } from '../src/widget/form';
import { fakeWidgetDocument } from './helpers/fake-dom-widget';

/**
 * The rules in a stylesheet, as a selector list and a body.
 *
 * Comments go first. Everything between one rule's `}` and the next rule's `{`
 * is that rule's selector, and a comment above it lands inside that: the block
 * above `.oac-btn` says "28px tall", so the selector reads as the comment plus
 * the selector and matches nothing anybody would look for.
 */
function rules(css: string): { selectors: string[]; body: string }[] {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
  return [...stripped.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((rule) => ({
    selectors: rule[1].split(',').map((one) => one.trim()).filter(Boolean),
    body: rule[2],
  }));
}

/**
 * The bodies of every rule whose selector list contains exactly this selector.
 *
 * Matched against the whole list rather than by substring, because
 * `.oac-row__ctl` is a prefix of `.oac-row__ctl input[type=number]` and a
 * substring match would read one rule's width as the other's.
 */
function bodies(css: string, selector: string): string[] {
  return rules(css)
    .filter((rule) => rule.selectors.includes(selector))
    .map((rule) => rule.body);
}

/** Every declaration of one property across those rules. */
function declarations(css: string, selector: string, property: string): string[] {
  const out: string[] = [];
  for (const body of bodies(css, selector)) {
    for (const found of body.matchAll(new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`, 'g'))) {
      out.push(found[1].trim());
    }
  }
  return out;
}

describe('a host that sets the corner reaches the fields', () => {
  const FIELDS = [
    '.oac-widget select',
    '.oac-widget input[type=color]',
    '.oac-widget input[type=text]',
    '.oac-widget .oac-btn',
  ];

  it.each(FIELDS)('%s takes its corner from the token', (selector) => {
    const radii = declarations(WIDGET_CSS, selector, 'border-radius');
    expect(radii.length).toBeGreaterThan(0);
    for (const radius of radii) expect(radius).toBe('var(--oac-radius)');
  });

  it('leaves no form control with a corner of its own', () => {
    // The check that catches the next one added, which is the only kind worth
    // having here: naming the four above would pass forever while a fifth
    // field shipped with a hardcoded corner. Pseudo-elements are excluded,
    // because the swatch inside a colour input is a detail of that control
    // rather than a field a host is theming.
    for (const rule of rules(WIDGET_CSS)) {
      const isField = rule.selectors.some((one) =>
        /^\.oac-widget (?:select|input\[type=(?:text|number|search|color)\]|textarea|\.oac-btn)$/.test(one)
      );
      if (!isField) continue;
      expect(rule.body, rule.selectors.join(', ')).not.toMatch(/border-radius:\s*\d/);
    }
  });

  it('sizes every field from the control height, not from a number', () => {
    for (const selector of [
      '.oac-widget select',
      '.oac-widget input[type=text]',
      '.oac-widget .oac-btn',
    ]) {
      const heights = declarations(WIDGET_CSS, selector, 'height');
      expect(heights.length, selector).toBeGreaterThan(0);
      for (const height of heights) expect(height, selector).toBe('var(--oac-ctl-h)');
    }
  });

  it('holds the date field to the same height and corner as the rest', () => {
    // It had a 28px height and a 6px corner written into it, so it was the one
    // control in the alert editor that ignored what the host asked for.
    const body = bodies(DIALOG_CSS, '.oac-widget .oac-alert-editor input[type=datetime-local]')[0];
    expect(body).toBeDefined();
    expect(body).toContain('height: var(--oac-ctl-h)');
    expect(body).toContain('border-radius: var(--oac-radius)');
    expect(body).not.toMatch(/height:\s*\d/);
  });
});

describe('every row in a form lines up to one column', () => {
  it('declares the control column once, and once only', () => {
    // The width itself is a taste call and is free to move. What must not move
    // is that there is exactly one of it: the bug was a second declaration
    // elsewhere, and pinning the number here would have turned every retune
    // into an edit of this line and taught nobody anything.
    const widths = declarations(DIALOG_CSS, '.oac-widget .oac-row__ctl', 'width');
    expect(widths).toHaveLength(1);
    expect(widths[0]).toMatch(/^min\(\d+px, \d+%\)$/);
  });

  it('gives no single row a column of its own', () => {
    // `[data-key=expiresAt] .oac-row__ctl { width: 224px }` was exactly this,
    // and it is what made the date row start sixty pixels left of every other
    // control in the editor.
    for (const rule of rules(DIALOG_CSS)) {
      if (!rule.selectors.some((one) => /\[data-key=[^\]]+\].*\.oac-row__ctl/.test(one))) continue;
      expect(rule.body, rule.selectors.join(', ')).not.toMatch(/(?:^|;)\s*width\s*:/);
    }
  });

  it('fills the column with a number that is the only control in it', () => {
    // A number paired with a slider keeps its narrow box: there the width is
    // the point. A number on its own was leaving ninety pixels of nothing to
    // its left, in a column every other row filled.
    expect(
      declarations(DIALOG_CSS, '.oac-widget .oac-row__ctl > input[type=number]:only-child', 'width')
    ).toEqual(['100%']);
    expect(declarations(DIALOG_CSS, '.oac-widget .oac-row__ctl input[type=number]', 'width')).toEqual(
      ['72px']
    );
  });

  it('fills the column with a select rather than a fixed width beside it', () => {
    // 164px against a 164px column agreed by coincidence. The two are no
    // longer two numbers that have to be kept the same by hand.
    expect(declarations(DIALOG_CSS, '.oac-widget .oac-row__ctl .oac-select', 'width')).toEqual([
      '100%',
    ]);
  });
});

describe('the chevron rule names the element the builder makes', () => {
  it('positions the chevron over the select rather than beside it', () => {
    // The bug this pins: the stylesheet positioned `.oac-select > svg`, and
    // `selectBox` has always wrapped the glyph in a span. The rule matched
    // nothing, so the span stayed an ordinary flex item, took eleven pixels of
    // the row, and left the select eleven pixels short of every input beside it
    // with its arrow outside its own box. A selector that matches nothing is
    // invisible to every test that reads either side on its own, so this reads
    // both: it builds the real element and asks the real selector.
    const doc = fakeWidgetDocument();
    const { wrap } = selectBox(doc as unknown as Document);
    // The select first, then the glyph it appends beside it.
    const children = (wrap as unknown as { children: { matches(s: string): boolean }[] }).children
    expect(children, 'selectBox no longer appends a glyph beside the select').toHaveLength(2)
    const chevron = children[1]

    const positioned = rules(WIDGET_CSS).filter(
      (rule) =>
        rule.selectors.some((one) => /^\.oac-widget \.oac-select > /.test(one)) &&
        /position:\s*absolute/.test(rule.body)
    );
    expect(positioned, 'nothing in the sheet lifts the chevron out of flow').toHaveLength(1);

    // The selector, minus the `.oac-widget` ancestor the element has no parent
    // for here, has to match what the builder actually appended.
    const selector = positioned[0].selectors
      .find((one) => /^\.oac-widget \.oac-select > /.test(one))!
      .replace('.oac-widget .oac-select > ', '');
    expect(chevron?.matches(selector), `${selector} does not match the chevron`).toBe(true);
  });
})
