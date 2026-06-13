// frontend/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  // Serve the data/ folder as static files at root during dev
  // In production, Vercel serves them from dist/ (copied by build script)
  publicDir: path.resolve(__dirname, '../data'),
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
        }
      }
    }
  },
  server: { port: 3000 },
  resolve: { alias: { '@': path.resolve(__dirname, './src') } }
})
