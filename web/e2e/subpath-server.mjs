// T7: serve the built site under a SUB-PATH, the way a real deployment might
// (e.g. https://example.com/gapeka/). `base: "./"` means every asset URL is
// relative, so the worker's data fetch must resolve against the page, not the
// server root.

import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";

const ROOT = resolve(process.argv[2] ?? "dist-e2e");
const PREFIX = process.argv[3] ?? "/sub/";
const PORT = Number(process.argv[4] ?? 4174);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".pbf": "application/x-protobuf",
  ".pmtiles": "application/octet-stream",
  ".woff2": "font/woff2",
};

createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://localhost");
  let path = decodeURIComponent(url.pathname);

  if (!path.startsWith(PREFIX)) {
    response.writeHead(404, { "content-type": "text/plain" });
    response.end(`not under ${PREFIX}`);
    return;
  }
  path = path.slice(PREFIX.length - 1);
  if (path === "" || path === "/") path = "/index.html";

  const target = join(ROOT, normalize(path).replace(/^(\.\.[/\\])+/, ""));
  if (!target.startsWith(ROOT) || !existsSync(target) || !statSync(target).isFile()) {
    // SPA fallback.
    const fallback = join(ROOT, "index.html");
    if (existsSync(fallback)) {
      response.writeHead(200, { "content-type": TYPES[".html"] });
      createReadStream(fallback).pipe(response);
      return;
    }
    response.writeHead(404, { "content-type": "text/plain" });
    response.end("not found");
    return;
  }

  response.writeHead(200, {
    "content-type": TYPES[extname(target)] ?? "application/octet-stream",
    "cache-control": "no-store",
  });
  createReadStream(target).pipe(response);
}).listen(PORT, "127.0.0.1", () => {
  console.log(`serving ${ROOT} at http://127.0.0.1:${PORT}${PREFIX}`);
});
