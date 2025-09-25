/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js",
  ],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        // Professional Trading Colors
        'trade': {
          'buy': '#10B981',   // Professional Green
          'sell': '#EF4444',  // Professional Red
          'buyHover': '#059669',
          'sellHover': '#DC2626',
          'buyLight': '#D1FAE5',
          'sellLight': '#FEE2E2',
        },
        // Professional Palette
        'pro': {
          50: '#F8FAFC',
          100: '#F1F5F9',
          200: '#E2E8F0',
          300: '#CBD5E1',
          400: '#94A3B8',
          500: '#64748B',
          600: '#475569',
          700: '#334155',
          800: '#1E293B',
          900: '#0F172A',
          950: '#020617',
        },
        // Status Colors
        'status': {
          'online': '#10B981',
          'offline': '#6B7280',
          'pending': '#F59E0B',
          'executed': '#10B981',
          'rejected': '#EF4444',
          'cancelled': '#6B7280',
        }
      },
      fontFamily: {
        'sans': ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        'mono': ['JetBrains Mono', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        'data': ['Roboto Mono', 'SF Mono', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.75rem' }],
        'xs': ['0.75rem', { lineHeight: '1rem' }],
        'sm': ['0.875rem', { lineHeight: '1.25rem' }],
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
        '128': '32rem',
      },
      height: {
        'navbar': '44px',
        'row': '32px',
        'row-compact': '28px',
      },
      width: {
        'sidebar': '240px',
        'sidebar-collapsed': '60px',
        'order-widget': '320px',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-up': 'slideUp 0.2s ease-out',
        'slide-down': 'slideDown 0.2s ease-out',
        'fade-in': 'fadeIn 0.15s ease-in',
        'price-flash': 'priceFlash 0.3s ease-out',
        'number-change': 'numberChange 0.4s ease-out',
      },
      keyframes: {
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideDown: {
          '0%': { transform: 'translateY(-10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        priceFlash: {
          '0%': { backgroundColor: 'transparent' },
          '50%': { backgroundColor: 'rgba(34, 197, 94, 0.1)' },
          '100%': { backgroundColor: 'transparent' },
        },
        numberChange: {
          '0%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.1)' },
          '100%': { transform: 'scale(1)' },
        },
      },
      boxShadow: {
        'trade': '0 0 0 3px rgba(59, 130, 246, 0.1)',
        'soft': '0 2px 8px rgba(0, 0, 0, 0.04)',
        'medium': '0 4px 16px rgba(0, 0, 0, 0.08)',
      },
      gridTemplateColumns: {
        'trading-layout': '240px 1fr 320px',
        'trading-compact': '60px 1fr 320px',
      },
    },
  },
  daisyui: {
    themes: [
      {
        professional: {
          "primary": "#2563EB",
          "secondary": "#64748B",
          "accent": "#F59E0B",
          "neutral": "#1F2937",
          "base-100": "#FFFFFF",
          "base-200": "#F9FAFB",
          "base-300": "#F3F4F6",
          "info": "#0891B2",
          "success": "#10B981",
          "warning": "#F59E0B",
          "error": "#EF4444",
          "--rounded-box": "0.25rem",
          "--rounded-btn": "0.25rem",
          "--rounded-badge": "0.25rem",
        },
        professional_dark: {
          "primary": "#3B82F6",
          "secondary": "#64748B",
          "accent": "#FBBF24",
          "neutral": "#E5E7EB",
          "base-100": "#0A0A0A",
          "base-200": "#171717",
          "base-300": "#262626",
          "info": "#06B6D4",
          "success": "#34D399",
          "warning": "#FBBF24",
          "error": "#F87171",
          "--rounded-box": "0.25rem",
          "--rounded-btn": "0.25rem",
          "--rounded-badge": "0.25rem",
        },
        analytics: {
          "primary": "#059669",
          "secondary": "#10B981",
          "accent": "#84CC16",
          "neutral": "#065F46",
          "base-100": "#F0FDF4",
          "base-200": "#FFFFFF",
          "base-300": "#ECFDF5",
          "info": "#06B6D4",
          "success": "#34D399",
          "warning": "#FCD34D",
          "error": "#F87171",
          "--rounded-box": "0.25rem",
          "--rounded-btn": "0.25rem",
          "--rounded-badge": "0.25rem",
        },
      },
      "light",
      "dark",
      "garden"
    ],
    darkTheme: "professional_dark",
    base: true,
    styled: true,
    utils: true,
    prefix: "",
    logs: false,
  },
  plugins: [require("daisyui")]
}
