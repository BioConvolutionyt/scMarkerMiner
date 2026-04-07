import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        manualChunks(id) {
                    if (id.includes('node_modules/vue') || id.includes('node_modules/vue-router') || id.includes('node_modules/@vue')) {
                      return 'vendor-vue'
                    }
                    if (id.includes('node_modules/element-plus') || id.includes('node_modules/@element-plus')) {
                      return 'vendor-element'
                    }
                    if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) {
                      return 'vendor-echarts'
                    }
                  },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
