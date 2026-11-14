// Minimal static server: serves a Vite build output directory under BASE (production is the finbotai.me root, "/").
// Unknown paths under the base fall back to index.html (hash routing never needs it, but a refresh would).
import http from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";

export const BASE = "/";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
  ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon",
  ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".map": "application/json",
};

/** Start a static server for `distDir` on a random free port. Resolves to { origin, url, close }. */
export async function startServer(distDir) {
  const root = path.resolve(distDir);
  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://localhost");
      if (!url.pathname.startsWith(BASE)) {
        // Only reachable when BASE is a sub-path: send the bare root there.
        if (url.pathname === "/") { response.writeHead(302, { Location: BASE }); response.end(); return; }
        response.writeHead(404); response.end("not found"); return;
      }
      let relative = decodeURIComponent(url.pathname.slice(BASE.length)) || "index.html";
      let file = path.join(root, relative);
      if (!file.startsWith(root + path.sep) && file !== root) { response.writeHead(403); response.end(); return; }
      let info = await stat(file).catch(() => null);
      if (info?.isDirectory()) { file = path.join(file, "index.html"); info = await stat(file).catch(() => null); }
      if (!info) { file = path.join(root, "index.html"); }
      const body = await readFile(file);
      response.writeHead(200, { "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream", "Cache-Control": "no-store" });
      response.end(body);
    } catch (error) {
      response.writeHead(500); response.end(String(error));
    }
  });
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  const { port } = server.address();
  const origin = `http://127.0.0.1:${port}`;
  return { origin, url: `${origin}${BASE}`, close: () => new Promise((resolve) => server.close(() => resolve())) };
}
