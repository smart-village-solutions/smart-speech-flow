# Smart Speech Flow - Frontend# React + TypeScript + Vite



React + TypeScript + Vite Frontend für die Smart Speech Flow Echtzeit-Übersetzungsanwendung.This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.



## FeaturesCurrently, two official plugins are available:



- 🔐 Passwortgeschützte Landing Page- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh

- 👨‍💼 Admin-Interface für Session-Verwaltung- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

- 👤 Kunden-Interface mit Session-Beitritt

- 🎤 Audio-Aufnahme mit WebRTC MediaRecorder## React Compiler

- 💬 Echtzeit-Messaging über WebSocket

- 🌐 Mehrsprachige UnterstützungThe React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

- 📱 Responsive Design

## Expanding the ESLint configuration

## Production Deployment

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

Das Frontend wird über Docker + Nginx bereitgestellt unter **translate.smart-village.solutions**

```js

### Quick Deployexport default defineConfig([

  globalIgnores(['dist']),

```bash  {

cd /root/projects/ssf-backend    files: ['**/*.{ts,tsx}'],

docker compose build frontend    extends: [

docker compose up -d frontend      // Other configs...

```

      // Remove tseslint.configs.recommended and replace with this

### Verify Deployment      tseslint.configs.recommendedTypeChecked,

      // Alternatively, use this for stricter rules

- Frontend: https://translate.smart-village.solutions      tseslint.configs.strictTypeChecked,

- Health Check: https://translate.smart-village.solutions/health      // Optionally, add this for stylistic rules

      tseslint.configs.stylisticTypeChecked,

## Environment Variables (Production)

      // Other configs...

Werden in `docker-compose.yml` konfiguriert:    ],

    languageOptions: {

```yaml      parserOptions: {

environment:        project: ['./tsconfig.node.json', './tsconfig.app.json'],

  - VITE_API_BASE_URL=https://ssf.smart-village.solutions        tsconfigRootDir: import.meta.dirname,

  - VITE_WS_BASE_URL=wss://ssf.smart-village.solutions      },

  - VITE_APP_PASSWORD=ssf2025kassel      // other options...

```    },

  },

## Development (Optional)])

```

```bash

cd services/frontendYou can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

npm install

npm run dev  # http://localhost:5174```js

```// eslint.config.js

import reactX from 'eslint-plugin-react-x'

## Licenseimport reactDom from 'eslint-plugin-react-dom'



Proprietary - Smart Village Solutionsexport default defineConfig([

  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```
