import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
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
