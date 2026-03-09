# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## 临时公网演示（ngrok）

1. 启动后端并使用 ngrok 暴露后端端口（例如 8001）。
2. 将 `frontend/.env.example` 复制为 `frontend/.env.local`，并设置：
   `VITE_API_BASE=https://your-backend-ngrok-url`
3. 启动前端后，使用 ngrok 暴露前端端口（例如 5173）。
4. 在后端环境变量中设置允许的前端来源（示例）：
   `ALLOW_ORIGINS=https://your-frontend-ngrok-url`

## 单 ngrok 临时公网演示

1. 启动后端：
   `uvicorn main:app --host 0.0.0.0 --port 8001 --reload`
2. 启动前端：
   `npm run dev`
3. 启动 ngrok（只暴露前端 5173）：
   `ngrok http 5173`
4. 后端环境变量 `NGROK_PUBLIC_URL` 填写“前端 ngrok 公网地址”。
5. 因为现在只有一个公网地址，前端不再需要 `VITE_API_BASE`。
6. 如果保留 `frontend/.env.example`，在单 ngrok 方案下不是必需。

为什么不用双 ngrok：同时维护两个公网地址容易出错且本地端口冲突。

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
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

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
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
