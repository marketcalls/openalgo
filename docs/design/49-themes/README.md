# 49 - Themes And App Mode

## State

`frontend/src/stores/themeStore.ts` is a persisted Zustand store with three related values:

| Value | Options | Purpose |
|---|---|---|
| `mode` | `light`, `dark` | User preference in live mode |
| `color` | zinc, slate, stone, gray, neutral, red, rose, orange, green, blue, yellow, violet | Accent theme |
| `appMode` | `live`, `analyzer` | Backend trading mode reflected in UI |

The store persists under `openalgo-theme`. Rehydration applies the `.dark` class, `.analyzer` class, and `data-theme` attribute to the document root.

## Mode Rules

Live mode permits light/dark and accent changes. Analyzer mode applies its dedicated analyzer theme and suppresses user theme/accent mutations until the app returns to live mode. Backend mode is synchronized from `/auth/analyzer-mode`; toggles use a CSRF token and `/auth/analyzer-toggle`.

Mode-change listeners allow data-heavy pages to refetch or reset state when moving between live and analyzer sources.

## CSS

`frontend/src/index.css` defines Tailwind variables, light/dark tokens, analyzer/sandbox overrides, and accent selectors. The frontend does not use DaisyUI or a separate Tailwind configuration file.

## Controls

Theme and app-mode controls are rendered by `frontend/src/components/layout/Navbar.tsx`. Lucide icons and accessible labels describe light/dark actions. Accent choices set the store's `color` value rather than loading a separate stylesheet.

## Invariants

- Persist visual state across logout for continuity, but resynchronize trading app mode after authentication.
- Never let a client-only color choice change backend analyzer/live behavior.
- Analyzer/live toggle failures must leave the last confirmed app mode intact.
- New accent names require both the TypeScript union and CSS variables/selectors.

## Key Files

| File | Purpose |
|---|---|
| `frontend/src/stores/themeStore.ts` | Persisted state and backend mode sync |
| `frontend/src/components/layout/Navbar.tsx` | User controls |
| `frontend/src/index.css` | Theme, accent, and mode variables |
