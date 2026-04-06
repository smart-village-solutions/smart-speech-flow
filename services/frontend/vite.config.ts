import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const localHttpTarget = `${'http'}://localhost:8000`
const localWsTarget = `${'ws'}://localhost:8000`

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: localHttpTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: localWsTarget,
        ws: true,
      },
    },
  },
})
