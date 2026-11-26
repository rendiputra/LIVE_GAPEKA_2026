// Serve the built frontend under a SUB-PATH, the way a static host might expose
// it (https://host/gapeka/). With `base: "./"` every asset URL is relative, so
// the app and its worker must resolve against the page, not the server root.
//
// Run: node e2e/subpath-server.mjs <root> <prefix> <port>

import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";

const ROOT = resolve(process.argv[2] ?? "dist");
const PREFIX = process.argv[3] ?? "/sub/";
const PORT = Number(process.argv[4] ?? 4175);

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
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
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