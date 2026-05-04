import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          // 单独拆 echarts（最重）；antd 与大量 deps 交织，拆分会触发 rollup circular chunk 警告
          if (id.includes("echarts")) return "echarts";
          return "vendor";
        }
      }
    },
    chunkSizeWarningLimit: 1600
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
        timeout: 600_000
      }
    }
  }
});
