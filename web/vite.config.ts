/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// `npm run dev` proxies the relay's endpoints to the Python server, so the page and the API share an origin.
const relay = { target: 'https://localhost:8080', secure: false, changeOrigin: true };

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/status': relay, '/view': relay, '/frame': relay, '/ca.crt': relay, '/baby': relay, '/detections': relay },
  },
  test: { include: ['src/**/*.test.ts'] },
});
