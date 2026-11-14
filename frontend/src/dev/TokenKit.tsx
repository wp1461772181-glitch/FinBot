// Developer-only sections of the sample page (#dev-kit): the design tokens of P1.2 on show.  Palette, type scale,
// the three materials, and the market colours with a live up/down switch.  Copy is English on purpose (no i18n),
// except the strings the design fixes in Chinese (the opinion label and the disclaimer, quoted verbatim).
import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, CircleAlert, CircleCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { applyUpdown, saveUpdown, storedUpdown, type UpdownChoice } from "../updown.mjs";

const SWATCHES = [
  "bg", "surface", "sunken", "ink", "ink-2", "muted", "faint", "line", "line-strong",
  "accent", "accent-soft", "on-accent", "opinion", "opinion-soft", "action", "action-soft",
  "hover", "up", "down", "success", "danger", "deep", "on-deep",
] as const;

const STEPS = [
  { cls: "text-caption", name: "caption", spec: "12 / 16 · 500" },
  { cls: "text-small", name: "small", spec: "13 / 20 · 400" },
  { cls: "text-body", name: "body", spec: "14 / 22 · 400" },
  { cls: "text-chat", name: "chat", spec: "15 / 26 · 400" },
  { cls: "text-title-s", name: "title-s", spec: "16 / 24 · 600" },
  { cls: "text-title-m", name: "title-m", spec: "20 / 28 · 600" },
  { cls: "text-title-l", name: "title-l", spec: "24 / 32 · 600" },
  { cls: "text-display", name: "display", spec: "30 / 36 · 600" },
] as const;

function toHex(rgb: string) {
  const m = rgb.match(/\d+(\.\d+)?/g);
  if (!m || m.length < 3) return rgb;
  return "#" + m.slice(0, 3).map((n) => Math.round(Number(n)).toString(16).padStart(2, "0")).join("");
}

function KitSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3" data-kit-section={title}>
      <h2 className="text-small font-semibold text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

/** Re-render when <html> changes its theme or up/down attribute, so resolved colours stay current. */
function useRootAttributes() {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() => setVersion((v) => v + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-updown"] });
    return () => observer.disconnect();
  }, []);
  return version;
}

function Swatch({ name, version }: { name: string; version: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [hex, setHex] = useState("");
  useEffect(() => {
    if (ref.current) setHex(toHex(getComputedStyle(ref.current).backgroundColor));
  }, [version]);
  return (
    <div className="space-y-1.5" data-kit-swatch={name}>
      <div ref={ref} className="h-12 rounded-sm border border-line-strong" style={{ backgroundColor: `var(--${name})` }} />
      <div className="text-caption font-medium text-foreground">{name}</div>
      <div className="font-mono text-caption text-muted-foreground">{hex}</div>
    </div>
  );
}

export function PaletteBlock() {
  const version = useRootAttributes();
  return (
    <KitSection title="Palette (semantic tokens)">
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        {SWATCHES.map((name) => <Swatch key={name} name={name} version={version} />)}
      </div>
    </KitSection>
  );
}

export function TypeBlock() {
  return (
    <KitSection title="Type scale and typefaces">
      <div className="space-y-2" data-kit="type-scale">
        {STEPS.map((step) => (
          <div key={step.name} className="flex items-baseline gap-4 border-b border-line pb-2">
            <div className="w-48 shrink-0 whitespace-nowrap font-mono text-caption text-muted-foreground">{step.name} {step.spec}</div>
            <div className={step.cls}>Evidence first 证据先行 · Revenue 营收 94,930 · +2.31%</div>
          </div>
        ))}
      </div>
      <div className="space-y-2">
        <p className="font-sans text-body"><span className="mr-3 font-mono text-caption text-muted-foreground">font-sans</span>Inter, then system Chinese: 界面与正文 Interface 0123456789</p>
        <p className="font-mono text-body"><span className="mr-3 text-caption text-muted-foreground">font-mono</span>JetBrains Mono: 金额 $1,234.56 · 概率 47% · 2026-11-10</p>
        <p className="font-quote text-body"><span className="mr-3 font-mono text-caption text-muted-foreground">font-quote</span>Source Serif 4, then Song: 逐字引文 Verbatim quotation 0123456789</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="material-fact p-3">
          <div className="mb-1 text-caption text-muted-foreground">Original quote (font-quote)</div>
          <p className="font-quote text-body">“We expect gross margin to be between 46% and 47%, and operating expenses between $14.2 and $14.5 billion.”</p>
        </div>
        <div className="rounded-md border border-line bg-surface p-3">
          <div className="mb-1 text-caption text-muted-foreground">Model paraphrase (font-sans)</div>
          <p className="font-sans text-body">管理层预计毛利率在 46% 到 47% 之间，运营费用在 142 亿到 145 亿美元之间。</p>
        </div>
      </div>
    </KitSection>
  );
}

function ProbabilityBar({ down, flat, up }: { down: number; flat: number; up: number }) {
  return (
    <div className="space-y-1.5" data-kit="probability-bar">
      <div className="flex h-2 overflow-hidden rounded-full bg-sunken">
        <i className="bg-down" style={{ width: `${down}%` }} data-segment="down" />
        <i className="bg-muted-foreground" style={{ width: `${flat}%` }} data-segment="flat" />
        <i className="bg-up" style={{ width: `${up}%` }} data-segment="up" />
      </div>
      <div className="flex justify-between font-mono text-caption tabular-nums text-muted-foreground">
        <span>Down {down}%</span><span>Flat {flat}%</span><span>Up {up}%</span>
      </div>
    </div>
  );
}

export function MaterialsBlock() {
  return (
    <KitSection title="Three materials (fact / opinion / action)">
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Fact: an excerpt with its source number, and figures that line up. */}
        <div className="material-fact space-y-3 p-4" data-material="fact">
          <span className="material-fact-source">[1]</span>
          <div className="text-caption text-muted-foreground">Fact · 10-Q, MD&amp;A</div>
          <p className="font-quote text-body">“Net sales increased 6% year over year, driven primarily by higher Services revenue.”</p>
          <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-body">
            <dt className="text-muted-foreground">Revenue</dt><dd className="num text-right">94,930</dd>
            <dt className="text-muted-foreground">Gross profit</dt><dd className="num text-right">43,879</dd>
            <dt className="text-muted-foreground">Net income</dt><dd className="num text-right">23,636</dd>
            <dt className="text-muted-foreground">Diluted EPS</dt><dd className="num text-right">1.46</dd>
          </dl>
        </div>

        {/* Opinion: the model's judgement, with a nested fact block for the evidence it leans on. */}
        <div className="material-opinion space-y-3 p-4" data-material="opinion">
          <span className="material-opinion-label">模型意见 · gpt-6.1-terra · 11-10</span>
          <p className="text-body">Next 20 trading days: the model leans up on the services mix and the guide above the street.</p>
          <ProbabilityBar down={22} flat={31} up={47} />
          <div className="material-fact space-y-1 p-3" data-material="fact-nested">
            <span className="material-fact-source">[2]</span>
            <div className="text-caption text-muted-foreground">Fact, nested</div>
            <p className="font-quote text-small">“Guidance: revenue growth in the low-to-mid single digits.”</p>
          </div>
          <p className="material-opinion-footnote">概率未经校准，属实验性信息。仅供参考，买不买由你决定。</p>
        </div>

        {/* Action: a write that waits for the user. */}
        <div className="material-action relative space-y-3 p-4" data-material="action">
          <span className="material-action-timer absolute right-4 top-4">04:32</span>
          <div className="material-action-label">等你确认 · Waiting for you</div>
          <p className="text-body">Add AAPL and MSFT to the watchlist, and track AAPL earnings on 11-20.</p>
          <div className="flex gap-2">
            <Button size="sm">Confirm</Button>
            <Button size="sm" variant="outline">Not now</Button>
          </div>
        </div>
      </div>
    </KitSection>
  );
}

function Delta({ kind, value }: { kind: "up" | "down"; value: string }) {
  const Icon = kind === "up" ? ArrowUp : ArrowDown;
  return (
    <span className={`inline-flex items-center gap-1 font-mono tabular-nums ${kind === "up" ? "text-up" : "text-down"}`} data-kit-delta={kind}>
      <Icon className="size-4" aria-hidden /> {value}
    </span>
  );
}

function Candle({ kind, x, top, bottom }: { kind: "up" | "down"; x: number; top: number; bottom: number }) {
  const color = kind === "up" ? "var(--up)" : "var(--down)";
  return (
    <g>
      <line x1={x + 4} x2={x + 4} y1={top - 6} y2={bottom + 6} stroke={color} strokeWidth="1.5" />
      <rect x={x} y={top} width="8" height={bottom - top} fill={color} />
    </g>
  );
}

export function UpDownBlock() {
  const version = useRootAttributes();
  const [choice, setChoice] = useState<UpdownChoice>(() => storedUpdown());
  useEffect(() => { setChoice((document.documentElement.dataset.updown as UpdownChoice) || storedUpdown()); }, [version]);
  const flip = () => {
    const next: UpdownChoice = choice === "green-up" ? "red-up" : "green-up";
    saveUpdown(next);
    applyUpdown(next);
    setChoice(next);
  };
  return (
    <KitSection title="Market colours (up / down) and status colours">
      <div className="flex flex-wrap items-center gap-4">
        <Button variant="outline" onClick={flip} data-kit="updown-toggle">Switch to {choice === "green-up" ? "red up" : "green up"}</Button>
        <span className="font-mono text-caption text-muted-foreground" data-kit="updown-current">data-updown={choice}</span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2 rounded-md border border-line bg-surface p-4">
          <div className="text-caption text-muted-foreground">Quotes: arrow and sign carry the direction</div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-body">
            <Delta kind="up" value="+2.31%" />
            <Delta kind="down" value="-1.08%" />
            <Delta kind="up" value="+0.42" />
            <Delta kind="down" value="-3.77" />
          </div>
          <div className="flex items-end gap-6">
            <div className="text-display font-semibold tabular-nums">189.84</div>
            <Delta kind="up" value="+4.12 (+2.22%)" />
          </div>
          <svg width="120" height="48" viewBox="0 0 120 48" role="img" aria-label="Two sample candles, one up and one down">
            <Candle kind="up" x={20} top={14} bottom={34} />
            <Candle kind="down" x={60} top={10} bottom={28} />
            <Candle kind="up" x={90} top={20} bottom={38} />
          </svg>
          <ProbabilityBar down={30} flat={20} up={50} />
        </div>
        <div className="space-y-3 rounded-md border border-line bg-surface p-4">
          <div className="text-caption text-muted-foreground">Status colours do not move with the switch</div>
          <div role="status" className="flex items-center gap-2 rounded-sm border border-success bg-sunken p-3 text-body text-success" data-kit-status="success">
            <CircleCheck className="size-4 shrink-0" aria-hidden /> Saved. 3 items updated.
          </div>
          <div role="alert" className="flex items-center gap-2 rounded-sm border border-danger bg-sunken p-3 text-body text-danger" data-kit-status="error">
            <CircleAlert className="size-4 shrink-0" aria-hidden /> Request failed (503). Try again.
          </div>
        </div>
      </div>
    </KitSection>
  );
}
