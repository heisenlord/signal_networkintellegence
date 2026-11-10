import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiBase = env.VITE_API_BASE_URL || '/api/v1';
  if (apiBase !== '/api/v1') {
    const url = new URL(apiBase);
    if (url.pathname !== '/api/v1' || url.search || url.hash || url.username || url.password
        || (mode === 'production' && url.protocol !== 'https:')) {
      throw new Error('VITE_API_BASE_URL must be /api/v1 or an HTTPS API URL ending in /api/v1');
    }
  }
  return {
    plugins: [react(), tailwindcss()],
    server: { port: 5173, strictPort: true, proxy: { '/api': env.API_PROXY_TARGET || 'http://127.0.0.1:8000' } },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            topology: ['@xyflow/react', 'dagre'],
            charts: ['recharts'],
          },
        },
      },
    },
  };
});
