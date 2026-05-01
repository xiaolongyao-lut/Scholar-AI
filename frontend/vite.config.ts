import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test/setup.ts'],
  },
  server: {
    port: 3000,
    proxy: {
      '/actions': 'http://127.0.0.1:8000',
      '/capabilities': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/runtime': 'http://127.0.0.1:8000',
      '/resources': 'http://127.0.0.1:8000',
      '/skills': 'http://127.0.0.1:8000',
      '/pipeline': 'http://127.0.0.1:8000',
      '/memory': 'http://127.0.0.1:8000',
      '/recovery': 'http://127.0.0.1:8000',
      '/autopilot': 'http://127.0.0.1:8000',
      '/inspiration': 'http://127.0.0.1:8000',
      '/agent': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:8000',
    },
  },
});
