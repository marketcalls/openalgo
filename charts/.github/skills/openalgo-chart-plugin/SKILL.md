---
name: openalgo-chart-plugin
description: Extend openalgo-charts with a custom primitive, drawing tool, chart type, or indicator descriptor. Use when the user wants a custom overlay, annotation, band, zone, marker layer, hand-drawn tool, or a series style the library does not ship.
argument-hint: "[what-to-build]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Extend the engine. Everything extensible in this library is a registry entry or a primitive - there is no plugin loader and no core file to edit.

## Step 1 - pick the extension point

Answer these in order and stop at the first yes.

| Question | Build |
|---|---|
| Does it need its own data, autoscale and price-scale identity? | a **chart type** via `registerChartType` |
| Is it a shape the user places with clicks and drags later? | a **drawing tool** via `registerDrawingTool` |
| Is it a number computed per bar that should get a pane, legend row and settings? | an **indicator** via `registerIndicator` |
| Anything else that draws - band, zone, label, watermark, custom axis marker | a **primitive** via `IPrimitive` |

**Default to a primitive.** It is the cheapest and most flexible. Reach past it only when the table above says to.

## Step 2 - read the contract before writing

- Primitive and custom chart type: [primitives-and-plugins](../openalgo-charts/references/primitives-and-plugins.md)
- Drawing tool: [drawing-tools](../openalgo-charts/references/drawing-tools.md)
- Indicator descriptor: [indicators](../openalgo-charts/references/indicators.md)

Confirm the interface shape against local typings before writing an implementation:

```sh
rg -n "interface IPrimitive|interface RendererEntry|interface DrawingTool|interface IndicatorDescriptor" \
  node_modules/openalgo-charts/dist/index.d.ts node_modules/openalgo-charts/dist/draw/index.d.ts
```

## Step 3 - the rules that make it correct

1. **Draw in bitmap pixels.** The canvas context is scaled to the device. Multiply every media-px value by `ctx.dpr` before you draw, or the result blurs and drifts on HiDPI displays. This is the single most common mistake.
2. **Anchor in data space, not pixels.** Store `{ time, price }` and convert at draw time. The time axis is gapless, so a pixel anchor slides the moment a session gap collapses or the user zooms.
3. **Pick the right z-order.** `'bottom'` draws behind the series, `'normal'` over it on the base canvas, `'top'` on the overlay canvas which repaints on cursor moves. Anything that follows the pointer belongs on `'top'`; anything static does not, or you will repaint it on every mouse move.
4. **`autoscaleInfo` runs every layout pass.** Return a cheap precomputed extent; do not scan your data there.
5. **Give hit-testable primitives a stable `externalId`.** Clicks and drags route back to you through it.
6. **Clean up in `detached`.** Timers, subscriptions, cached bitmaps.
7. **Register into the package entry, never a deep path.** A deep import creates a second registry Map and your registration becomes invisible to `createChart`. See [bundling-and-tiers](../openalgo-charts/references/bundling-and-tiers.md).
8. **Register before use.** For a chart type, before the `addSeries` call that names it.
9. No emojis or icons in drawn text or logs.

## Step 4 - minimum viable primitive

```ts
import type { IPrimitive, PrimitiveRenderContext } from 'openalgo-charts';

class Band implements IPrimitive {
  constructor(private lo: number, private hi: number) {}
  zOrder() { return 'bottom' as const; }
  draw(g: CanvasRenderingContext2D, ctx: PrimitiveRenderContext) {
    const dpr = ctx.dpr;
    const y1 = ctx.priceScale.priceToY(this.hi) * dpr;
    const y2 = ctx.priceScale.priceToY(this.lo) * dpr;
    g.fillStyle = 'rgba(80,140,255,0.12)';
    g.fillRect(0, y1, ctx.plotWidth * dpr, y2 - y1);
  }
  autoscaleInfo() { return { min: this.lo, max: this.hi }; }
}

chart.addPrimitive(new Band(99, 101), 0);
```

Confirm every member name against the typings before shipping this shape - the reference file documents the interface, but `dist/index.d.ts` is authoritative.

## Step 5 - test it

The repo's own tests are the pattern to copy. Look at `tests/primitives.test.ts`, `tests/draw-tier.test.ts` and `tests/chart-types.test.ts` for how a canvas-free unit test asserts draw calls and hit-testing. A plugin with no test is not done.

```sh
npx vitest run
npx tsc --noEmit
```

Report the extension point you chose and why, the file you created, and the test that covers it.
