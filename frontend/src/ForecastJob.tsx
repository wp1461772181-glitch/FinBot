import { translatePhrase } from "./i18n";
import { ApiError } from "./api/base";

/** What to tell the reader about a failed request: the server's own sentence for an API error, else the fallback (a zh-CN phrase key).  Used by the monitor page. */
export function errorMessage(error: unknown, fallback: string) {
  return translatePhrase(error instanceof ApiError ? error.message : fallback);
}
