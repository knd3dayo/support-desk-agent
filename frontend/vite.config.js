import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, '.', '');
    var apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8010';
    return {
        plugins: [react()],
        server: {
            port: 5173,
            proxy: {
                '/health': apiProxyTarget,
                '/ui-config': apiProxyTarget,
                '/control-catalog': apiProxyTarget,
                '/runtime-constraints': apiProxyTarget,
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
