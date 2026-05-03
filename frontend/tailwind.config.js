export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        mf: {
          bg: '#06080d',
          'bg-secondary': '#0c1018',
          card: '#111827',
          elevated: '#1a2235',
          green: '#76b900',
          indigo: '#818cf8',
          border: '#1e293b',
          patent: '#d4a574',
        },
      },
      fontFamily: {
        display: ['Instrument Serif', 'Georgia', 'serif'],
        sans: ['Outfit', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
};
