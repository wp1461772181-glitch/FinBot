import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { rewriteAgentChatProxyPath } from "./src/agent-chat-url.mjs";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    // GitHub Pages project sites are hosted below /<repository-name>/.
    // Local development and other static hosts keep the normal root path.
    base: env.VITE_BASE_PATH || "/",
    plugins: [react(), tailwindcss()],
    resolve: {
      // "@/" -> src/ (shadcn convention).  The .mjs logic modules never use it, so node --test still runs them bare.
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    build: {
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              // Pins where react-router lives: every module of the package goes into ONE chunk that is
              // named "hooks" (the name Rolldown already derived from react-router's lib/hooks module, so the
              // first-screen file list keeps the same de-hashed names).  Without this the package is split
              // between the entry chunk and a shared chunk according to which lazy pages happen to import
              // what, so moving a small export between two page files could re-cut it and add 1-2 files
              // (+1.3 kB gzip) to the first screen (seen in P6.4 when frames.tsx lost ResearchFrame).
              // includeDependenciesRecursively is off on purpose: with it on (measured on Rolldown 1.2.9) the
              // group also swallows react itself, the shared module-runtime helpers end up in a separate
              // "rolldown-runtime" chunk, and that is a new file name on the first screen.  This group only
              // fixes the chunk shape; it does not decide what the first screen needs.
              { name: "hooks", test: /node_modules[\\/]react-router[\\/]/, includeDependenciesRecursively: false },
            ],
          },
        },
      },
    },
    server: {
      proxy: {
        "/api": {
          target: env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000",
          changeOrigin: true,
          rewrite: (path) => rewriteAgentChatProxyPath(path).replace(/^\/api/, ""),
        },
      },
    },
  };
});
