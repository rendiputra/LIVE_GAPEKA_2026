// Tiles belong on object storage, not in the static site bundle (ADR 009).
// Vite copies `public/**` into `dist/`, including the generated PMTiles archive,
// which made the "static site" 269 MB. Remove it after the build so a deploy
// cannot accidentally ship tiles from the wrong origin.

import { existsSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";

const DIST = "dist";
const TILES = join(DIST, "tiles");

if (existsSync(TILES)) {
  rmSync(TILES, { recursive: true, force: true });
  console.log("pruned dist/tiles (tiles are hosted separately)");
}

const indexPath = join(DIST, "index.html");
if (!existsSync(indexPath)) {
  console.error("dist/index.html missing: the build did not produce a site");
  process.exit(1);
}
console.log(`dist/index.html ${statSync(indexPath).size} bytes`);
