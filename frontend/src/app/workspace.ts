import { createContext, useContext } from "react";
import type { Bot } from "../api";
import type { WorkspaceSection } from "../Shell";

export type BotList = { bots: Bot[]; loaded: boolean; error: string; reload: () => Promise<void>; defaultBot: Bot | null };

/** What the workspace layout shares with the pages under it (the routed outlet reads it; nothing else does). */
export type Workspace = {
  /** Owner mode: bots, routines, the research queue on the server. */
  personal: boolean;
  /** The research queue. */
  symbols: string[];
  setSymbols: (symbols: string[]) => void;
  /** The company the page is about: the one in the address when it has one, else the preferred one. */
  symbol: string;
  /** Last company the reader had open (a stored preference; only a default for addresses without a company). */
  preferredSymbol: string;
  setPreferredSymbol: (symbol: string) => void;
  bots: BotList;
  onModeChange: (mode: "guest" | "personal") => void;
  /** Jump to a section by its old name (what SectionTabs, the rail and the pages' buttons speak). */
  go: (section: WorkspaceSection) => void;
  /** Open a company's page: its overview, or its forecasts. */
  openCompany: (ticker: string, view?: "overview" | "forecast") => void;
  removeWatchSymbol: (ticker: string) => void;
};

export const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace needs the workspace layout above it");
  return value;
}
