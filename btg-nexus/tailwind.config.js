/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}'
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'monospace']
      },
      colors: {
        // Core surfaces — tinted neutrals (not pure gray)
        nexus: {
          950: '#070B0E',  // deepest background, subtly blue-tinted
          900: '#0D131A',  // card / elevated surface
          850: '#111820',  // card hover
          800: '#1A2230',  // border
          700: '#243040',  // input
          600: '#334458',  // muted
          500: '#4A5E78',  // muted foreground
          400: '#7A8FA3',  // secondary text
          200: '#C8D6E0',  // primary text
        },
        // Primary signal — Cyan
        signal: {
          400: '#22D3EE',  // bright
          500: '#06B6D4',  // primary
          600: '#0891B2',  // hover
          950: '#083344',  // darkest background
        },
        // Secondary accent — Fuchsia
        accent: {
          400: '#E879F9',
          500: '#D946EF',
          600: '#C026D3',
        },
        // Warning
        warn: {
          400: '#FBBF24',
          500: '#F59E0B',
          600: '#D97706',
        },
        // Danger / Threshold
        danger: {
          400: '#FB7185',
          500: '#F43F5E',
          600: '#E11D48',
        }
      },
      backdropBlur: {
        'glass': '12px',
        'glass-lg': '20px',
      },
      animation: {
        'breathe': 'breathe 2s ease-in-out infinite',
        'watchdog-shrink': 'shrink 2s linear infinite',
        'watchdog-blink': 'blink 0.5s ease-in-out infinite',
        'slide-in-up': 'slideInUp 300ms var(--ease-out-expo) both',
        'fade-in': 'fadeIn 200ms ease-out both',
      },
      keyframes: {
        breathe: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.65' },
        },
        shrink: {
          '0%': { transform: 'scaleX(1)' },
          '100%': { transform: 'scaleX(0)' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.2' },
        },
        slideInUp: {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
      }
    }
  },
  plugins: []
}