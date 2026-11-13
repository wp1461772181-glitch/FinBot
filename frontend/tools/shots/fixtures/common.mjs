// Deterministic helpers shared by the fixtures.
import { WATCHLIST } from "./ids.mjs";

/** mulberry32: small seeded PRNG so every run builds the same data. */
export function rng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export const hashSeed = (text) => [...String(text)].reduce((acc, ch) => (Math.imul(acc, 31) + ch.charCodeAt(0)) | 0, 7);

/** The fixed "now" of every run (2026-11-13 10:00 Beijing) and helpers around it. */
export const NOW = new Date("2026-11-13T02:00:00.000Z");
export const iso = (date) => new Date(date).toISOString().replace(/\.\d{3}Z$/, "Z");
export const daysAgo = (days, hour = 2) => { const d = new Date(NOW); d.setUTCDate(d.getUTCDate() - days); d.setUTCHours(hour, 0, 0, 0); return iso(d); };
export const dayOnly = (days) => daysAgo(days).slice(0, 10);
export const minutesAgo = (minutes) => iso(new Date(NOW.getTime() - minutes * 60_000));

/** Business days (Mon-Fri) ending at `end` (YYYY-MM-DD), oldest first. */
export function businessDays(count, end = "2026-11-12") {
  const days = []; const cursor = new Date(`${end}T00:00:00Z`);
  while (days.length < count) { const day = cursor.getUTCDay(); if (day !== 0 && day !== 6) days.unshift(cursor.toISOString().slice(0, 10)); cursor.setUTCDate(cursor.getUTCDate() - 1); }
  return days;
}

const START = { AAPL: 192, TSLA: 248, NVDA: 118, AMD: 148, MSFT: 402, GOOGL: 168, AMZN: 186 };
const DRIFT = { AAPL: 0.0007, TSLA: 0.0004, NVDA: 0.0016, AMD: 0.0003, MSFT: 0.0006, GOOGL: 0.0008, AMZN: 0.0007 };
const VOL = { AAPL: 0.011, TSLA: 0.026, NVDA: 0.022, AMD: 0.021, MSFT: 0.0105, GOOGL: 0.0125, AMZN: 0.0135 };
const cache = new Map();

/** About one year of daily candles for a symbol: a seeded random walk, deterministic per symbol. */
export function candles(symbol) {
  if (cache.has(symbol)) return cache.get(symbol);
  const random = rng(hashSeed(symbol));
  const gauss = () => { let sum = 0; for (let i = 0; i < 6; i += 1) sum += random(); return (sum - 3) / 0.7071; };
  const days = businessDays(252);
  let close = START[symbol] ?? 100 + (hashSeed(symbol) % 120);
  let bench = 5200;
  const rows = days.map((day) => {
    const open = close * (1 + gauss() * 0.003);
    close = Math.max(5, close * (1 + (DRIFT[symbol] ?? 0.0005) + gauss() * (VOL[symbol] ?? 0.015)));
    bench *= 1 + 0.0005 + gauss() * 0.007;
    const high = Math.max(open, close) * (1 + random() * 0.008);
    const low = Math.min(open, close) * (1 - random() * 0.008);
    const volume = Math.round((18 + random() * 40) * 1_000_000 * (symbol === "TSLA" || symbol === "NVDA" ? 2.4 : 1));
    const fix = (value) => Math.round(value * 100) / 100;
    return { trading_date: day, open: fix(open), high: fix(high), low: fix(low), close: fix(close), volume, benchmark_close: fix(bench) };
  });
  cache.set(symbol, rows);
  return rows;
}
export const lastClose = (symbol) => candles(symbol).at(-1).close;
export const prices = (symbol) => ({ symbol, price_history: { source: "market_data", latest_trading_date: candles(symbol).at(-1).trading_date, candles: candles(symbol) } });

export const COMPANY_NAMES = { AAPL: "Apple Inc.", TSLA: "Tesla, Inc.", NVDA: "NVIDIA Corporation", AMD: "Advanced Micro Devices, Inc.", MSFT: "Microsoft Corporation", GOOGL: "Alphabet Inc.", AMZN: "Amazon.com, Inc." };
export { WATCHLIST };
