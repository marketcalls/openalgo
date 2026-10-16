/**
 * The chart grid's own words, as message keys. They join the widget's
 * catalog through `WidgetBuiltinMessage`, so a host translates them with the
 * same `translate` function it gives every chart, and a typed host catalog
 * names them like any other key.
 */
import { widgetText, type WidgetTranslationOptions } from './localization';
import type { ChartGridLayoutId } from './grid-layouts';

export type ChartGridMessage =
  // Layout names, one per entry of CHART_GRID_LAYOUTS.
  | 'One chart' | 'Two columns' | 'Two rows' | 'Three columns' | 'Three rows' | 'Two by two' | 'Four columns' | 'Four rows'
  | 'Two rows of three' | 'Three rows of two' | 'Two rows of four' | 'Four rows of two' | 'Three by three'
  | 'Three rows of four' | 'Four rows of three' | 'Four by four'
  | 'Large left, two on the right' | 'Large right, two on the left' | 'Large top, two below' | 'Large bottom, two above'
  | 'Large left, three on the right' | 'Large top, three below' | 'Large left, four on the right' | 'Large top, four below'
  | 'Large corner, five around' | 'Large corner, seven around'
  // The bar and its menus.
  | 'Chart grid' | 'Arrange charts' | 'Arrange charts: {name}' | '1 chart' | '{count} charts' | '{name}, {count} charts' | 'Link: {name}'
  | 'Maximize the chart' | 'Restore the grid' | 'There is only one chart' | 'The grid shows one chart at a time at this width' | 'Link' | 'Linking' | 'Link group' | 'Not linked' | 'Group {letter}'
  | 'New group' | 'Rename group' | 'Group name' | 'Save' | 'Cancel' | 'Links in {group}'
  | 'Crosshair' | 'Time range' | 'Symbol' | 'Interval' | 'Chart type' | 'Appearance' | 'Drawings'
  | 'Nearest bar' | 'where a chart has no bar at that time' | 'same instrument only'
  | 'Share this chart\'s drawings' | 'Shared {count} drawing' | 'Shared {count} drawings' | 'No drawing here can be shared'
  | 'Link this chart to a group first' | 'Switch Drawings on first'
  | 'Capture every chart' | 'Every chart' | 'Download PNG of every chart' | 'Copy image of every chart'
  | 'Saved a PNG of every chart' | 'Every chart copied' | 'The image could not be saved: {error}'
  | 'Show every chart to capture them together'
  // Cells and their marks.
  | 'Chart {index}, linked in {name}' | 'Chart {index}, not linked' | 'Linked in {name}'
  // Chords, in the shortcuts panel's Chart grid section.
  | 'Maximize or restore the chart' | 'Make the chart to the left active' | 'Make the chart to the right active'
  | 'Make the chart above active' | 'Make the chart below active' | 'Swap with the chart to the left'
  | 'Swap with the chart to the right' | 'Swap with the chart above' | 'Swap with the chart below';

/** The name each layout shows in the picker and announces. */
export const CHART_GRID_LAYOUT_NAMES: Readonly<Record<ChartGridLayoutId, ChartGridMessage>> = {
  '1x1': 'One chart', '1x2': 'Two columns', '2x1': 'Two rows', '1x3': 'Three columns', '3x1': 'Three rows',
  'left-2': 'Large left, two on the right', 'right-2': 'Large right, two on the left',
  'top-2': 'Large top, two below', 'bottom-2': 'Large bottom, two above',
  '2x2': 'Two by two', '1x4': 'Four columns', '4x1': 'Four rows',
  'left-3': 'Large left, three on the right', 'top-3': 'Large top, three below',
  'left-4': 'Large left, four on the right', 'top-4': 'Large top, four below',
  '2x3': 'Two rows of three', '3x2': 'Three rows of two', 'corner-5': 'Large corner, five around',
  '2x4': 'Two rows of four', '4x2': 'Four rows of two', 'corner-7': 'Large corner, seven around',
  '3x3': 'Three by three', '3x4': 'Three rows of four', '4x3': 'Four rows of three', '4x4': 'Four by four',
};

/** A layout's name in the host's language. */
export function layoutName(text: WidgetTranslationOptions, id: ChartGridLayoutId): string {
  return widgetText(text, CHART_GRID_LAYOUT_NAMES[id]);
}

/** `1 chart` or `{count} charts`, the picker's group heads. */
export function chartCount(text: WidgetTranslationOptions, count: number): string {
  return count === 1 ? widgetText(text, '1 chart') : widgetText(text, '{count} charts', { count });
}
