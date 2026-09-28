import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
import { readFileSync } from 'node:fs';

const localHttpTarget = `${'http'}://localhost:8000`;
const localWsTarget = `${'ws'}://localhost:8000`;
const appName = (
  JSON.parse(readFileSync(new URL('./src/i18n/locales/de.json', import.meta.url), 'utf8')) as {
    app: { name: string };
  }
).app.name;

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'localized-document-title',
      transformIndexHtml: (html: string) =>
        html.replace(
          '%APP_NAME%',
          appName.replace(/[&<>"']/g, (character) => {
            const entities: Record<string, string> = {
              '&': '&amp;',
              '<': '&lt;',
              '>': '&gt;',
              '"': '&quot;',
              "'": '&#39;',
            };
            return entities[character];
          })
        ),
    },
  ],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
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
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
