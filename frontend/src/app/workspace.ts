import { createContext, useContext, type Dispatch, type SetStateAction } from "react";
import type { Bot } from "../api/bots";
import type { WorkspaceSection } from "../workspace-sections.mjs";

export type BotList = { bots: Bot[]; loaded: boolean; error: string; reload: () => Promise<void>; defaultBot: Bot | null };

/** What the workspace layout shares with the pages under it (the routed outlet reads it; nothing else does). */
export type Workspace = {
  /** Owner mode: bots, routines, the research queue on the server. */
  personal: boolean;
  /** The research queue. */
  symbols: string[];
  setSymbols: Dispatch<SetStateAction<string[]>>;
  /** The company the page is about: the one in the address when it has one, else the preferred one. */
  symbol: string;
  /** Last company the reader had open (a stored preference; only a default for addresses without a company). */
  preferredSymbol: string;
  setPreferredSymbol: (symbol: string) => void;
  bots: BotList;
  /** Jump to a section by its old name (what the pages' own buttons speak). */
  go: (section: WorkspaceSection) => void;
  /** Open a company's page: its overview, or its forecasts. */
  openCompany: (ticker: string, view?: "overview" | "forecast") => void;
  /** Take a code off the watchlist.  `stay`: the reader is looking at that company and keeps looking (the company page's own ★), instead of moving to the next one. */
  removeWatchSymbol: (ticker: string, options?: { stay?: boolean }) => void;
  /** Open the new-bot dialog (the sidebar's 新建 bot; the phone's bot switcher has the same entry). */
  openNewBot: () => void;
};

export const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace needs the workspace layout above it");
  return value;
}
