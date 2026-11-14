import { useState } from "react";
import { ChevronRight } from "lucide-react";

// A small folding tree for a node's raw data.  Keys and values are shown as they are (never translated); objects and arrays fold,
// the first level is open, the rest closed.  No dependency: this is the whole viewer.

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

const isBranch = (value: Json): value is Json[] | { [key: string]: Json } => typeof value === "object" && value !== null;

function Leaf({ value }: { value: Json }) {
  if (typeof value === "string") return <span className="break-words text-ink [overflow-wrap:anywhere]">"{value}"</span>;
  return <span className="text-ink-2">{String(value)}</span>;
}

function Branch({ name, value, depth }: { name?: string; value: Json[] | { [key: string]: Json }; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  const array = Array.isArray(value);
  const entries: [string, Json][] = array ? value.map((item, index) => [String(index), item]) : Object.entries(value);
  const head = array ? `[${entries.length}]` : `{${entries.length}}`;
  return <div role="treeitem" aria-expanded={open} aria-selected="false">
    <button type="button" className="inline-flex items-center gap-0.5 rounded-sm text-left outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setOpen((x) => !x)}>
      <ChevronRight aria-hidden="true" className={`size-3 shrink-0 transition-transform duration-1 ${open ? "rotate-90" : ""}`} />
      {name !== undefined && <span className="text-ink-2">{name}:</span>}
      <span className="text-muted-foreground">{head}</span>
    </button>
    {open && <div role="group" className="ml-3 border-l border-line pl-2">{entries.length === 0 ? <span className="text-muted-foreground">{array ? "[]" : "{}"}</span> : entries.map(([key, item]) => <Entry key={key} name={key} value={item} depth={depth + 1} />)}</div>}
  </div>;
}

function Entry({ name, value, depth }: { name: string; value: Json; depth: number }) {
  if (isBranch(value)) return <Branch name={name} value={value} depth={depth} />;
  return <div role="treeitem" aria-selected="false" className="flex gap-1.5 pl-3.5"><span className="shrink-0 text-ink-2">{name}:</span><Leaf value={value} /></div>;
}

/** The raw data of a step as a folding tree.  It is only drawn once the 原始数据 section is opened. */
export function JsonViewer({ value }: { value: unknown }) {
  const root = value as Json;
  return <div role="tree" data-testid="json-viewer" className="overflow-x-auto font-mono text-caption leading-5">
    {isBranch(root) ? <Branch value={root} depth={0} /> : <Leaf value={root} />}
  </div>;
}
