import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/health': apiProxyTarget,
        '/ui-config': apiProxyTarget,
        '/cases': apiProxyTarget,
        '/init-case': apiProxyTarget,
        '/plan': apiProxyTarget,
        '/action': apiProxyTarget,
        '/resume-customer-input': apiProxyTarget,
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
    },
  };
});