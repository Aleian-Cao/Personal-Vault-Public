/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ins: {
          navy: '#062C80',
          'navy-hover': '#0A3CA8',
          'navy-dark': '#041F5C',
          steel: '#4E6EA7',
          cyan: '#00C2FF',
          'cyan-soft': '#DDF7FF',
        }
      },
      fontFamily: {
        sans: ['"Segoe UI"', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
        mono: ['Consolas', '"Courier New"', 'monospace'],
      }
    },
  },
  plugins: [],
}
