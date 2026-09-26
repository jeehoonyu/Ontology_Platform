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
          //
          // `graphLayout` rides here too, for the same round trip at a price.
          // It is 663 bytes, imported by the pipeline and the platform graph,
          // and Rollup gave it its own chunk: `audit_route_cost` measured graph
          // at 15 requests on open (ceiling 14) and pipeline at 16 (ceiling 15)
          // after `1f7fee5` moved the layout into `src/lib`. This chunk is one
          // every route already loads, so the two graph screens lose a request
          // and the other fifteen routes pay 619 bytes each for it. Grouping it
          // with the store shim both graph screens load instead split that shim
          // and gave five other routes a request each.
          //
          // `Tabs` (GOAL_FOUNDATIONS A8) rides here for the same reason: Decision
          // and Ontology Manager import it, Rollup gave it a chunk of its own, and
          // `audit_route_cost` measured each at one more request on open. Every
          // route already loads this chunk, so each pays about a kilobyte instead.
          "dragdrop-vendor": ["@dnd-kit/core", "@dnd-kit/sortable", "@dnd-kit/utilities",
                              "./src/components/dnd/DragKit.tsx", "./src/lib/graphLayout.ts",
                              "./src/components/layout/Tabs.tsx"],
          "query-vendor": ["@tanstack/react-query"],
          "icons-vendor": ["lucide-react"]
        }
      }
    }
  }
});
