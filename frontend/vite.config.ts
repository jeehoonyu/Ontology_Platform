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
          // `DragKit` rides with the library it configures. It is 843 bytes and
          // Rollup gave it its own chunk, because three lazy routes import it --
          // so every dragging route paid an extra round trip for well under a
          // kilobyte, and `audit_route_cost` caught the pipeline route going
          // from 12 requests on open to 13. Any route that loads DragKit needs
          // dnd-kit anyway, so folding it in costs no route a byte it was not
          // already fetching.
          "dragdrop-vendor": ["@dnd-kit/core", "@dnd-kit/sortable", "@dnd-kit/utilities",
                              "./src/components/dnd/DragKit.tsx"],
          "query-vendor": ["@tanstack/react-query"],
          "icons-vendor": ["lucide-react"]
        }
      }
    }
  }
});
