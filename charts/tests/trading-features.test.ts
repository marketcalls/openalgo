import { describe, expect, it, vi } from 'vitest';
import { checkTradingFeature, ORDER_DURATIONS, type TradingFeatureRequest, type TradingFeatures } from '../src/trade/features';

// Unlike the original place/modify/cancel flags, where an omission keeps the
// legacy route open, every newer operation is refused until a provider declares
// it. A silent default of "supported" here would let a host believe a close was
// native when nothing on the wire could carry it.
describe('advanced trading feature declarations', () => {
  it('refuses an operation that no source declares', () => {
    expect(checkTradingFeature(undefined, { feature: 'close' })).toEqual({
      supported: false, reason: 'Closing a position is not declared by this provider',
    });
    expect(checkTradingFeature({}, { feature: 'accounts' })).toEqual({
      supported: false, reason: 'Account data is not declared by this provider',
    });
  });

  it('distinguishes declared support, refusal and unknown support', () => {
    const features: TradingFeatures = { reverse: true, partialClose: false, brackets: 'unknown' };
    expect(checkTradingFeature(features, { feature: 'reverse' })).toEqual({ supported: true });
    expect(checkTradingFeature(features, { feature: 'partialClose' })).toEqual({ supported: false, reason: 'Partial close is not supported' });
    expect(checkTradingFeature(features, { feature: 'brackets' })).toEqual({ supported: false, reason: 'Support for bracket placement is unknown' });
  });

  it('accepts only the durations a provider lists', () => {
    const features: TradingFeatures = { durations: ['DAY', 'GTD'] };
    expect(checkTradingFeature(features, { feature: 'duration', duration: 'GTD' })).toEqual({ supported: true });
    expect(checkTradingFeature(features, { feature: 'duration', duration: 'IOC' })).toEqual({ supported: false, reason: 'Duration IOC is not supported' });
    expect(checkTradingFeature(features, { feature: 'duration' }).supported).toBe(false);
    expect(checkTradingFeature({}, { feature: 'duration', duration: 'DAY' })).toEqual({
      supported: false, reason: 'Order duration is not declared by this provider',
    });
    expect(checkTradingFeature({ durations: 'DAY' as unknown as never }, { feature: 'duration', duration: 'DAY' }).supported).toBe(false);
    expect(ORDER_DURATIONS).toEqual(['DAY', 'IOC', 'FOK', 'GTC', 'GTD']);
  });

  it('treats a provider that cannot answer as unavailable, and hands it a frozen request', () => {
    const provider = vi.fn((_request: Readonly<TradingFeatureRequest>) => undefined);
    expect(checkTradingFeature(provider, { feature: 'preview', symbol: 'SYN', mode: 'analyzer' })).toEqual({
      supported: false, reason: 'Trading features are unavailable',
    });
    expect(Object.isFrozen(provider.mock.calls[0][0])).toBe(true);
    expect(checkTradingFeature(() => { throw new Error('metadata lost'); }, { feature: 'preview' }).supported).toBe(false);
    expect(checkTradingFeature((() => Promise.resolve({ preview: true })) as never, { feature: 'preview' }).supported).toBe(false);
  });
});
