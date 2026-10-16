/**
 * Named colour sets for a footprint (since 2.6.4). Each is a plain options
 * patch, so a host spreads one under its own choices:
 * `new Footprint({ ...FOOTPRINT_THEMES.ocean, displayMode: 'bidask' })`.
 * Daylight is for a light chart; the others are for a dark one. A theme sets
 * colours only, never the chart's background.
 */
import type { FootprintOptions } from './footprint-primitive';

export type FootprintThemeName = 'ocean' | 'ember' | 'forest' | 'neon' | 'monochrome' | 'daylight';

/** The colours a theme sets, each an optional `FootprintOptions` colour. */
export type FootprintThemeColors = Readonly<Pick<FootprintOptions,
  'buyColor' | 'sellColor' | 'volumeColor' | 'candleUpColor' | 'candleDownColor' | 'textColor' | 'imbalanceBuyColor' | 'imbalanceSellColor'
  | 'lastPriceColor' | 'pocColor' | 'nodeColor' | 'divergenceColor' | 'bigOrderColor' | 'absorptionColor' | 'auctionHighColor' | 'auctionLowColor'
  | 'profileAskColor' | 'profileBidColor' | 'sessionColor' | 'tableBackground'>>;

/** The options a theme sets, in the order its colours are listed below. */
const KEYS: readonly (keyof FootprintThemeColors)[] = [
  'buyColor', 'sellColor', 'volumeColor', 'candleUpColor', 'candleDownColor', 'textColor', 'imbalanceBuyColor', 'imbalanceSellColor',
  'lastPriceColor', 'pocColor', 'nodeColor', 'divergenceColor', 'bigOrderColor', 'absorptionColor', 'auctionHighColor', 'auctionLowColor',
  'profileAskColor', 'profileBidColor', 'sessionColor', 'tableBackground',
];

const theme = (colors: string): FootprintThemeColors =>
  Object.freeze(Object.fromEntries(colors.split(' ').map((hex, i) => [KEYS[i], `#${hex}`]))) as FootprintThemeColors;

export const FOOTPRINT_THEMES: Readonly<Record<FootprintThemeName, FootprintThemeColors>> = Object.freeze({
  ocean: theme('1E88E5 E53935 90A4AE 26C6DA FF7043 ECEFF1 00ACC1 F4511E 4DD0E1 FFFFFF FFD54F FFB300 40C4FF B39DDB 26C6DA FF7043 0097A7 E53935 00796B 0D1B2A'),
  ember: theme('FF8F00 C62828 BCAAA4 FFB300 D84315 FFF8E1 FFC107 E53935 FFEB3B FFFFFF FFF176 FF6E40 FFD180 CE93D8 FFCA28 EF5350 FB8C00 B71C1C 8D6E63 1E1410'),
  forest: theme('2E7D32 AD1457 A5D6A7 66BB6A EC407A F1F8E9 43A047 D81B60 C6FF00 FFFFFF FFEE58 FFA726 80DEEA CE93D8 66BB6A F06292 388E3C C2185B 558B2F 102017'),
  neon: theme('00B8D4 FF1744 B388FF 00E676 FF3D00 FFFFFF 00E676 FF1744 FFEA00 FFFFFF FFEA00 FF9100 18FFFF D500F9 76FF03 FF4081 00B8D4 F50057 651FFF 0A0A14'),
  monochrome: theme('B0BEC5 546E7A CFD8DC ECEFF1 78909C FFFFFF E0E0E0 616161 90A4AE FFFFFF BDBDBD FFFFFF FFFFFF 9E9E9E E0E0E0 757575 90A4AE 455A64 607D8B 121212'),
  daylight: theme('1976D2 D32F2F 546E7A 2E7D32 C62828 1A1A1A 43A047 E53935 4DD0E1 000000 FBC02D F57C00 0288D1 7E57C2 2E7D32 C62828 4A9AA5 E57373 C27A3A ECEFF1'),
});
