/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['Space Grotesk', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Cascadia Code', 'Consolas', 'monospace'],
      },
      boxShadow: {
        cyan: '0 0 24px rgba(6, 182, 212, 0.16)',
        purple: '0 0 24px rgba(168, 85, 247, 0.16)',
        danger: '0 0 28px rgba(244, 63, 94, 0.28)',
      },
    },
  },
  plugins: [],
}
