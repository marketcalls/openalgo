/**
 * Chart theme (palette). A single object drives chart chrome (background, grid,
 * axes, crosshair), series defaults (up/down, line, area gradient, last price),
 * and the trade layer (buy/sell, profit/loss). Renderers read theme colors when
 * a per-series style field is absent, so one theme restyles the whole chart.
 */
export interface ChartTheme {
  background: string;
  grid: string;
  axisText: string;
  axisLine: string;
  /** 1px rule between stacked panes. Subtle: it separates, it does not divide. */
  paneSeparator: string;
  crosshair: string;
  /** Axis label font size in px (default 11). */
  axisFontSize?: number;
  /** Grid line dash style (default 'solid'). */
  gridStyle?: 'solid' | 'dashed' | 'dotted';
  /** Crosshair line dash style (default 'dashed'). */
  crosshairStyle?: 'solid' | 'dashed' | 'dotted';
  /** Crosshair line width in device px (default 1 = hairline). */
  crosshairWidth?: number;
  /** Background of the crosshair value tags (defaults to `crosshair`). */
  crosshairLabelBackground?: string;
  /** Show the crosshair price/time value tags (default true). */
  crosshairLabelVisible?: boolean;
  // candle / bar / column up & down
  upColor: string;
  downColor: string;
  wickUpColor: string;
  wickDownColor: string;
  // line / area
  lineColor: string;
  areaTopColor: string;
  areaBottomColor: string;
  // baseline
  baselineTopLine: string;
  baselineTopFill: string;
  baselineBottomLine: string;
  baselineBottomFill: string;
  // last-price tag
  lastPriceUp: string;
  lastPriceDown: string;
  lastPriceText: string;
  // trade layer
  buy: string;
  sell: string;
  profit: string;
  loss: string;
}

export const darkTheme: ChartTheme = {
  background: '#0d0e12',
  grid: '#161a26',
  axisText: '#8b91a7',
  axisLine: '#2a3046',
  paneSeparator: '#1e2334',
  crosshair: '#6b7280',
  upColor: '#26a69a',
  downColor: '#ef5350',
  wickUpColor: '#26a69a',
  wickDownColor: '#ef5350',
  lineColor: '#4f8cff',
  areaTopColor: 'rgba(79,140,255,0.40)',
  areaBottomColor: 'rgba(79,140,255,0.00)',
  baselineTopLine: '#26a69a',
  baselineTopFill: 'rgba(38,166,154,0.20)',
  baselineBottomLine: '#ef5350',
  baselineBottomFill: 'rgba(239,83,80,0.20)',
  lastPriceUp: '#26a69a',
  lastPriceDown: '#ef5350',
  lastPriceText: '#0d0e12',
  buy: '#26a69a',
  sell: '#ef5350',
  profit: '#26a69a',
  loss: '#ef5350',
};

export const lightTheme: ChartTheme = {
  background: '#ffffff',
  grid: '#eef1f6',
  axisText: '#5b6472',
  axisLine: '#d4dae3',
  paneSeparator: '#e6eaf0',
  crosshair: '#9aa3b2',
  upColor: '#089981',
  downColor: '#e0473e',
  wickUpColor: '#089981',
  wickDownColor: '#e0473e',
  lineColor: '#2962ff',
  areaTopColor: 'rgba(41,98,255,0.30)',
  areaBottomColor: 'rgba(41,98,255,0.00)',
  baselineTopLine: '#089981',
  baselineTopFill: 'rgba(8,153,129,0.18)',
  baselineBottomLine: '#e0473e',
  baselineBottomFill: 'rgba(224,71,62,0.18)',
  lastPriceUp: '#089981',
  lastPriceDown: '#e0473e',
  lastPriceText: '#ffffff',
  buy: '#089981',
  sell: '#e0473e',
  profit: '#089981',
  loss: '#e0473e',
};

export const DEFAULT_THEME = lightTheme;
