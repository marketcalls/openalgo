/**
 * Drawing-tool catalogue for the trading terminal's rail.
 *
 * A group is one rail button that opens a flyout of its tools — the pattern
 * the openalgo-charts examples follow. Tool ids are the
 * openalgo-charts `draw` tier's registered ids; nothing here knows how a tool
 * behaves, only what to call it and which glyph to show.
 */
import type { ReactNode } from 'react'

const s = {
  fill: 'none' as const,
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

export interface DrawToolDef {
  /** Registered tool id, or null for the cursor (disarm). */
  id: string | null
  label: string
  iconKey: string
}

export interface DrawGroupDef {
  /** Group key — also the persisted "last tool used in this group". */
  key: string
  label: string
  iconKey: string
  /** Section headers keep a 10-item flyout readable. */
  sections: { head?: string; tools: DrawToolDef[] }[]
}

export const DRAW_GROUPS: DrawGroupDef[] = [
  {
    key: 'lines',
    label: 'Lines',
    iconKey: 'trend',
    sections: [
      {
        head: 'Lines',
        tools: [
          { id: 'trend-line', label: 'Trend line', iconKey: 'trend' },
          { id: 'ray', label: 'Ray', iconKey: 'ray' },
          { id: 'extended-line', label: 'Extended line', iconKey: 'extended' },
          { id: 'arrow', label: 'Arrow', iconKey: 'arrow' },
        ],
      },
      {
        head: 'Horizontal & vertical',
        tools: [
          { id: 'horizontal-line', label: 'Horizontal line', iconKey: 'hline' },
          { id: 'horizontal-ray', label: 'Horizontal ray', iconKey: 'hray' },
          { id: 'vertical-line', label: 'Vertical line', iconKey: 'vline' },
          { id: 'cross-line', label: 'Cross line', iconKey: 'cross' },
        ],
      },
    ],
  },
  {
    key: 'channels',
    label: 'Channels',
    iconKey: 'channel',
    sections: [
      {
        tools: [
          { id: 'parallel-channel', label: 'Parallel channel', iconKey: 'channel' },
          { id: 'fib-channel', label: 'Fib channel', iconKey: 'fibchannel' },
        ],
      },
    ],
  },
  {
    key: 'fib',
    label: 'Fibonacci & Gann',
    iconKey: 'fib',
    sections: [
      {
        head: 'Fibonacci',
        tools: [
          { id: 'fib-retracement', label: 'Fib retracement', iconKey: 'fib' },
          { id: 'fib-extension', label: 'Fib extension', iconKey: 'fib' },
          { id: 'fib-time-zone', label: 'Fib time zone', iconKey: 'fibtime' },
          { id: 'fib-fan', label: 'Fib speed fan', iconKey: 'fibfan' },
        ],
      },
      {
        head: 'Gann',
        tools: [
          { id: 'gann-fan', label: 'Gann fan', iconKey: 'fibfan' },
          { id: 'gann-box', label: 'Gann box', iconKey: 'rect' },
        ],
      },
    ],
  },
  {
    key: 'shapes',
    label: 'Shapes',
    iconKey: 'rect',
    sections: [
      {
        head: 'Shapes',
        tools: [
          { id: 'rectangle', label: 'Rectangle', iconKey: 'rect' },
          { id: 'rotated-rectangle', label: 'Rotated rectangle', iconKey: 'rotrect' },
          { id: 'ellipse', label: 'Ellipse', iconKey: 'ellipse' },
          { id: 'circle', label: 'Circle', iconKey: 'circle' },
          { id: 'triangle', label: 'Triangle', iconKey: 'triangle' },
        ],
      },
      {
        head: 'Paths',
        tools: [
          { id: 'path', label: 'Path', iconKey: 'path' },
          { id: 'polyline', label: 'Polyline', iconKey: 'polyline' },
          { id: 'arc', label: 'Arc', iconKey: 'arc' },
          { id: 'curve', label: 'Curve', iconKey: 'curve' },
          { id: 'double-curve', label: 'Double curve', iconKey: 'dcurve' },
        ],
      },
    ],
  },
  {
    key: 'cycles',
    label: 'Cycles',
    iconKey: 'sine',
    sections: [
      {
        tools: [
          { id: 'cyclic-lines', label: 'Cyclic lines', iconKey: 'cyclic' },
          { id: 'time-cycles', label: 'Time cycles', iconKey: 'timecycle' },
          { id: 'sine-line', label: 'Sine line', iconKey: 'sine' },
        ],
      },
    ],
  },
  {
    key: 'positions',
    label: 'Forecasting',
    iconKey: 'long',
    sections: [
      {
        tools: [
          { id: 'long-position', label: 'Long position', iconKey: 'long' },
          { id: 'short-position', label: 'Short position', iconKey: 'short' },
          { id: 'forecast', label: 'Forecast', iconKey: 'forecast' },
        ],
      },
    ],
  },
  {
    key: 'measure',
    label: 'Measurers',
    iconKey: 'measure',
    sections: [
      {
        tools: [
          { id: 'price-range', label: 'Price range', iconKey: 'pricerange' },
          { id: 'date-range', label: 'Date range', iconKey: 'daterange' },
          { id: 'measure', label: 'Date and price range', iconKey: 'measure' },
        ],
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
        tools: [
          { id: 'text', label: 'Text', iconKey: 'text' },
          { id: 'price-label', label: 'Price label', iconKey: 'pricelabel' },
          { id: 'callout', label: 'Callout', iconKey: 'callout' },
          { id: 'flag-mark', label: 'Flag mark', iconKey: 'flag' },
        ],
      },
      {
        head: 'Arrows',
        tools: [
          { id: 'arrow-up', label: 'Arrow mark up', iconKey: 'arrowup' },
          { id: 'arrow-down', label: 'Arrow mark down', iconKey: 'arrowdown' },
        ],
      },
      {
        head: 'Brushes',
        tools: [
          { id: 'brush', label: 'Brush', iconKey: 'brush' },
          { id: 'highlighter', label: 'Highlighter', iconKey: 'highlighter' },
        ],
      },
    ],
  },
]

/** Glyph for a rail button or flyout row. 24x24, stroked, matches the toolbar. */
export function drawToolIcon(iconKey: string): ReactNode {
  switch (iconKey) {
    case 'cursor':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M12 3v5M12 16v5M3 12h5M16 12h5" />
          <circle cx="12" cy="12" r="1.2" />
        </svg>
      )
    case 'trend':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4 18 20 6" />
          <circle cx="4" cy="18" r="1.8" />
          <circle cx="20" cy="6" r="1.8" />
        </svg>
      )
    case 'ray':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M5 17 21 5" />
          <circle cx="5" cy="17" r="1.8" />
        </svg>
      )
    case 'extended':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3 19 21 5" />
          <circle cx="9" cy="14.5" r="1.6" />
          <circle cx="15" cy="9.5" r="1.6" />
        </svg>
      )
    case 'arrow':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4 19 18 6M18 6h-5M18 6v5" />
        </svg>
      )
    case 'hline':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3 12h18" />
          <circle cx="12" cy="12" r="1.8" />
        </svg>
      )
    case 'hray':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M6 12h15" />
          <circle cx="6" cy="12" r="1.8" />
        </svg>
      )
    case 'vline':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M12 3v18" />
          <circle cx="12" cy="12" r="1.8" />
        </svg>
      )
    case 'cross':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3 12h18M12 3v18" />
        </svg>
      )
    case 'channel':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3 15 15 4M9 20 21 9" />
        </svg>
      )
    case 'fibchannel':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3 15 13 5M6 18 16 8M9 21 19 11" />
        </svg>
      )
    case 'fib':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4 6h16M4 11h16M4 16h16M4 20h16" />
        </svg>
      )
    case 'fibtime':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4 4v16M7 4v16M11 4v16M17 4v16" />
        </svg>
      )
    case 'fibfan':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4 20 20 4M4 20h16M4 20 20 12M4 20 20 17" />
        </svg>
      )
    case 'rect':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <rect x="4" y="6" width="16" height="12" rx="1.5" />
        </svg>
      )
    case 'rotrect':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M9.5 3.5 20.5 9l-6 11.5L3.5 15z" />
        </svg>
      )
    case 'ellipse':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <ellipse cx="12" cy="12" rx="9" ry="6" />
        </svg>
      )
    case 'circle':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <circle cx="12" cy="12" r="7.5" />
          <circle cx="12" cy="12" r="1.4" />
        </svg>
      )
    case 'triangle':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M12 4.5 20 19H4z" />
        </svg>
      )
    case 'path':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3.5 17 8 10l4.5 4L20 5M20 5h-4.5M20 5v4.5" />
        </svg>
      )
    case 'polyline':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3.5 16 8 9l4.5 4.5L20.5 5" />
          <circle cx="3.5" cy="16" r="1.5" />
          <circle cx="20.5" cy="5" r="1.5" />
        </svg>
      )
    case 'arc':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4 19a12 12 0 0 1 16-11" />
          <circle cx="4" cy="19" r="1.6" />
          <circle cx="20" cy="8" r="1.6" />
        </svg>
      )
    case 'curve':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4 18c4.5 0 5-11 9.5-11S20 13 20 13" />
        </svg>
      )
    case 'dcurve':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3.5 17c3.5 0 3-9 6.5-9s3 9 6.5 9 4-6 4-6" />
        </svg>
      )
    case 'cyclic':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M5 4v16M10 4v16M15 4v16M20 4v16" />
        </svg>
      )
    case 'timecycle':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3 17a3.5 3.5 0 0 1 7 0 3.5 3.5 0 0 1 7 0" />
          <path d="M17 17a3.5 3.5 0 0 1 4 0" />
        </svg>
      )
    case 'sine':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3 12c2.5-8 5-8 7.5 0s5 8 7.5 0" />
        </svg>
      )
    case 'long':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <rect x="3.5" y="5" width="17" height="6" rx="1.4" />
          <rect x="3.5" y="13" width="17" height="6" rx="1.4" />
          <path d="M12 13V5" />
        </svg>
      )
    case 'short':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <rect x="3.5" y="5" width="17" height="6" rx="1.4" />
          <rect x="3.5" y="13" width="17" height="6" rx="1.4" />
          <path d="M12 11v8" />
        </svg>
      )
    case 'forecast':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3 17c5 0 7-9 12-11" />
          <path d="M15 6h5v5" />
        </svg>
      )
    case 'measure':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M14.6 3 21 9.4 9.4 21 3 14.6z" />
          <path d="M12.2 5.4 14 7.2M9.6 8l1.8 1.8M7 10.6l1.8 1.8" />
        </svg>
      )
    case 'pricerange':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M12 4v16M12 4l-3 3M12 4l3 3M12 20l-3-3M12 20l3-3" />
        </svg>
      )
    case 'daterange':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4 12h16M4 12l3-3M4 12l3 3M20 12l-3-3M20 12l-3 3" />
        </svg>
      )
    case 'text':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M5 5.5h14M12 5.5V19" />
        </svg>
      )
    case 'pricelabel':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <rect x="10" y="4.5" width="10.5" height="7" rx="2" />
          <path d="M10 8 4 15.5" />
          <circle cx="4" cy="15.5" r="1.6" />
        </svg>
      )
    case 'callout':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <rect x="3.5" y="4.5" width="17" height="10" rx="2.5" />
          <path d="M8 14.5 6.5 20l5-5.5" />
        </svg>
      )
    case 'flag':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M6 20.5V4" />
          <path d="M6 4.5h11l-2.5 3.5L17 11.5H6z" />
        </svg>
      )
    case 'arrowup':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M12 4.5 6.5 11h3.5v8.5h4V11h3.5z" />
        </svg>
      )
    case 'arrowdown':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M12 19.5 6.5 13h3.5V4.5h4V13h3.5z" />
        </svg>
      )
    case 'brush':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4 19.5c3-1 3.5-3.5 5-3.5" />
          <path d="M9 16 17 6.5a2.2 2.2 0 0 1 3.2 3L11 19" />
        </svg>
      )
    case 'highlighter':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M4.5 19.5h6" />
          <path d="M7 16.5 15.5 8l3 3-8.5 8.5H7z" />
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
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <circle cx="12" cy="12" r="7" />
        </svg>
      )
  }
}
