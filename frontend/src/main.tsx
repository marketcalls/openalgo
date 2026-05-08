import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { clearChunkReloadFlag } from '@/utils/chunkReload'
import { installGlobalErrorReporter } from '@/utils/errorReporter'
import App from './App.tsx'

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
