import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { loadEnv } from 'vite';
import { securityHeaders } from './security/securityPolicy.ts';

const localHttpTarget = `${'http'}://localhost:8000`;
const localWsTarget = `${'ws'}://localhost:8000`;
const appName = (
  JSON.parse(readFileSync(new URL('./src/i18n/locales/de.json', import.meta.url), 'utf8')) as {
    app: { name: string };
  }
).app.name;
const previewPolicy = securityHeaders(loadEnv('production', import.meta.dirname, ''), false);

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
  preview: {
    headers: { [previewPolicy.name]: previewPolicy.policy },
  },
  test: {
    exclude: [...configDefaults.exclude, 'e2e/**'],
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
