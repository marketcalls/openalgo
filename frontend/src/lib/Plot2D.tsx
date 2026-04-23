// React component bound to the 2D Plotly build. Drop-in replacement for
// `import Plot from 'react-plotly.js'` in any page that only uses scatter,
// bar, or candlestick traces.
import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from './plotly-2d'

// react-plotly.js/factory is untyped; cast to the generic Plotly surface
// so the returned component still accepts the same PlotParams.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Plot = createPlotlyComponent(Plotly as any)

export default Plot
