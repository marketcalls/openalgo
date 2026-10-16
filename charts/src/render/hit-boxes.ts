/**
 * The hit-box prefilter a pane runs before asking its primitives to hit-test
 * (`IPrimitive.hitBounds`, `Pane.hitTestPrimitives`).
 *
 * A pointer move used to ask every primitive on the pane, and a pane can carry
 * hundreds: order lines, alerts, a host's annotations. A primitive that
 * declares a box is asked only when the point is inside it, and the boxes are
 * measured once and kept while nothing they depend on has changed, so a hover
 * over a still chart measures once rather than on every move.
 *
 * "Nothing has changed" is a key the pane reads afresh on every hit test:
 * the numbers and references a primitive's render context maps with, and two
 * counts standing for everything else. Any difference from the last reading
 * lets every kept box go.
 *
 * The pane reads it again after each frame it paints. A box measured while
 * the key differed from the last painted one was measured between a change
 * and the frame that shows it; a primitive that answers from what it last
 * drew has a box of the old frame then, so such boxes go at the next paint.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext } from '../primitives/primitive';
import { PRICE_SCALE_MODES, type PriceScale } from '../scale/price-scale';

/** A primitive's hit box: media px relative to the plot, edges inclusive. */
interface HitBox {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** The box of a primitive that says nothing of it can be hit: no point is inside. */
const NO_HIT_BOX: HitBox = { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity };

/** The box of a primitive that declares none: every point is inside, so it is always asked. */
const EVERYWHERE: HitBox = { left: -Infinity, top: -Infinity, right: Infinity, bottom: Infinity };

/**
 * Bumped whenever a primitive that declares a hit box requests an update, on
 * any pane of any chart. A pane's kept boxes describe its primitives' state,
 * so none may outlive a change a primitive has announced. One count for all
 * panes keeps a primitive moved to another pane announcing to the right one,
 * at the price of the other panes measuring again.
 */
let primitiveEpoch = 0;

/** The host a bounded primitive is attached with: the chart's, which also retires kept boxes. */
export function announcingHost(host: PrimitiveHost): PrimitiveHost {
  return { requestUpdate: (): void => { primitiveEpoch++; host.requestUpdate(); } };
}

/**
 * The kept boxes and the key they were measured against. Boxes are kept by the
 * primitive's place in the pane's walk: that order only changes through calls
 * that also change the key, so the place names the same primitive for as long
 * as the boxes are kept, and a pointer move reads each one without a lookup.
 */
interface HitBoxes {
  /** Start reading the key. The primitives' own announcements are always part of it. */
  begin(): void;
  number(value: number): void;
  /** A reference compared by identity: a scale, a theme, a hover id. */
  ref(value: unknown): void;
  /**
   * A price scale's mapping. It is linear in the scale's own transformed space
   * (price, log price or percent), so its value at two prices, with its mode,
   * pins all of it: range, height, inversion and rebasing alike.
   */
  scale(scale: PriceScale): void;
  /** Finish reading the key: anything read differently lets every kept box go. */
  end(): void;
  /**
   * The key just read is what the pane has painted. Boxes measured since the
   * last paint against a key it had not painted go now.
   */
  painted(): void;
  /** The kept box of the primitive at `index` in the walk, or undefined before it is measured. */
  kept(index: number): HitBox | undefined;
  /** Measure and keep the box of the primitive at `index`, asked with its render context. */
  measure(index: number, primitive: IPrimitive, context: PrimitiveRenderContext): HitBox;
  clear(): void;
}

/** A closure, like the pane's other per-frame helpers, so its state minifies to letters. */
export function createHitBoxes(): HitBoxes {
  const boxes: HitBox[] = [];
  const key: number[] = [];
  const refs: unknown[] = [];
  const paintedKey: number[] = [];
  const paintedRefs: unknown[] = [];
  let at = 0, refAt = 0, moved = false;
  /** The key read last is the one painted last. */
  let clean = false;
  /** Some kept box was measured while the key was not the painted one. */
  let provisional = false;
  const same = (a: readonly unknown[], b: readonly unknown[]): boolean => a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const number = (value: number): void => {
    const i = at++;
    // `Object.is`, so a NaN that stays NaN reads as unchanged.
    if (!Object.is(key[i], value)) { key[i] = value; moved = true; }
  };
  return {
    begin(): void {
      at = 0;
      refAt = 0;
      moved = false;
      number(primitiveEpoch);
    },
    number,
    ref(value: unknown): void {
      const i = refAt++;
      if (i < refs.length && Object.is(refs[i], value)) return;
      refs[i] = value;
      moved = true;
    },
    scale(scale: PriceScale): void {
      number(scale.priceToY(1));
      number(scale.priceToY(1000));
      number(scale.height);
      number(PRICE_SCALE_MODES.indexOf(scale.options.mode));
      number(scale.options.inverted ? 1 : 0);
    },
    end(): void {
      if (at !== key.length) { key.length = at; moved = true; }
      if (refAt !== refs.length) { refs.length = refAt; moved = true; }
      if (moved) { boxes.length = 0; provisional = false; clean = same(key, paintedKey) && same(refs, paintedRefs); }
    },
    painted(): void {
      if (provisional) { boxes.length = 0; provisional = false; }
      paintedKey.length = 0;
      paintedKey.push(...key);
      paintedRefs.length = 0;
      paintedRefs.push(...refs);
      clean = true;
    },
    kept: (index: number): HitBox | undefined => boxes[index],
    measure(index: number, primitive: IPrimitive, context: PrimitiveRenderContext): HitBox {
      const box = primitive.hitBounds === undefined ? EVERYWHERE : primitive.hitBounds(context) ?? NO_HIT_BOX;
      // Places before this one that were never measured (skipped by `except`,
      // or without `hitTest`) stay holes, which read as unmeasured.
      boxes[index] = box;
      if (!clean) provisional = true;
      return box;
    },
    clear(): void {
      boxes.length = 0;
    },
  };
}

/**
 * Whether (x, y) can be in `box`. Written as "not outside", so a box with a
 * NaN edge, which answers no comparison, is asked rather than skipped.
 */
export function inHitBox(box: HitBox, x: number, y: number): boolean {
  return !(x < box.left || x > box.right || y < box.top || y > box.bottom);
}
