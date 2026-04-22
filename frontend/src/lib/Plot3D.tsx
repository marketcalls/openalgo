// React component bound to the 3D Plotly build. Used only by /volsurface.
import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from './plotly-3d'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Plot = createPlotlyComponent(Plotly as any)

export default Plot
