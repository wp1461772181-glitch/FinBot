import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { watchBackend } from "./components/state/connectivity-store";
import { LocaleProvider } from "./i18n";
import "./styles/index.css";
import { applyTheme, storedTheme } from "./theme.mjs";
import { applyUpdown, storedUpdown } from "./updown.mjs";

watchBackend();
applyTheme(storedTheme());
applyUpdown(storedUpdown());
window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyTheme(storedTheme()));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LocaleProvider><App /></LocaleProvider>
  </StrictMode>,
);
