// Pixel-compare two screenshot directories file by file.
//   node compare.mjs <dirA> <dirB> [--out <diff dir>] [--max-diff-pixels 0]
// Same-named PNGs are compared; a size mismatch or a file on one side only counts as a difference.
import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { PNG } from "pngjs";
import pixelmatch from "pixelmatch";
import { parseArgs } from "./args.mjs";

const { flags, positional } = parseArgs(process.argv.slice(2));
const [dirA, dirB] = positional;
if (!dirA || !dirB) { console.error("usage: node compare.mjs <dirA> <dirB> [--out <diff dir>] [--max-diff-pixels 0]"); process.exit(2); }
const threshold = Number(flags["max-diff-pixels"] ?? 0);
const pngs = async (dir) => new Set((await readdir(dir)).filter((name) => name.endsWith(".png") && !name.endsWith(".FAILED.png")));
const [a, b] = await Promise.all([pngs(dirA), pngs(dirB)]);
const names = [...new Set([...a, ...b])].sort();
if (flags.out) await mkdir(flags.out, { recursive: true });

let same = 0; let different = 0;
const rows = [];
for (const name of names) {
  if (!a.has(name) || !b.has(name)) { different += 1; rows.push({ name, verdict: `MISSING on ${a.has(name) ? "B" : "A"}` }); continue; }
  const imageA = PNG.sync.read(await readFile(path.join(dirA, name)));
  const imageB = PNG.sync.read(await readFile(path.join(dirB, name)));
  if (imageA.width !== imageB.width || imageA.height !== imageB.height) {
    different += 1; rows.push({ name, verdict: `SIZE ${imageA.width}x${imageA.height} vs ${imageB.width}x${imageB.height}` }); continue;
  }
  const diff = new PNG({ width: imageA.width, height: imageA.height });
  const count = pixelmatch(imageA.data, imageB.data, diff.data, imageA.width, imageA.height, { threshold: 0, includeAA: true });
  const share = (count / (imageA.width * imageA.height)) * 100;
  if (count > threshold) {
    different += 1; rows.push({ name, verdict: `DIFF ${count} px (${share.toFixed(3)}%)` });
    if (flags.out) await writeFile(path.join(flags.out, name.replace(/\.png$/, ".diff.png")), PNG.sync.write(diff));
  } else { same += 1; rows.push({ name, verdict: count ? `ok (${count} px within threshold)` : "same" }); }
}
for (const row of rows) if (row.verdict !== "same" || flags.verbose) console.log(`${row.name.padEnd(40)} ${row.verdict}`);
console.log(`\ncompared ${names.length} files: ${same} same, ${different} different (max-diff-pixels ${threshold})`);
process.exit(different ? 1 : 0);
