/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'primary': {
          DEFAULT: '#00A99D', // Smart-Kassel-Türkis (Akzentfarbe)
          dark: '#0A2342',    // Stadt-Kassel-Dunkelblau
        },
        'accent': '#00A99D',
        'background': '#F8F8F8',
        'text': '#333333',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      fontSize: {
        base: '18px',
      },
      lineHeight: {
        relaxed: '1.6',
      },
      borderRadius: {
        'card': '12px',
        'card-lg': '16px',
      },
      boxShadow: {
        'card': '0 4px 16px rgba(0, 0, 0, 0.08)',
        'card-hover': '0 8px 24px rgba(0, 0, 0, 0.12)',
      },
      spacing: {
        'section': '80px',
        'section-lg': '100px',
      },
    },
  },
  plugins: [],
}
