# Developer Guide

This guide covers everything you need to know to develop the OpenAlgo frontend.

## Prerequisites

- Node.js 20.19+ or 22.12+
- npm 10+
- Git

## Getting Started

### 1. Clone and Install

```bash
cd openalgo/frontend
npm install
```

### 2. Start Development Server

```bash
npm run dev
```

The app runs at `http://localhost:5173` with hot module replacement (HMR).

### 3. Backend Proxy

The Vite dev server proxies API requests to the Flask backend:

| Path | Target |
|------|--------|
| `/api/*` | `http://localhost:5000` |
| `/auth/*` | `http://localhost:5000` |
| `/socket.io/*` | `http://localhost:5000` (WebSocket) |

Ensure the Flask backend is running on port 5000.

## Project Structure

```
frontend/
├── docs/                 # Documentation
├── e2e/                  # Playwright E2E tests
├── public/               # Static assets
├── src/
│   ├── api/              # API client modules
│   │   ├── auth.ts       # Authentication API
│   │   ├── broker.ts     # Broker operations
│   │   ├── chartink.ts   # Chartink strategies
│   │   ├── orders.ts     # Order management
│   │   ├── strategy.ts   # Webhook strategies
│   │   └── ...
│   ├── app/
│   │   └── providers.tsx # App-wide providers
│   ├── components/
│   │   ├── auth/         # Auth components
│   │   ├── layout/       # Layout components
│   │   │   ├── Layout.tsx
│   │   │   ├── Navbar.tsx
│   │   │   ├── Footer.tsx
│   │   │   └── MobileBottomNav.tsx
│   │   └── ui/           # shadcn/ui components
│   ├── config/
│   │   └── navigation.ts # Navigation configuration
│   ├── hooks/            # Custom hooks
│   ├── lib/
│   │   └── utils.ts      # Utility functions
│   ├── pages/            # Page components
│   │   ├── admin/        # Admin pages
│   │   ├── chartink/     # Chartink pages
│   │   ├── monitoring/   # Monitoring pages
│   │   ├── python-strategy/
│   │   ├── strategy/     # Strategy pages
│   │   ├── telegram/     # Telegram pages
│   │   └── ...
│   ├── stores/           # Zustand stores
│   │   ├── authStore.ts
│   │   └── themeStore.ts
│   ├── test/             # Test utilities
│   ├── types/            # TypeScript types
│   ├── App.tsx           # Root component
│   ├── index.css         # Global styles
│   └── main.tsx          # Entry point
├── index.html
├── package.json
├── playwright.config.ts
├── tsconfig.json
├── vite.config.ts
└── vitest.config.ts
```

## NPM Scripts

| Script | Description |
|--------|-------------|
| `npm run dev` | Start development server |
| `npm run build` | Build for production |
| `npm run preview` | Preview production build |
| `npm run lint` | Run Biome linter |
| `npm run format` | Format code with Biome |
| `npm run check` | Lint and format |
| `npm run test` | Run unit tests (watch mode) |
| `npm run test:run` | Run unit tests once |
| `npm run test:coverage` | Run tests with coverage |
| `npm run e2e` | Run E2E tests |
| `npm run e2e:ui` | Run E2E tests with UI |

## Code Conventions

### File Naming

- **Components**: PascalCase (`Button.tsx`, `MobileBottomNav.tsx`)
- **Utilities**: camelCase (`utils.ts`, `authStore.ts`)
- **Types**: PascalCase for types, camelCase for files (`types/chartink.ts`)
- **Tests**: Same name with `.test.tsx` suffix (`button.test.tsx`)

### Component Structure

```tsx
// 1. Imports (external, then internal)
import { useState } from 'react'
import { Button } from '@/components/ui/button'

// 2. Types/Interfaces
interface MyComponentProps {
  title: string
  onAction: () => void
}

// 3. Component
export function MyComponent({ title, onAction }: MyComponentProps) {
  // State
  const [isOpen, setIsOpen] = useState(false)

  // Handlers
  const handleClick = () => {
    setIsOpen(true)
    onAction()
  }

  // Render
  return (
    <div>
      <h1>{title}</h1>
      <Button onClick={handleClick}>Click me</Button>
    </div>
  )
}
```

### Import Aliases

Use `@/` alias for src imports:

```tsx
// Good
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/authStore'

// Avoid
import { Button } from '../../../components/ui/button'
```

### Styling

Use Tailwind CSS utility classes:

```tsx
// Good - Tailwind utilities
<div className="flex items-center gap-4 p-4 bg-background">

// Avoid - inline styles
<div style={{ display: 'flex', alignItems: 'center' }}>
```

Use `cn()` helper for conditional classes:

```tsx
import { cn } from '@/lib/utils'

<button className={cn(
  'px-4 py-2 rounded-md',
  isActive && 'bg-primary text-primary-foreground',
  isDisabled && 'opacity-50 cursor-not-allowed'
)}>
```

### State Management

Use Zustand for global state:

```tsx
// stores/myStore.ts
import { create } from 'zustand'

interface MyStore {
  count: number
  increment: () => void
}

export const useMyStore = create<MyStore>((set) => ({
  count: 0,
  increment: () => set((state) => ({ count: state.count + 1 })),
}))

// Usage in component
const { count, increment } = useMyStore()
```

Use TanStack Query for server state:

```tsx
import { useQuery } from '@tanstack/react-query'

const { data, isLoading, error } = useQuery({
  queryKey: ['orders'],
  queryFn: () => ordersApi.getOrders(),
})
```

## Adding New Features

### 1. Add a New Page

```tsx
// src/pages/MyNewPage.tsx
export default function MyNewPage() {
  return (
    <div className="container mx-auto py-6">
      <h1>My New Page</h1>
    </div>
  )
}
```

```tsx
// src/App.tsx - Add lazy import
const MyNewPage = lazy(() => import('@/pages/MyNewPage'))

// Add route
<Route path="/my-new-page" element={<MyNewPage />} />
```

### 2. Add a New API Module

```tsx
// src/api/myApi.ts
export const myApi = {
  async getData(): Promise<MyData[]> {
    const response = await fetch('/api/v1/my-endpoint', {
      credentials: 'include',
    })
    if (!response.ok) throw new Error('Failed to fetch')
    return response.json()
  },

  async createItem(data: CreateItemData): Promise<MyData> {
    const response = await fetch('/api/v1/my-endpoint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    })
    if (!response.ok) throw new Error('Failed to create')
    return response.json()
  },
}
```

### 3. Add a New UI Component

```tsx
// src/components/ui/my-component.tsx
import { cn } from '@/lib/utils'

interface MyComponentProps {
  className?: string
  children: React.ReactNode
}

export function MyComponent({ className, children }: MyComponentProps) {
  return (
    <div className={cn('base-classes', className)}>
      {children}
    </div>
  )
}
```

## Environment Variables

Vite exposes env vars prefixed with `VITE_`:

```env
# .env.local
VITE_API_URL=http://localhost:5000
VITE_FEATURE_FLAG=true
```

```tsx
// Access in code
const apiUrl = import.meta.env.VITE_API_URL
```

## Build & Deployment

### Production Build

```bash
npm run build
```

Output is in `dist/` directory with:
- Code splitting (lazy-loaded chunks)
- Vendor chunks (react, router, radix, icons, charts, syntax)
- Minified and tree-shaken

### Bundle Analysis

The build uses manual chunks for optimal caching:

| Chunk | Contents |
|-------|----------|
| `vendor-react` | React, ReactDOM, scheduler |
| `vendor-router` | React Router |
| `vendor-radix` | Radix UI primitives |
| `vendor-icons` | Lucide icons |
| `vendor-syntax` | Syntax highlighter (lazy) |
| `vendor-charts` | Recharts, D3 (lazy) |

### Deployment Checklist

1. Run tests: `npm run test:run && npm run e2e`
2. Run linter: `npm run lint`
3. Build: `npm run build`
4. Test build: `npm run preview`
5. Deploy `dist/` to static hosting

## Troubleshooting

### Common Issues

**Port already in use**
```bash
# Kill process on port 5173
lsof -ti:5173 | xargs kill -9
```

**Module not found**
```bash
# Clear node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

**TypeScript errors**
```bash
# Check types
npx tsc --noEmit
```

**Vite cache issues**
```bash
# Clear Vite cache
rm -rf node_modules/.vite
npm run dev
```
