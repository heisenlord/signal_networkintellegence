import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ command, mode, isPreview }) => {
  const env = loadEnv(mode, process.cwd(), '');
  let apiBase = (env.VITE_API_BASE_URL || (mode === 'production'
    ? 'https://signal-networkintellegence.onrender.com/api/v1'
    : '/api/v1')).trim().replace(/\/+$/, '');
  let apiOrigin: string | undefined;
  if (apiBase !== '/api/v1') {
    let url: URL;
    try { url = new URL(apiBase); }
    catch { throw new Error('VITE_API_BASE_URL must be /api/v1 or a backend HTTP(S) URL, optionally ending in /api/v1'); }
    if (!['http:', 'https:'].includes(url.protocol)
        || !['/', '/api/v1'].includes(url.pathname) || url.search || url.hash || url.username || url.password
        || (mode === 'production' && url.protocol !== 'https:')) {
      throw new Error('VITE_API_BASE_URL must be /api/v1 or a backend URL, optionally ending in /api/v1; production requires HTTPS');
    }
    apiOrigin = url.origin;
    apiBase = `${apiOrigin}/api/v1`;
  }
  const devServer = command === 'serve' && !isPreview;
  return {
    define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify(devServer ? '/api/v1' : apiBase) },
    plugins: [react(), tailwindcss()],
    server: { port: 5173, strictPort: true, proxy: { '/api': {
      target: apiOrigin || env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true,
    } } },
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
