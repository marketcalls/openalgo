/** The host owns grouping; names and glyphs come from the pinned chart package. */
import type { ReactNode } from 'react'
import { RAIL_TOOL_PATHS } from './chromeIcons'
import { DRAW_TOOL_METADATA } from './drawingToolMetadata'
import { toolGlyph } from './glyphs'

export interface DrawToolDef {
  id: string | null
  label: string
  iconKey: string
}

export interface DrawGroupDef {
  key: string
  label: string
  iconKey: string
  sections: { head?: string; tools: DrawToolDef[] }[]
}

function tools(...ids: string[]): DrawToolDef[] {
  return ids.map((id) => ({ id, label: DRAW_TOOL_METADATA[id].name, iconKey: id }))
}

export const DRAW_GROUPS: DrawGroupDef[] = [
  {
    key: 'lines',
    label: 'Lines',
    iconKey: 'trend-line',
    sections: [
      {
        head: 'Lines',
        tools: tools('trend-line', 'ray', 'extended-line', 'arrow', 'info-line', 'trend-angle'),
      },
      {
        head: 'Horizontal and vertical',
        tools: tools('horizontal-line', 'horizontal-ray', 'vertical-line', 'cross-line'),
      },
    ],
  },
  {
    key: 'channels',
    label: 'Channels',
    iconKey: 'parallel-channel',
    sections: [
      {
        head: 'Channels',
        tools: tools(
          'parallel-channel',
          'fib-channel',
          'disjoint-channel',
          'flat-top-bottom',
          'regression-channel'
        ),
      },
      {
        head: 'Pitchforks',
        tools: tools(
          'pitchfork',
          'schiff-pitchfork',
          'modified-schiff-pitchfork',
          'inside-pitchfork'
        ),
      },
    ],
  },
  {
    key: 'fib',
    label: 'Fibonacci & Gann',
    iconKey: 'fib-retracement',
    sections: [
      {
        head: 'Fibonacci',
        tools: tools(
          'fib-retracement',
          'fib-extension',
          'fib-time-zone',
          'fib-fan',
          'fib-extension-two-point',
          'fib-speed-resistance-fan',
          'trend-fib-time',
          'fib-circles',
          'fib-speed-resistance-arcs',
          'fib-wedge',
          'fib-spiral'
        ),
      },
      {
        head: 'Gann',
        tools: tools('gann-fan', 'gann-box', 'gann-square'),
      },
    ],
  },
  {
    key: 'shapes',
    label: 'Shapes',
    iconKey: 'rectangle',
    sections: [
      {
        head: 'Shapes',
        tools: tools('rectangle', 'rotated-rectangle', 'ellipse', 'circle', 'triangle'),
      },
      {
        head: 'Paths',
        tools: tools('path', 'polyline', 'arc', 'curve', 'double-curve'),
      },
    ],
  },
  {
    key: 'cycles',
    label: 'Cycles',
    iconKey: 'sine-line',
    sections: [
      {
        tools: tools('cyclic-lines', 'time-cycles', 'sine-line'),
      },
    ],
  },
  {
    key: 'patterns',
    label: 'Patterns',
    iconKey: 'xabcd-pattern',
    sections: [
      {
        head: 'Patterns and waves',
        tools: tools(
          'xabcd-pattern',
          'abcd-pattern',
          'head-shoulders',
          'elliott-impulse',
          'elliott-correction'
        ),
      },
      {
        head: 'Harmonic patterns',
        tools: tools('gartley', 'bat', 'butterfly', 'crab', 'shark', 'cypher'),
      },
    ],
  },
  {
    key: 'geometry',
    label: 'Geometric studies',
    iconKey: 'dedekind-tessellation',
    sections: [
      {
        tools: tools(
          'dedekind-tessellation',
          'sonic',
          'supersonic',
          'golden-sonic',
          'golden-supersonic'
        ),
      },
    ],
  },
  {
    key: 'positions',
    label: 'Forecasting',
    iconKey: 'long-position',
    sections: [
      {
        tools: tools('long-position', 'short-position', 'forecast'),
      },
    ],
  },
  {
    key: 'volume',
    label: 'Volume studies',
    iconKey: 'fixed-range-volume-profile',
    sections: [
      {
        tools: tools('anchored-vwap', 'fixed-range-volume-profile'),
      },
    ],
  },
  {
    key: 'measure',
    label: 'Measurers',
    iconKey: 'measure',
    sections: [
      {
        tools: tools('price-range', 'date-range', 'measure'),
      },
    ],
  },
  {
    key: 'marks',
    label: 'Arrows & notes',
    iconKey: 'text',
    sections: [
      {
        head: 'Text and notes',
        tools: tools(
          'text',
          'price-label',
          'callout',
          'note',
          'balloon',
          'comment',
          'price-note',
          'signpost',
          'table'
        ),
      },
      {
        head: 'Marks',
        tools: tools('flag-mark', 'icon-stamp'),
      },
      {
        head: 'Arrows',
        tools: tools('arrow-up', 'arrow-down', 'arrow-left', 'arrow-right'),
      },
      {
        head: 'Brushes',
        tools: tools('brush', 'highlighter'),
      },
    ],
  },
]

/**
 * Render public path data as React elements, keeping SVG attributes consistent.
 *
 * `size` is the box the glyph is shown in, so the stroke can keep the engine's
 * line at any size: the rail shows tools at the 20px they are drawn for, a
 * menu row at 16px. The cursor and magnet are the engine's rail glyphs, on the
 * same grid as the tools rather than hand-drawn beside them.
 */
export function drawToolIcon(iconKey: string, size?: number, className?: string): ReactNode {
  const path = DRAW_TOOL_METADATA[iconKey]?.path ?? RAIL_TOOL_PATHS[iconKey]
  return path ? toolGlyph(path, iconKey, size, className) : null
}
