// Plotly 3D build — adds only the `surface` trace, used exclusively by
// /volsurface. Kept as its own module so 2D tools don't bundle the gl3d
// WebGL engine. Vite / Rollup dedupes `plotly.js/lib/core` into a shared
// vendor chunk between this file and plotly-2d.ts.
import Plotly from 'plotly.js/lib/core'
import surface from 'plotly.js/lib/surface'

Plotly.register([surface])

export default Plotly
