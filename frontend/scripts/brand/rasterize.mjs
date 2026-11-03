// Rasterise the brand SVGs to the PNGs index.html links (favicon 64, apple-touch-icon 180).
// @resvg/resvg-js is not a project dependency: `mkdir /tmp/r && cd /tmp/r && npm i @resvg/resvg-js`, then
//   node scripts/brand/rasterize.mjs /tmp/r/node_modules/@resvg/resvg-js/index.js   (from frontend/)
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
const { Resvg } = createRequire(import.meta.url)(process.argv[2] ?? "@resvg/resvg-js");
const render = (svg, width) => new Resvg(svg, { fitTo: { mode: "width", value: width } }).render().asPng();
// The tab icon is ink on a light bar; PNG has no prefers-color-scheme, so it stays ink (the SVG icon carries the dark variant).
writeFileSync("public/favicon.png", render(readFileSync("public/favicon.svg", "utf8"), 64));
// iOS draws the touch icon on black if transparent: a paper plate with the green mark.
const logo = readFileSync("public/logo.svg", "utf8").replace(/<svg[^>]*viewBox="[^"]*"[^>]*>/, m => m.replace(/viewBox="[^"]*"/, 'viewBox="-140 -140 280 280"')).replace("<title>FinBot</title>", '<rect x="-140" y="-140" width="280" height="280" fill="#f9f9f9"/>');
writeFileSync("public/apple-touch-icon.png", render(logo, 180));
