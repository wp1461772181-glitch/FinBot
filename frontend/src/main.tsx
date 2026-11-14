import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { prefetchMarkdown } from "./app/chat/markdown-loader";
import { watchBackend } from "./components/state/connectivity-store";
import { LocaleProvider, preloadSavedLocale } from "./i18n";
import "./styles/index.css";
import { applyTheme, storedTheme } from "./theme.mjs";
import { applyUpdown, storedUpdown } from "./updown.mjs";

watchBackend();
applyTheme(storedTheme());
applyUpdown(storedUpdown());
window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyTheme(storedTheme()));

// The chat's Markdown renderer is a chunk of its own: start fetching it now, in parallel with the page's code and the history request,
// so it is usually in before the first message needs it.  An address that names another section does not pay for it (the chat page
// asks for it itself when it is opened later).
if (!/^#\/(research|portfolio|routines|assistant|settings|dev)(\/|\?|$)/.test(window.location.hash)) prefetchMarkdown();

void preloadSavedLocale().then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <LocaleProvider><App /></LocaleProvider>
    </StrictMode>,
  );
});
