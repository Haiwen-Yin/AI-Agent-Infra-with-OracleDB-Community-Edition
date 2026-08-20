import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 420,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("vis-network") || id.includes("vis-data")) return "graph-vendor";
          if (id.includes("lucide-react")) return "icon-vendor";
          return "vendor";
        },
      },
    },
  },
});
