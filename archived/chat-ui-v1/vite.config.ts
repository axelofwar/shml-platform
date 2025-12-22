import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/chat-ui/',
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/chat': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      '/api/chat': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
