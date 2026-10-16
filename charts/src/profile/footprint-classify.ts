/**
 * Aggressor classification for raw prints, for feeds that do not mark each trade
 * as hitting the bid or lifting the ask. A footprint is only as honest as this
 * step, so the rule is spelled out rather than guessed per call site.
 */

/** A raw print. `bid` and `ask` are the quote at the time of the trade, when the feed has it. */
export interface TradePrint {
  price: number;
  qty: number;
  bid?: number;
  ask?: number;
}

/**
 * `'tickRule'` decides by the move from the previous print: up is a buy, down a
 * sell, and an unchanged price keeps the previous side. `'quote'` first tests the
 * recorded quote, a print at or above the ask being a buy and at or below the
 * bid a sell, and falls back to the tick rule inside the spread or when the
 * quote is missing or crossed.
 */
export type TradeClassification = 'tickRule' | 'quote';

/**
 * A stateful classifier: feed prints in time order and it returns the side each
 * one goes to, `'ask'` for buyer-initiated and `'bid'` for seller-initiated.
 * The first print of a fresh classifier is a buy, because a move up from no
 * previous price is the only reading the tick rule has. Make one classifier per
 * instrument, and a new one when the tape restarts.
 */
export function createTradeClassifier(mode: TradeClassification = 'tickRule'): (print: TradePrint) => 'bid' | 'ask' {
  if (mode !== 'tickRule' && mode !== 'quote') throw new TypeError('Trade classification must be tickRule or quote');
  let last = 0;
  let lastSide: 'bid' | 'ask' = 'ask';
  return (print) => {
    if (!Number.isFinite(print.price)) throw new RangeError('Trade print price must be finite');
    const { price, bid, ask } = print;
    const quoted = mode === 'quote' && bid !== undefined && ask !== undefined && bid > 0 && ask >= bid;
    let side: 'bid' | 'ask';
    if (quoted && price >= ask) side = 'ask';
    else if (quoted && price <= bid) side = 'bid';
    else side = price > last ? 'ask' : price < last ? 'bid' : lastSide;
    last = price;
    lastSide = side;
    return side;
  };
}
