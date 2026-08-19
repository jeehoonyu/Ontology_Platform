import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/react/",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // The chunk graph, so `oms/audit_route_payload.py` can say what each
    // workspace route costs a browser rather than guessing from filenames.
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks: {
          "dragdrop-vendor": ["@dnd-kit/core", "@dnd-kit/sortable", "@dnd-kit/utilities"],
          "query-vendor": ["@tanstack/react-query"],
          "icons-vendor": ["lucide-react"]
        }
      }
    }
  }
});
