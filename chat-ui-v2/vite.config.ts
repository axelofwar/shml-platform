import path from "path"
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  base: '/chat-ui/',
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 3001,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost',
        changeOrigin: true,
      },
      '/chat': {
        target: 'http://localhost',
        changeOrigin: true,
      },
      // WebSocket proxy for agent service test endpoint
      // Routes to Traefik which strips /ws-test and forwards to agent service
      '/ws-test': {
        target: 'http://localhost',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
