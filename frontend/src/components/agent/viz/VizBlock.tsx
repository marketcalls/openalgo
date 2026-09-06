/**
 * The one place a visualization's `kind` chooses a renderer.
 *
 * Three engines draw for the agent and every one of them already ships in this
 * app, so nothing here is a fourth charting stack:
 *
 * | kind | engine | already used by |
 * | --- | --- | --- |
 * | `candles` | `openalgo-charts` | the `/trading` terminal |
 * | `plotly` | `Plot2D` / `Plot3D` | `/strategybuilder` and the option pages |
 * | `openui` | OpenUI genui-lib | new here |
 * | `instrument` | `openalgo-charts`, through `CandleViz` | as above |
 * | `live_quotes` | the shared market data feed | the trading surfaces |
 * | `live_combo` | the shared market data feed | as above |
 *
 * `instrument` is a composed card rather than a fourth engine: it draws its
 * chart by mounting `CandleViz` in its inline variant, so the number of things
 * in this app that drive a charting library is unchanged by it. The two live
 * kinds are the same idea applied to the feed: they subscribe through
 * `useMarketData`, which is the one shared `MarketDataManager` connection the
 * whole application already streams on. Neither is a second WebSocket client
 * and neither is a second poller.
 *
 * **An unknown kind renders nothing, and says nothing.** A backend that learns
 * a fourth kind must be able to ship before every browser has the client that
 * draws it, and the failure a user should see for that is a chart that is not
 * there, not an error where the answer should be. The same rule covers a
 * payload a renderer cannot read: each renderer parses its own spec and
 * reports its own "nothing to draw", so there is exactly one parser per kind
 * and no second copy here to drift from it.
 *
 * Adding a renderer is a `kind` and a branch. That is the whole contract.
 */

import { lazy, Suspense } from 'react'
import type { AgentVizItem } from '@/lib/agent/viz'
import { OPENUI_VIZ, openUiMarkup } from '@/lib/agent/viz'
import { CandleViz } from './CandleViz'
import { InstrumentCard } from './InstrumentCard'
import { LiveComboCard } from './LiveComboCard'
import { LiveQuotesCard } from './LiveQuotesCard'
import { PayoffCard } from './PayoffCard'
import { PlotlyViz } from './PlotlyViz'

/**
 * The OpenUI runtime, fetched only once a turn actually composes markup.
 *
 * It is by far the heaviest of the three: the component library, its
 * stylesheet and Recharts together are about 1.6MB of the agent page's bundle,
 * and most conversations never render a single block. Imported statically it
 * would be downloaded before the first message could be typed.
 *
 * `CandleViz` and `PlotlyViz` reach the same result their own way, by importing
 * their engines inside an effect, so no chart engine is in the page's first
 * load either. This one cannot: the library object is needed to render, not
 * after it.
 *
 * The fallback is deliberately empty. A spinner where a figure is about to
 * appear reads as a slower answer, and the chunk is served from the same origin
 * as the page that asked for it.
 */
const OpenUiViz = lazy(async () => ({ default: (await import('./OpenUiViz')).OpenUiViz }))

export interface VizBlockProps {
  /**
   * The item, straight from `AgentMessage.viz`.
   *
   * Pass the stored object rather than a fresh literal: `spec` identity is
   * what decides whether a chart is rebuilt, so a new object per render would
   * tear the chart down and build it again on every streamed token.
   */
  item: AgentVizItem
  /**
   * True while the turn is still streaming into this message. Only the OpenUI
   * block cares: a `viz` frame arrives complete, while OpenUI markup is
   * written a piece at a time and the renderer holds back the unresolved tail.
   */
  streaming?: boolean
  /** Extra classes on the block, for a host that needs to adjust margins. */
  className?: string
}

/**
 * Draw one visualization, or nothing.
 *
 * @param item - The visualization to draw.
 * @param streaming - Whether the turn is still writing into it.
 * @param className - Extra classes on the block.
 */
export function VizBlock({ item, streaming, className }: VizBlockProps) {
  switch (item.kind) {
    case 'candles':
      return (
        <CandleViz spec={item.spec} title={item.title} source={item.source} className={className} />
      )
    case 'plotly':
      return (
        <PlotlyViz spec={item.spec} title={item.title} source={item.source} className={className} />
      )
    case 'instrument':
      return (
        <InstrumentCard
          spec={item.spec}
          title={item.title}
          source={item.source}
          className={className}
        />
      )
    case 'live_quotes':
      return (
        <LiveQuotesCard
          spec={item.spec}
          title={item.title}
          source={item.source}
          className={className}
        />
      )
    case 'live_combo':
      return (
        <LiveComboCard
          spec={item.spec}
          title={item.title}
          source={item.source}
          className={className}
        />
      )
    case 'payoff':
      // The card computes the curve with strategyMath and draws it with the
      // /strategybuilder chart, so nothing about the payoff lives here.
      return <PayoffCard spec={item.spec} title={item.title} />
    case OPENUI_VIZ:
      return (
        <Suspense fallback={null}>
          <OpenUiViz markup={openUiMarkup(item.spec)} streaming={streaming} className={className} />
        </Suspense>
      )
    default:
      return null
  }
}
