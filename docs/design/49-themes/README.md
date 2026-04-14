# 49 - Themes

## Overview

OpenAlgo's React frontend supports theme customization with light/dark modes and 12 base colors. Theme preferences persist across sessions using Zustand with localStorage. The theme system also manages "App Mode" (live vs analyzer) with distinct visual states.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Theme Architecture                                  │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         Theme Configuration                                  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Zustand Theme Store                                                 │   │
│  │                                                                      │   │
│  │  state: {                                                            │   │
│  │    mode: 'light' | 'dark',                                          │   │
│  │    color: 'zinc' | 'blue' | 'green' | 'violet' | ...               │   │
│  │    appMode: 'live' | 'analyzer',                                    │   │
│  │    isTogglingMode: boolean                                          │   │
│  │  }                                                                   │   │
│  │                                                                      │   │
│  │  actions: {                                                          │   │
│  │    setMode(mode),                                                   │   │
│  │    setColor(color),                                                 │   │
│  │    setAppMode(appMode),                                             │   │
│  │    toggleMode(),                                                    │   │
│  │    toggleAppMode(),   // async - calls backend                      │   │
│  │    syncAppMode()      // sync with backend state                    │   │
│  │  }                                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    │ persist to localStorage                 │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  localStorage                                                        │   │
│  │                                                                      │   │
│  │  openalgo-theme: {                                                  │   │
│  │    "state": {                                                       │   │
│  │      "theme": "dark",                                               │   │
│  │      "accentColor": "blue"                                          │   │
│  │    }                                                                │   │
│  │  }                                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ Apply to DOM
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            DOM Application                                   │
│                                                                              │
│  <html data-theme="dark" class="accent-blue">                              │
│    <body class="bg-base-100 text-base-content">                            │
│      <!-- DaisyUI components inherit theme -->                              │
│    </body>                                                                   │
│  </html>                                                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  CSS Variables Applied                                               │   │
│  │                                                                      │   │
│  │  --primary: hsl(217, 91%, 60%)      /* Accent color */              │   │
│  │  --secondary: hsl(217, 33%, 17%)                                    │   │
│  │  --accent: hsl(217, 91%, 70%)                                       │   │
│  │  --base-100: hsl(0, 0%, 100%)       /* Light mode */                │   │
│  │  --base-100: hsl(220, 13%, 18%)     /* Dark mode */                 │   │
│  │  --base-content: hsl(220, 13%, 69%)                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Theme Store Implementation

### Zustand Store

```typescript
// frontend/src/stores/themeStore.ts

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type ThemeMode = 'light' | 'dark';
type AppMode = 'live' | 'analyzer';
type ThemeColor = 'zinc' | 'slate' | 'stone' | 'gray' | 'neutral' | 'red' | 'rose' | 'orange' | 'green' | 'blue' | 'yellow' | 'violet';

interface ThemeState {
  theme: Theme;
  accentColor: AccentColor;
  setTheme: (theme: Theme) => void;
  setAccentColor: (color: AccentColor) => void;
  toggleTheme: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'light',
      accentColor: 'blue',

      setTheme: (theme) => {
        set({ theme });
        applyTheme(theme);
      },

      setAccentColor: (accentColor) => {
        set({ accentColor });
        applyAccentColor(accentColor);
      },

      toggleTheme: () => {
        set((state) => {
          const newTheme = state.theme === 'light' ? 'dark' : 'light';
          applyTheme(newTheme);
          return { theme: newTheme };
        });
      }
    }),
    {
      name: 'openalgo-theme',
      partialize: (state) => ({
        theme: state.theme,
        accentColor: state.accentColor
      })
    }
  )
);
```

### DOM Application

```typescript
function applyTheme(theme: Theme) {
  const html = document.documentElement;

  // DaisyUI theme attribute
  html.setAttribute('data-theme', theme);

  // Tailwind dark mode class
  if (theme === 'dark') {
    html.classList.add('dark');
  } else {
    html.classList.remove('dark');
  }
}

function applyAccentColor(color: AccentColor) {
  const html = document.documentElement;

  // Remove existing accent classes
  const accentClasses = ['accent-blue', 'accent-green', 'accent-purple',
                         'accent-orange', 'accent-red', 'accent-yellow',
                         'accent-pink', 'accent-cyan'];
  html.classList.remove(...accentClasses);

  // Add new accent class
  html.classList.add(`accent-${color}`);
}
```

## Available Themes

### Color Modes

```
┌────────────────────────────────────────────────────────────────────────────┐
│                            Theme Modes                                      │
│                                                                             │
│  Light Mode                           Dark Mode                             │
│  ───────────                          ─────────                             │
│  Background: #FFFFFF                  Background: #1F2937                   │
│  Surface: #F3F4F6                     Surface: #374151                      │
│  Text: #111827                        Text: #F9FAFB                         │
│  Border: #E5E7EB                      Border: #4B5563                       │
│                                                                             │
│  Optimized for:                       Optimized for:                        │
│  • Daylight visibility                • Reduced eye strain                  │
│  • Print-friendly                     • Low-light environments              │
│  • Professional settings              • OLED displays                       │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### Theme Colors (12 options)

| Color | Use Case |
|-------|----------|
| Zinc | Default neutral gray |
| Slate | Blue-gray neutral |
| Stone | Warm gray neutral |
| Gray | Pure gray |
| Neutral | Balanced neutral |
| Red | Errors, sell actions |
| Rose | Soft pink accent |
| Orange | Warnings, attention |
| Green | Success, growth |
| Blue | Professional, primary |
| Yellow | Caution, pending |
| Violet | Creative accent |

## App Mode (Live vs Analyzer)

The theme store manages two distinct app modes with different visual states:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         App Mode Behavior                                   │
│                                                                             │
│  LIVE MODE (default):                                                       │
│  • User can toggle light/dark mode                                         │
│  • User can change theme color (zinc, blue, green, etc.)                   │
│  • Normal application appearance                                           │
│                                                                             │
│  ANALYZER MODE (sandbox):                                                   │
│  • Theme changes are BLOCKED (setMode, setColor, toggleMode disabled)     │
│  • Fixed dark purple theme via CSS class 'analyzer'                        │
│  • Visual distinction for paper trading environment                        │
│  • Mode synced with backend via /auth/analyzer-mode                        │
│                                                                             │
│  Switching modes:                                                           │
│  • toggleAppMode() - async call to /auth/analyzer-toggle                  │
│  • syncAppMode() - fetches current mode from backend                      │
│  • Mode changes emit events via onModeChange() listener                   │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### Implementation

```typescript
// Handle analyzer mode theme changes
const useAnalyzerTheme = () => {
  const { setAccentColor, accentColor } = useThemeStore();
  const { isAnalyzerMode } = useAnalyzerStore();
  const previousColorRef = useRef<AccentColor>(accentColor);

  useEffect(() => {
    if (isAnalyzerMode) {
      // Save current and switch to purple
      previousColorRef.current = accentColor;
      setAccentColor('purple');
    } else {
      // Restore previous color
      setAccentColor(previousColorRef.current);
    }
  }, [isAnalyzerMode]);
};
```

## Theme Settings UI

### Theme Toggle Component

```typescript
function ThemeToggle() {
  const { theme, toggleTheme } = useThemeStore();

  return (
    <button
      onClick={toggleTheme}
      className="btn btn-ghost btn-circle"
      aria-label="Toggle theme"
    >
      {theme === 'light' ? (
        <MoonIcon className="w-5 h-5" />
      ) : (
        <SunIcon className="w-5 h-5" />
      )}
    </button>
  );
}
```

### Color Picker Component

```typescript
const ACCENT_COLORS = [
  { name: 'blue', label: 'Blue', class: 'bg-blue-500' },
  { name: 'green', label: 'Green', class: 'bg-green-500' },
  { name: 'purple', label: 'Purple', class: 'bg-purple-500' },
  { name: 'orange', label: 'Orange', class: 'bg-orange-500' },
  { name: 'red', label: 'Red', class: 'bg-red-500' },
  { name: 'yellow', label: 'Yellow', class: 'bg-yellow-500' },
  { name: 'pink', label: 'Pink', class: 'bg-pink-500' },
  { name: 'cyan', label: 'Cyan', class: 'bg-cyan-500' },
];

function AccentColorPicker() {
  const { accentColor, setAccentColor } = useThemeStore();

  return (
    <div className="flex flex-wrap gap-2">
      {ACCENT_COLORS.map((color) => (
        <button
          key={color.name}
          onClick={() => setAccentColor(color.name as AccentColor)}
          className={`
            w-8 h-8 rounded-full ${color.class}
            ${accentColor === color.name ? 'ring-2 ring-offset-2 ring-primary' : ''}
          `}
          aria-label={`Select ${color.label} accent`}
        />
      ))}
    </div>
  );
}
```

### Settings Page Section

```typescript
function ThemeSettings() {
  const { theme, accentColor, setTheme, setAccentColor } = useThemeStore();

  return (
    <div className="card bg-base-200 p-6">
      <h2 className="text-xl font-semibold mb-4">Appearance</h2>

      <div className="space-y-6">
        {/* Theme Mode */}
        <div>
          <label className="label">
            <span className="label-text">Theme Mode</span>
          </label>
          <div className="flex gap-2">
            <button
              onClick={() => setTheme('light')}
              className={`btn ${theme === 'light' ? 'btn-primary' : 'btn-ghost'}`}
            >
              <SunIcon className="w-4 h-4 mr-2" />
              Light
            </button>
            <button
              onClick={() => setTheme('dark')}
              className={`btn ${theme === 'dark' ? 'btn-primary' : 'btn-ghost'}`}
            >
              <MoonIcon className="w-4 h-4 mr-2" />
              Dark
            </button>
          </div>
        </div>

        {/* Accent Color */}
        <div>
          <label className="label">
            <span className="label-text">Accent Color</span>
          </label>
          <AccentColorPicker />
        </div>
      </div>
    </div>
  );
}
```

## CSS Implementation

### DaisyUI Theme Configuration

```javascript
// tailwind.config.js

module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  plugins: [require('daisyui')],
  daisyui: {
    themes: [
      {
        light: {
          "primary": "#3B82F6",
          "secondary": "#6B7280",
          "accent": "#8B5CF6",
          "neutral": "#374151",
          "base-100": "#FFFFFF",
          "base-200": "#F3F4F6",
          "base-300": "#E5E7EB",
          "info": "#3ABFF8",
          "success": "#36D399",
          "warning": "#FBBD23",
          "error": "#F87272",
        },
        dark: {
          "primary": "#3B82F6",
          "secondary": "#6B7280",
          "accent": "#8B5CF6",
          "neutral": "#1F2937",
          "base-100": "#1F2937",
          "base-200": "#374151",
          "base-300": "#4B5563",
          "info": "#3ABFF8",
          "success": "#36D399",
          "warning": "#FBBD23",
          "error": "#F87272",
        }
      }
    ]
  }
};
```

### Accent Color CSS

```css
/* frontend/src/styles/accent-colors.css */

/* Blue accent (default) */
.accent-blue {
  --color-primary: 217 91% 60%;
  --color-primary-focus: 217 91% 50%;
}

/* Green accent */
.accent-green {
  --color-primary: 142 76% 36%;
  --color-primary-focus: 142 76% 30%;
}

/* Purple accent */
.accent-purple {
  --color-primary: 270 76% 60%;
  --color-primary-focus: 270 76% 50%;
}

/* Orange accent */
.accent-orange {
  --color-primary: 24 95% 53%;
  --color-primary-focus: 24 95% 45%;
}

/* Red accent */
.accent-red {
  --color-primary: 0 84% 60%;
  --color-primary-focus: 0 84% 50%;
}

/* Yellow accent */
.accent-yellow {
  --color-primary: 45 93% 47%;
  --color-primary-focus: 45 93% 40%;
}

/* Pink accent */
.accent-pink {
  --color-primary: 330 81% 60%;
  --color-primary-focus: 330 81% 50%;
}

/* Cyan accent */
.accent-cyan {
  --color-primary: 187 92% 41%;
  --color-primary-focus: 187 92% 35%;
}
```

## System Preference Detection

```typescript
// Detect system color scheme preference
function useSystemTheme() {
  const { setTheme } = useThemeStore();

  useEffect(() => {
    // Check if user has set a preference
    const stored = localStorage.getItem('openalgo-theme');
    if (stored) return; // User preference takes precedence

    // Use system preference
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    setTheme(mediaQuery.matches ? 'dark' : 'light');

    // Listen for changes
    const handler = (e: MediaQueryListEvent) => {
      setTheme(e.matches ? 'dark' : 'light');
    };

    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);
}
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `frontend/src/stores/themeStore.ts` | Zustand theme store |
| `frontend/src/components/ThemeToggle.tsx` | Toggle button |
| `frontend/src/components/AccentColorPicker.tsx` | Color picker |
| `frontend/src/styles/accent-colors.css` | Accent CSS vars |
| `frontend/tailwind.config.js` | DaisyUI themes |
