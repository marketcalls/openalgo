// Custom Plotly 2D build — registers only the trace types the 2D tools
// actually use (scatter, bar, candlestick). Scatter covers line, marker,
// and area fills; `type: 'line'` in code is treated as scatter by Plotly.
// Ships a much smaller chunk than the full plotly.js-dist-min bundle.
// 3D surface plots are in a separate module (`plotly-3d.ts`) so VolSurface
// is the only page that pays the WebGL / gl3d cost.
import Plotly from 'plotly.js/lib/core'
import scatter from 'plotly.js/lib/scatter'
import bar from 'plotly.js/lib/bar'
import candlestick from 'plotly.js/lib/candlestick'

Plotly.register([scatter, bar, candlestick])

export default Plotly
