import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/cases': 'http://127.0.0.1:8000',
      '/init-case': 'http://127.0.0.1:8000',
      '/plan': 'http://127.0.0.1:8000',
      '/action': 'http://127.0.0.1:8000',
      '/resume-customer-input': 'http://127.0.0.1:8000'
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
});