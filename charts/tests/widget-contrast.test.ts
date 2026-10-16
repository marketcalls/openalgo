/**
 * The widget's text tokens read at the WCAG AA minimum on every surface they
 * are painted on, in both built-in themes and in a host's own theme.
 *
 * Faint text (section heads, chords, hints, the interval beside the symbol)
 * measured 2.2 to 2.9 to 1 against its panels in both themes, and the
 * watchlist painted every rise in the dark theme's green whatever the theme,
 * 2.9 to 1 on a light panel.
 */
import { describe, expect, it } from 'vitest';
import { darkTheme, lightTheme, type ChartTheme } from '../src/index';
import {
  contrastRatio, readableOn, widgetTokens, TEXT_CONTRAST, WATCHLIST_PANEL_CSS, WIDGET_CSS, DIALOG_CSS,
} from '../src/widget/index';

const THEMES: Array<[string, ChartTheme]> = [
  ['dark', darkTheme],
  ['light', lightTheme],
  // A host palette whose axis text is a dim grey on navy and whose candles are pastel.
  ['host navy', { ...darkTheme, background: '#101a2c', axisText: '#4a5568', upColor: '#1f6f5c', downColor: '#8a2d2d' }],
  ['host paper', { ...lightTheme, background: '#fbf7ef', axisText: '#b0aa9e', upColor: '#7fd1b9', downColor: '#f4a3a3' }],
];

const token = (tokens: Record<string, string>, name: string): string => tokens[`--oac-${name}`];
const RESTING = ['bg', 'panel', 'panel-2', 'elev'];

describe('widget text contrast', () => {
  it.each(THEMES)('faint, up, down and amber text read on every resting surface in the %s theme', (_name, theme) => {
    const t = widgetTokens(theme);
    for (const role of ['faint', 'up', 'down', 'amber']) {
      for (const surface of RESTING) {
        const ratio = contrastRatio(token(t, role), token(t, surface));
        expect(ratio, `${role} on ${surface}: ${token(t, role)} on ${token(t, surface)}`).toBeGreaterThanOrEqual(TEXT_CONTRAST);
      }
    }
  });

  it.each(THEMES)('muted and error text read on the hovered step too in the %s theme', (_name, theme) => {
    const t = widgetTokens(theme);
    for (const role of ['mut', 'danger']) {
      for (const surface of [...RESTING, 'elev-2']) {
        expect(contrastRatio(token(t, role), token(t, surface)), `${role} on ${surface}`).toBeGreaterThanOrEqual(TEXT_CONTRAST);
      }
    }
  });

  it.each(THEMES)('keeps faint dimmer than muted text in the %s theme', (_name, theme) => {
    // Lifted only as far as the minimum, so the hierarchy survives.
    const t = widgetTokens(theme);
    expect(contrastRatio(token(t, 'faint'), token(t, 'bg'))).toBeLessThanOrEqual(contrastRatio(token(t, 'mut'), token(t, 'bg')));
  });

  it('follows the theme for the watchlist pair rather than one palette', () => {
    const dark = widgetTokens(darkTheme);
    const light = widgetTokens(lightTheme);
    expect(token(dark, 'up')).toBe(darkTheme.upColor);
    expect(token(light, 'up')).not.toBe(token(dark, 'up'));
    expect(WATCHLIST_PANEL_CSS).toContain('.is-up { color: var(--oac-up); }');
    expect(WATCHLIST_PANEL_CSS).toContain('.is-down { color: var(--oac-down); }');
    // No colour literal may stand in for the token.
    expect(WATCHLIST_PANEL_CSS).not.toMatch(/var\(--oac-(?:up|down),/);
  });

  it('brightens hints on the hovered step, where faint no longer reads', () => {
    const t = widgetTokens(darkTheme);
    expect(contrastRatio(token(t, 'faint'), token(t, 'elev-2'))).toBeLessThan(TEXT_CONTRAST);
    expect(WIDGET_CSS).toMatch(/\.oac-tip__sub \{[^}]*color: var\(--oac-mut\)/);
    expect(WIDGET_CSS).toMatch(/\.oac-menu__row:is\(:hover, :focus-visible, \.is-active\) :is\(\.oac-menu__sub, \.oac-menu__key\),\n[^{]*\{ color: var\(--oac-mut\)/);
    expect(DIALOG_CSS).toMatch(/\.oac-ctx__row:is\(:hover, :focus-visible\) :is\(\.oac-ctx__note, \.oac-ctx__key\) \{ color: var\(--oac-mut\)/);
  });

  it('lifts a colour by the least amount, and leaves one that reads alone', () => {
    expect(readableOn('#26a69a', ['#15161a'], '#ffffff')).toBe('#26a69a');
    const lifted = readableOn('#26a69a', ['#fafafb'], '#0c1120');
    expect(contrastRatio(lifted, '#fafafb')).toBeGreaterThanOrEqual(TEXT_CONTRAST);
    expect(contrastRatio(lifted, '#fafafb')).toBeLessThan(TEXT_CONTRAST + 0.2);
    // A pole that cannot reach the minimum is the best there is.
    expect(readableOn('#777777', ['#808080'], '#999999')).toBe('#999999');
  });
});
