/** The host owns grouping; names and glyphs come from the pinned chart package. */
import type { ReactNode } from 'react'
import { DRAW_TOOL_ICON_ATTRS, DRAW_TOOL_METADATA } from './drawingToolMetadata'

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

/** Render public path data as React elements, keeping SVG attributes consistent. */
export function drawToolIcon(iconKey: string): ReactNode {
  const metadata = DRAW_TOOL_METADATA[iconKey]
  if (metadata) {
    return (
      <svg {...DRAW_TOOL_ICON_ATTRS} strokeWidth={1.5} aria-hidden="true">
        <path d={metadata.path} />
      </svg>
    )
  }
  const s = {
    fill: 'none' as const,
    stroke: 'currentColor',
    strokeWidth: 1.5,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
  switch (iconKey) {
    case 'cursor':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M12 3v5M12 16v5M3 12h5M16 12h5" />
          <circle cx="12" cy="12" r="1.2" />
        </svg>
      )
    case 'lock':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <rect x="5" y="10.5" width="14" height="9" rx="2" />
          <path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3" />
        </svg>
      )
    case 'magnet':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M6 4v6a4 4 0 0 0 8 0V4" />
          <path d="M6 4h3v6M11 4h3v6" />
        </svg>
      )
    default:
      return null
  }
}
