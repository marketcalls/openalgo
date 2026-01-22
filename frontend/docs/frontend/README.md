# OpenAlgo Frontend Documentation

Welcome to the OpenAlgo React frontend documentation. This guide covers everything you need to know to develop, test, and maintain the frontend application.

## Table of Contents

1. [Developer Guide](./developer-guide.md) - Getting started, project structure, conventions
2. [Components](./components.md) - UI components, layouts, and patterns
3. [API Reference](./api-reference.md) - Hooks, stores, and API integration
4. [Testing Guide](./testing-guide.md) - Unit tests, E2E tests, accessibility testing

## Quick Start

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Run tests
npm run test

# Build for production
npm run build
```

## Tech Stack

| Category | Technology |
|----------|------------|
| Framework | React 19 |
| Language | TypeScript |
| Build Tool | Vite 7 |
| Styling | Tailwind CSS 4 |
| UI Components | Radix UI + shadcn/ui |
| State Management | Zustand |
| Data Fetching | TanStack Query |
| Routing | React Router 7 |
| Testing | Vitest + Playwright |
| Linting | Biome |

## Project Overview

OpenAlgo frontend is a single-page application (SPA) that provides:

- **Dashboard** - Real-time trading overview
- **Order Management** - Orderbook, tradebook, positions
- **Strategy Management** - Webhook strategies, Python strategies, Chartink
- **Platform Integration** - TradingView, GoCharting webhooks
- **Admin Tools** - System configuration, monitoring, logs
- **Responsive Design** - Mobile-first with bottom navigation

## Architecture

```
src/
├── api/          # API client functions
├── components/   # Reusable UI components
├── config/       # App configuration
├── hooks/        # Custom React hooks
├── lib/          # Utility functions
├── pages/        # Route page components
├── stores/       # Zustand state stores
├── test/         # Test utilities
└── types/        # TypeScript type definitions
```

## Key Features

- **Code Splitting** - Lazy-loaded pages for optimal performance
- **Theme Support** - Light/dark mode with system preference
- **Accessibility** - WCAG 2.1 AA compliant
- **Real-time Updates** - WebSocket integration for live data
- **Offline Ready** - Graceful degradation when offline
