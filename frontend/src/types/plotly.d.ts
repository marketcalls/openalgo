declare module 'react-plotly.js' {
  import type { Component } from 'react'
  import type * as Plotly from 'plotly.js'

  interface PlotParams {
    data: Plotly.Data[]
    layout?: Partial<Plotly.Layout>
    config?: Partial<Plotly.Config>
    style?: React.CSSProperties
    className?: string
    useResizeHandler?: boolean
    onInitialized?: (
      figure: { data: Plotly.Data[]; layout: Partial<Plotly.Layout> },
      graphDiv: HTMLElement
    ) => void
    onUpdate?: (
      figure: { data: Plotly.Data[]; layout: Partial<Plotly.Layout> },
      graphDiv: HTMLElement
    ) => void
    onRelayout?: (event: Plotly.PlotRelayoutEvent) => void
    onClick?: (event: Plotly.PlotMouseEvent) => void
    onHover?: (event: Plotly.PlotMouseEvent) => void
    revision?: number
  }

  class Plot extends Component<PlotParams> {}
  export default Plot
}

declare module 'plotly.js-dist-min' {
  import * as Plotly from 'plotly.js'
  export = Plotly
}
