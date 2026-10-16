/**
 * Chart linking: a grid of charts driven as one workspace. Part of the base
 * tier (it is a few hundred bytes and every multi-chart layout wants it), so
 * these names are re-exported from 'openalgo-charts'.
 */
export { LinkGroup, createLinkGroup } from './group';
export type { LinkChart, LinkOptions, LinkMemberOptions, ResolvedLinkOptions } from './group';
export { followerIndex, followerRange } from './align';
export type { LinkDataLayer, LinkMissingPolicy } from './align';
export { LinkCrosshair, LINK_CROSSHAIR_ALPHA } from './crosshair';
export { filterLinkAppearance } from './appearance';
export type { LinkAppearanceAdapter, LinkAppearanceValues } from './appearance';
export type { LinkDrawingsAdapter } from './drawings';
