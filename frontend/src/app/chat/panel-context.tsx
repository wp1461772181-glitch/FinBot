import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { PANEL_DEFAULT, availableTabs, clampPanelWidth, initialTab, selectedIndex, storedPanelWidth, type PanelTab } from "../../panel-model.mjs";
import { useChat } from "./ChatSessionProvider";

// The right panel's state (design 4.2): open or folded, which tab, how wide, and which round of the conversation it shows.  It lives
// above the thread and the panel so a citation chip or the process bar in a message can open the panel on the right tab.

const OPEN_KEY = "market-evidence-agent:bot-side-open:v1";        // the old right rail's key: the choice made there is kept
const TAB_KEY = "market-evidence-agent:chat-panel-tab:v1";
const WIDTH_KEY = "market-evidence-agent:chat-panel-width:v1";

const read = (key: string): string | null => { try { return localStorage.getItem(key); } catch { return null; } };
const write = (key: string, value: string) => { try { localStorage.setItem(key, value); } catch { /* a preference, not required */ } };
/** Beside the thread from xl up, over it below that: the panel starts open only where it does not cover the thread. */
const wide = () => window.matchMedia?.("(min-width: 1280px)").matches ?? true;

/** Where a jump to a source points: a round, and the source's number in it (null: the tab only). `nonce` makes the same jump twice a new one. */
export type SourceFocus = { key: string | null; ordinal: number | null; nonce: number; byKeyboard: boolean };

export type PanelApi = {
  tabs: PanelTab[];
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  tab: PanelTab;
  /** The reader's own choice of tab: kept for the next visit. */
  chooseTab: (tab: PanelTab) => void;
  width: number;
  setWidth: (px: number, keep?: boolean) => void;
  /** The key of the round shown, or null for the newest answer with content. */
  turn: string | null;
  /** The index of the round shown in the thread's messages (-1: none). */
  index: number;
  focus: SourceFocus | null;
  handledFocus: { current: number };
  /** Point the panel at a source of a round: opens it, on 来源, and marks the card. */
  showSource: (key: string, ordinal: number | null, origin?: HTMLElement | null, byKeyboard?: boolean) => void;
  /** Point the panel at a round's steps: opens it, on 过程. */
  showProcess: (key: string) => void;
  /** Give the focus back to the chip that sent the reader to a source. */
  returnToOrigin: () => boolean;
};

const Context = createContext<PanelApi | null>(null);

export function PanelProvider({ hasWorkspace, hasProfile, startOnProfile, children }: { hasWorkspace: boolean; hasProfile: boolean; startOnProfile: boolean; children: ReactNode }) {
  const c = useChat();
  const tabs = useMemo(() => availableTabs({ hasWorkspace, hasProfile }), [hasWorkspace, hasProfile]);
  const [open, setOpenState] = useState(() => {
    if (startOnProfile) return true;
    const stored = read(OPEN_KEY);
    return stored === null ? hasWorkspace && wide() : stored === "1";
  });
  const [tab, setTab] = useState<PanelTab>(() => (startOnProfile && tabs.includes("profile") ? "profile" : initialTab(read(TAB_KEY), tabs)));
  const [width, setWidthState] = useState(() => storedPanelWidth(read(WIDTH_KEY)) || PANEL_DEFAULT);
  const [turn, setTurn] = useState<string | null>(null);
  const [focus, setFocus] = useState<SourceFocus | null>(null);
  const handledFocus = useRef(0), nonce = useRef(0), origin = useRef<HTMLElement | null>(null);

  const setOpen = useCallback((next: boolean) => { setOpenState(next); write(OPEN_KEY, next ? "1" : "0"); }, []);
  const toggle = useCallback(() => setOpenState((value) => { write(OPEN_KEY, value ? "0" : "1"); return !value; }), []);
  const chooseTab = useCallback((next: PanelTab) => { setTab(next); if (next !== "profile") write(TAB_KEY, next); }, []);
  const setWidth = useCallback((px: number, keep = true) => { const next = clampPanelWidth(px); setWidthState(next); if (keep) write(WIDTH_KEY, String(next)); }, []);

  // A tab this page does not have (the page changed from a bot's to none) falls back to the first one it has.
  useEffect(() => { if (!tabs.includes(tab)) setTab(initialTab(null, tabs)); }, [tabs, tab]);
  // The profile route opened while the page was already up (the header's gear): show 档案.
  useEffect(() => { if (startOnProfile && tabs.includes("profile")) { setTab("profile"); setOpenState(true); } }, [startOnProfile, tabs]);
  // A new question ends the choice of an older round: the panel follows the turn that is being answered.
  useEffect(() => { if (c.state === "sending") setTurn(null); }, [c.state]);

  const showSource = useCallback((key: string, ordinal: number | null, from?: HTMLElement | null, byKeyboard = false) => {
    origin.current = from ?? null;
    nonce.current += 1;
    setTurn(key); setTab("sources"); setOpen(true);
    setFocus({ key, ordinal, nonce: nonce.current, byKeyboard });
  }, [setOpen]);
  const showProcess = useCallback((key: string) => { setTurn(key); setTab("process"); setOpen(true); }, [setOpen]);
  const returnToOrigin = useCallback(() => {
    const el = origin.current;
    if (!el || !el.isConnected) return false;
    el.focus();
    return true;
  }, []);

  const index = selectedIndex(c.messages, turn);
  const value = useMemo<PanelApi>(() => ({ tabs, open, setOpen, toggle, tab, chooseTab, width, setWidth, turn, index, focus, handledFocus, showSource, showProcess, returnToOrigin }),
    [tabs, open, setOpen, toggle, tab, chooseTab, width, setWidth, turn, index, focus, showSource, showProcess, returnToOrigin]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function usePanel(): PanelApi {
  const value = useContext(Context);
  if (!value) throw new Error("The chat panel provider is missing");
  return value;
}
