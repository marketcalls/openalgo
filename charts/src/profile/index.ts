// Profile tier (opt-in: "openalgo-charts/profile").
// Family C: Volume Profile + TPO (from OHLCV) and Footprint + Orderflow (which
// need classified trade data: see footprint.ts data-dependency note).

export const PROFILE_TIER = 'profile' as const;

export type { VolumeProfileResult, TpoResult, FootprintBar, FootprintCell } from './profile-model';
export { bucketPrice, priceBuckets } from './profile-model';
export { computeVolumeProfile, type VolumeProfileOptions } from './volume-profile';
export {
  computeVolumeProfileSessions,
  DEFAULT_VOLUME_PROFILE_FAMILY_OPTIONS,
  type VolumeProfileFamilyOptions,
  type VolumeProfileSession,
  type VolumeProfileLevel,
  type VolumeProfileSessionResult,
  type VolumeProfileFamilyResult,
} from './volume-profile-family';
export {
  VolumeProfile,
  DEFAULT_VOLUME_PROFILE_PRIMITIVE_OPTIONS,
  type VolumeProfilePrimitiveOptions,
  type VolumeDisplayMode,
  type VolumeProfileSide,
} from './volume-profile-primitive';
export { computeTpo } from './tpo';
export {
  computeMarketProfile,
  tpoLetter,
  rowTicksFor,
  nakedLevels,
  rowOf,
  inWindow,
  TRADING_HOURS,
  DEFAULT_MARKET_PROFILE_OPTIONS,
  type MarketProfileOptions,
  type MarketProfileSession,
  type MarketProfileLevel,
  type MarketProfilePeriod,
  type MarketProfileSessionResult,
  type MarketProfileResult,
  type SessionWindow,
  type DevelopingValue,
  type DayType,
  type OpenType,
} from './market-profile';
export {
  MarketProfile,
  TPO_PERIOD_COLORS,
  DEFAULT_MARKET_PROFILE_PRIMITIVE_OPTIONS,
  type MarketProfilePrimitiveOptions,
  type MarketProfileHover,
  type MpBlockDisplay,
  type MpColorMode,
} from './market-profile-primitive';
export {
  computeFootprint,
  diagonalImbalances,
  cumulativeDelta,
  stackedImbalances,
  type ClassifiedTrade,
  type FootprintBuildOptions,
  type Imbalance,
  type StackedImbalance,
} from './footprint';
export {
  createTradeClassifier,
  type TradePrint,
  type TradeClassification,
} from './footprint-classify';
export {
  footprintSignals,
  DEFAULT_FOOTPRINT_SIGNAL_OPTIONS,
  type FootprintSignalOptions,
  type FootprintSignals,
  type FootprintBarSignals,
  type FootprintZone,
  type FootprintZoneKind,
  type FootprintZoneEnd,
  type FootprintAuction,
} from './footprint-signals';
export {
  HorizontalProfile,
  type ProfileLevel,
  type HorizontalProfileOptions,
} from './profile-primitive';
export {
  Footprint,
  DEFAULT_FOOTPRINT_OPTIONS,
  compactVol,
  type FootprintOptions,
  type FootprintDisplayMode,
  type FootprintCellStyle,
  type FootprintTextColorMode,
  type FootprintStatRow,
  type FootprintBarStats,
  type FootprintHover,
  type FootprintZoneGroup,
  type FootprintZoneAlert,
} from './footprint-primitive';
export { FOOTPRINT_THEMES, type FootprintThemeName, type FootprintThemeColors } from './footprint-themes';
export {
  FootprintAggregator,
  type FootprintTick,
  type FootprintUpdate,
} from './footprint-aggregator';
