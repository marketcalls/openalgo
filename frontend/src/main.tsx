import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { clearChunkReloadFlag } from '@/utils/chunkReload'
import { installApiBasePath } from '@/utils/apiBasePath'
import { installGlobalErrorReporter } from '@/utils/errorReporter'
import App from './App.tsx'

// Must run before anything fetches: rewrites absolute API paths to include the
// sub-path base (e.g. /portfolio/openalgo) so login and all API calls work.
installApiBasePath()

installGlobalErrorReporter()

// We mounted successfully — the bundle is fresh. Clear the
// stale-chunk reload-attempt flag so a *future* stale-chunk navigation
// later in this tab session can auto-recover too. See #1393.
clearChunkReloadFlag()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>
)
