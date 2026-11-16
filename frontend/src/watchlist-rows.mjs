// The watchlist page's rows as pure functions (P6.1): which forecast a company's row shows, the facts of its row, and the small
// request pool that keeps the page from opening dozens of connections at once.
import { forecastBySymbol } from "./forecast-home.mjs";
import { priceChange, recentCloses } from "./data-display.mjs";
import { hasProbabilities } from "./probability-bar.mjs";

/** The newest formal forecast of a company in a list of forecast rows (the list the page reads once for the whole queue), or null. */
export function latestForecast(rows, symbol) {
  return (forecastBySymbol(rows).get(String(symbol ?? "").toUpperCase()) ?? [])[0] ?? null;
}

/**
 * The facts of one watchlist row from what has been read for it.  `forecast` is a forecast list row or null, `candles` the price
 * candles or null (not read / failed), `materialTotal` the library's total or null.  Every field is a fact or null; nothing here
 * says what to do with the company.
 */
export function watchRow({ symbol, forecast = null, candles = null, materialTotal = null }) {
  const price = candles === null ? null : priceChange(candles);
  return {
    symbol,
    price,
    closes: candles === null ? [] : recentCloses(candles),
    forecast: forecast ? {
      id: forecast.id, versionNo: forecast.latest_version_no, targetDate: forecast.target_end_date ?? null, status: forecast.model_status,
      probabilities: hasProbabilities(forecast.probabilities) ? forecast.probabilities : null, model: forecast.decider?.actual_model ?? null, decisionAt: forecast.decision_at,
    } : null,
    materialTotal: Number.isFinite(materialTotal) ? materialTotal : null,
  };
}

/** The watchlist with `ticker` put back at `index` (the 撤销 of a removal); unchanged when it is already there or the list is full. */
export function restoreAt(items, ticker, index, max = 30) {
  if (items.includes(ticker) || items.length >= max) return items;
  const at = Math.min(Math.max(0, index), items.length);
  return [...items.slice(0, at), ticker, ...items.slice(at)];
}

/**
 * A limit on how many reads run at once.  `run(task, signal)` starts `task()` when a slot is free (in the order asked) and resolves with its
 * result; a task whose signal is aborted before it starts never runs and rejects with an AbortError.  The page uses it for the per-row reads
 * so thirty rows make at most `size` requests at a time instead of sixty at once.
 */
export function createPool(size = 6) {
  let active = 0;
  const waiting = [];
  const next = () => {
    while (active < size && waiting.length) {
      const job = waiting.shift();
      if (job.signal?.aborted) { job.reject(abortError()); continue; }
      active += 1;
      Promise.resolve().then(job.task).then(job.resolve, job.reject).finally(() => { active -= 1; next(); });
    }
  };
  return {
    run(task, signal) {
      return new Promise((resolve, reject) => {
        if (signal?.aborted) { reject(abortError()); return; }
        waiting.push({ task, signal, resolve, reject });
        signal?.addEventListener("abort", () => {
          const index = waiting.findIndex((job) => job.task === task);
          if (index >= 0) { waiting.splice(index, 1); reject(abortError()); }
        }, { once: true });
        next();
      });
    },
    get active() { return active; },
    get waiting() { return waiting.length; },
  };
}

function abortError() {
  const error = new Error("aborted");
  error.name = "AbortError";
  return error;
}
