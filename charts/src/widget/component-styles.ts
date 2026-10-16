import { DIALOG_CSS } from './dialogs/index';
import { OBJECTS_PANEL_CSS } from './objects-panel';
import { EVENT_DETAILS_CSS } from './event-details';
import { DATA_WINDOW_CSS } from './data-window';
import { PANEL_DOCK_CSS } from './panel-dock';
import { SYMBOL_PICKER_CSS } from './symbol-picker';
import { QUICK_ENTRY_CSS } from './quick-entry';
import { COLOR_PICKER_CSS } from './color-picker';
import { INDICATOR_PICKER_CSS } from './dialogs/indicator-picker';
import { DATE_NAVIGATION_CSS } from './date-navigation-dialog';
import { CHART_GRID_CSS } from './grid-styles';
import { WATCHLIST_PANEL_CSS } from './watchlist-panel';
import { NEWS_PANEL_CSS } from './news-panel';
import { ACCOUNT_SUMMARY_CSS } from './account-summary';
import { DRAWING_TOOLBAR_CSS } from './drawing-toolbar';
import { DRAWING_TEMPLATES_CSS } from './drawing-templates';
import { DRAWING_COORDINATES_CSS } from './dialogs/drawing-coordinates';
// The bottom bar's rules ride the shared sheet, so a custom host's bar is styled under CSP too.
import { BOTTOMBAR_CSS } from './bottombar';
import { LAYOUTS_BUTTON_CSS } from './layouts-widget';

/** Shared first-mount styles keep embedded hosts and full widgets identical under CSP. */
export const WIDGET_COMPONENT_CSS = DIALOG_CSS + OBJECTS_PANEL_CSS + EVENT_DETAILS_CSS
  + DATA_WINDOW_CSS + PANEL_DOCK_CSS + SYMBOL_PICKER_CSS + QUICK_ENTRY_CSS + COLOR_PICKER_CSS + INDICATOR_PICKER_CSS + DATE_NAVIGATION_CSS
  + CHART_GRID_CSS + WATCHLIST_PANEL_CSS + NEWS_PANEL_CSS + ACCOUNT_SUMMARY_CSS
  + DRAWING_TOOLBAR_CSS + DRAWING_TEMPLATES_CSS + DRAWING_COORDINATES_CSS + BOTTOMBAR_CSS + LAYOUTS_BUTTON_CSS;
