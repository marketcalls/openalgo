// React component bound to the 3D Plotly build. Used only by /volsurface.
import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from './plotly-3d'

// react-plotly.js/factory is an untyped CommonJS module. Vite 8's CJS->ESM
// interop can deliver the default export wrapped as `{ default: factory }`, so
// unwrap defensively before calling — otherwise this throws
// "(0 , be.default) is not a function" at runtime on /volsurface.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const factory = createPlotlyComponent as any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Plot = (factory.default ?? factory)(Plotly as any)

export default Plot
