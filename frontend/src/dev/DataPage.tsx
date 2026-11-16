// Developer-only sample page of the four data components (P6.1), at #/dev/kit/data: the opinion card, the probability bar, the stat tile and the status
// badge, each in its states.  Its own address (like /dev/kit/states) so the screenshots of /dev/kit stay put.  Never reachable from the UI; the route in
// app/router.tsx only loads it when import.meta.env.DEV or VITE_DEV_KIT=1.  Copy is English on purpose; the components bring their own words.
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { OpinionCard, OpinionFacts } from "@/components/OpinionCard";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { Sparkline } from "@/components/Sparkline";
import { Change, StatTile } from "@/components/StatTile";
import { StatusBadge } from "@/components/StatusBadge";
import { applyUpdown, saveUpdown, storedUpdown, type UpdownChoice } from "../updown.mjs";
import { signedChange } from "../data-display.mjs";

function Block({ title, children }: { title: string; children: ReactNode }) {
  return <section className="space-y-3 border-t border-line pt-4" data-kit-data-block={title}>
    <h2 className="text-small font-semibold text-muted-foreground">{title}</h2>
    {children}
  </section>;
}

const TRIPLES: Array<{ label: string; p: Record<"bearish" | "neutral" | "bullish", number> }> = [
  { label: "28 / 31 / 41", p: { bearish: 0.28, neutral: 0.31, bullish: 0.41 } },
  { label: "5 / 30 / 65 (a thin down segment)", p: { bearish: 0.05, neutral: 0.3, bullish: 0.65 } },
  { label: "20 / 20 / 20 (does not add to 100: drawn as given)", p: { bearish: 0.2, neutral: 0.2, bullish: 0.2 } },
];

const CLOSES = [100, 101, 99.5, 102, 104, 103, 105.5, 104.8, 107, 108.2, 107.4, 109.9];

/** The market colours' switch (same attribute the settings page writes), so the page can be photographed under red-up too. */
function UpDownSwitch() {
  const [choice, setChoice] = useState<UpdownChoice>(() => storedUpdown());
  useEffect(() => {
    const observer = new MutationObserver(() => setChoice((document.documentElement.dataset.updown as UpdownChoice) || storedUpdown()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-updown"] });
    return () => observer.disconnect();
  }, []);
  const flip = () => { const next: UpdownChoice = choice === "green-up" ? "red-up" : "green-up"; saveUpdown(next); applyUpdown(next); setChoice(next); };
  return <div className="flex items-center gap-3">
    <Button variant="outline" onClick={flip} data-kit="updown-toggle">Switch to {choice === "green-up" ? "red up" : "green up"}</Button>
    <span className="font-mono text-caption text-muted-foreground" data-kit="updown-current">data-updown={choice}</span>
  </div>;
}

export default function DataPage() {
  return <main className="min-h-screen space-y-8 bg-background p-6 text-foreground" data-kit-data>
    <h1 className="text-xl font-semibold">Data components (dev only)</h1>
    <UpDownSwitch />

    <Block title="ProbabilityBar · standard">
      <div className="grid gap-6 md:grid-cols-2" data-kit="bar-standard">
        {TRIPLES.map(item => <div key={item.label} className="space-y-1.5">
          <p className="font-mono text-caption text-muted-foreground">{item.label}</p>
          <ProbabilityBar probabilities={item.p} />
        </div>)}
        <div className="max-w-[220px] space-y-1.5"><p className="font-mono text-caption text-muted-foreground">narrow (220px)</p><ProbabilityBar probabilities={TRIPLES[0].p} /></div>
      </div>
    </Block>

    <Block title="ProbabilityBar · mini (a row's bar; the numbers show on hover or focus)">
      <div className="grid max-w-md gap-4" data-kit="bar-mini">
        {TRIPLES.map(item => <div key={item.label} className="flex flex-wrap items-center gap-x-3 gap-y-1"><span className="w-56 max-w-full shrink-0 font-mono text-caption text-muted-foreground">{item.label}</span><ProbabilityBar probabilities={item.p} size="mini" className="w-40" /></div>)}
      </div>
    </Block>

    <Block title="ProbabilityBar · no probabilities (the model status in words, no empty track)">
      <div className="space-y-2" data-kit="bar-none">
        <ProbabilityBar probabilities={null} status="research_only" />
        <ProbabilityBar probabilities={null} status="experimental_jev" size="mini" />
        <ProbabilityBar probabilities={undefined} />
      </div>
    </Block>

    <Block title="StatTile">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-kit="stat-tiles">
        <StatTile label="Last close" value="248.50" change={signedChange(3.2, { digits: 2 })} footnote="2026-11-12 · +1.30% on the day" />
        <StatTile label="Day change" value="187.20" change={signedChange(-1.45, { digits: 2 })} footnote="down on the day" />
        <StatTile label="Unchanged" value="52.00" change={signedChange(0, { digits: 2 })} footnote="flat" />
        <StatTile label="Materials" value={12} footnote="saved, official and uploaded" />
      </div>
      <p className="flex flex-wrap items-center gap-4 text-body" data-kit="changes">
        <Change {...signedChange(2.31, { digits: 2, suffix: "%" })} /><Change {...signedChange(-1.08, { digits: 2, suffix: "%" })} /><Change {...signedChange(0, { digits: 2, suffix: "%" })} />
        <span className="w-32"><Sparkline closes={CLOSES} label="sample" /></span>
      </p>
    </Block>

    <Block title="StatusBadge">
      <div className="flex flex-wrap items-center gap-2" data-kit="badges">
        <StatusBadge kind="neutral">Neutral</StatusBadge>
        <StatusBadge kind="progress">In progress</StatusBadge>
        <StatusBadge kind="success">Succeeded</StatusBadge>
        <StatusBadge kind="failure">Failed</StatusBadge>
        <StatusBadge kind="opinion">Model opinion</StatusBadge>
        <StatusBadge kind="action">Waiting for you</StatusBadge>
      </div>
    </Block>

    <Block title="OpinionCard">
      <div className="grid gap-4 lg:grid-cols-2" data-kit="opinion-cards">
        <OpinionCard model="gpt-6.1-terra" version="v3" time="Nov 10, 2026" disclaimer>
          <ProbabilityBar probabilities={TRIPLES[0].p} />
          <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-small"><dt className="text-muted-foreground">Target date</dt><dd className="m-0 font-mono">2026-12-31</dd></dl>
          <OpinionFacts><p className="m-0 text-caption text-muted-foreground">Cited fact</p><p className="m-0"><span data-num>Services net sales were $28.8 billion, up 14% year over year.</span></p></OpinionFacts>
        </OpinionCard>
        <OpinionCard model={null} time={null} version={null}>
          <p className="m-0 text-small">A card with no recorded model, time or version leaves them out of the label; no footnote when it carries none.</p>
        </OpinionCard>
      </div>
    </Block>
  </main>;
}
