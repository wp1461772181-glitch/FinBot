// Developer-only sample page of the nine states (design 4.0), at #/dev/kit/states: one live demo per row of the table, so the
// screenshot and smoke tools can drive them.  It is its own address (like /dev/kit/probe) so the screenshots of /dev/kit stay put.
// Never reachable from the UI; the route in app/router.tsx only loads it when import.meta.env.DEV or VITE_DEV_KIT=1.
// The page is outside the shell, so it mounts the hosts the shell would (offline banner, toaster, confirm dialog, login dialog).
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmHost } from "@/components/state/ConfirmHost";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { NotifyHost } from "@/components/state/NotifyHost";
import { OfflineBanner } from "@/components/state/OfflineBanner";
import { DelayedSkeleton, SkeletonCard, SkeletonMessages, SkeletonRows, SkeletonTable } from "@/components/state/Skeleton";
import { StatefulButton, type ButtonPhase } from "@/components/state/StatefulButton";
import { TaskBar, TaskRow } from "@/components/state/TaskBar";
import { confirm } from "@/components/state/confirm";
import { connectivity } from "@/components/state/connectivity-store";
import { notify } from "@/components/state/notify";
import { tasks } from "@/components/state/tasks";
import { LoginDialog } from "../app/shell/LoginDialog";
import { openLoginDialog } from "../app/shell/login-events";

function Row({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return <section className="space-y-3 border-t border-line pt-4" data-kit-state={n}>
    <h2 className="text-sm font-semibold text-muted-foreground">{n}. {title}</h2>
    {children}
  </section>;
}

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

/** 1. Loading: every skeleton shape now, and the 400ms rule with a quick and a slow "request". */
function Loading() {
  const [mode, setMode] = useState<"idle" | "fast" | "slow">("idle");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const run = (next: "fast" | "slow") => { window.clearTimeout(timer.current); setMode(next); timer.current = window.setTimeout(() => setMode("idle"), next === "fast" ? 200 : 1500); };
  return <Row n={1} title="Loading: skeletons, shown only after 400ms">
    <div className="grid gap-4 md:grid-cols-2" data-kit="skeleton-shapes">
      <DelayedSkeleton delay={0}><SkeletonRows rows={3} /></DelayedSkeleton>
      <DelayedSkeleton delay={0}><SkeletonCard /></DelayedSkeleton>
      <DelayedSkeleton delay={0}><SkeletonTable rows={3} cols={4} /></DelayedSkeleton>
      <DelayedSkeleton delay={0}><SkeletonMessages /></DelayedSkeleton>
    </div>
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="outline" data-kit="skeleton-show-now" onClick={() => { window.clearTimeout(timer.current); setMode("slow"); }}>Show now</Button>
      <Button variant="outline" data-kit="skeleton-fast" onClick={() => run("fast")}>Quick load (200ms)</Button>
      <Button variant="outline" data-kit="skeleton-slow" onClick={() => run("slow")}>Slow load (1.5s, skeleton after 400ms)</Button>
      <Button variant="ghost" onClick={() => { window.clearTimeout(timer.current); setMode("idle"); }}>Reset</Button>
    </div>
    <div className="min-h-24 rounded-md border border-dashed border-line p-3" data-kit="skeleton-stage" data-mode={mode}>
      {mode === "idle" ? <p className="text-sm text-muted-foreground">Content</p> : <DelayedSkeleton><SkeletonRows rows={2} /></DelayedSkeleton>}
    </div>
  </Row>;
}

function Empty() {
  const [added, setAdded] = useState(false);
  return <Row n={2} title="Empty">
    <EmptyState title="还没有自选公司" description="加入一个代码后，它的预测和材料会出现在这里。" action={{ label: "添加公司", onClick: () => setAdded(true) }} />
    {added && <p className="text-sm text-muted-foreground" data-kit="empty-acted">Action pressed</p>}
  </Row>;
}

function Errors() {
  const [tries, setTries] = useState(0);
  return <Row n={3} title="Local error: reason, retry, optional go-to-settings">
    <ErrorBar error={new Error("provider_rate_or_quota_error")} onRetry={() => setTries((n) => n + 1)} settings />
    <ErrorBar error={new TypeError("Failed to fetch")} onRetry={() => setTries((n) => n + 1)} />
    <p className="text-sm text-muted-foreground" data-kit="error-tries">Retries: {tries}</p>
  </Row>;
}

function Offline() {
  return <Row n={4} title="Backend unreachable: one banner at the top of the page">
    <div className="flex flex-wrap gap-3">
      <Button variant="outline" data-kit="offline-on" onClick={() => connectivity.report("down", { reason: "demo" })}>Light the banner</Button>
      <Button variant="outline" data-kit="offline-off" onClick={() => connectivity.report("up")}>Put it out</Button>
    </div>
  </Row>;
}

function Toasts() {
  return <Row n={5} title="Success toast: bottom right, 2 seconds; undo when the action can be undone">
    <div className="flex flex-wrap gap-3">
      <Button variant="outline" data-kit="toast-success" onClick={() => notify.success("已保存")}>Saved</Button>
      <Button variant="outline" data-kit="toast-undo" onClick={() => notify.success("已删除这一笔记录", { undo: { label: "撤销", onClick: () => notify.info("已撤销") } })}>Deleted, with undo</Button>
      <Button variant="outline" data-kit="toast-pinned" onClick={() => notify.success("已删除这一笔记录", { undo: { label: "撤销", onClick: () => {} }, duration: Infinity })}>Pinned (stays, for the screenshot)</Button>
      <Button variant="outline" data-kit="toast-error" onClick={() => notify.error("保存失败，请重试")}>Failed</Button>
      <Button variant="outline" data-kit="toast-promise" onClick={() => { void notify.promise(wait(1200), { loading: "正在保存", success: "已保存", error: "保存失败" }); }}>Promise</Button>
    </div>
  </Row>;
}

function Buttons() {
  const [phase, setPhase] = useState<ButtonPhase>("idle");
  const cycle = () => { setPhase("loading"); window.setTimeout(() => setPhase("success"), 900); window.setTimeout(() => setPhase("idle"), 2400); };
  return <Row n={6} title="In progress: the button carries it (spinner, then check or cross)">
    <div className="flex flex-wrap items-center gap-3">
      <StatefulButton data-kit="stateful-ok" onClick={() => wait(900)}>保存</StatefulButton>
      <StatefulButton data-kit="stateful-fail" variant="outline" onClick={async () => { await wait(900); throw new Error("nope"); }}>测试并保存</StatefulButton>
      <StatefulButton data-kit="stateful-controlled" variant="secondary" phase={phase} onClick={cycle}>扫描 SEC</StatefulButton>
      <StatefulButton data-phase-static="success" phase="success" variant="outline">保存</StatefulButton>
      <StatefulButton data-phase-static="error" phase="error" variant="outline">保存</StatefulButton>
      <StatefulButton data-phase-static="loading" phase="loading" variant="outline">保存</StatefulButton>
    </div>
  </Row>;
}

function Confirms() {
  const [last, setLast] = useState("none");
  return <Row n={7} title="Destructive confirmation: ordinary, and press-and-hold for what cannot be undone">
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="outline" data-kit="confirm-plain" onClick={async () => setLast((await confirm({ title: "归档这条对话？", description: "归档后它不再出现在最近对话里，可以在历史对话里找回。", confirmLabel: "归档" })) ? "confirmed" : "cancelled")}>Ordinary confirm</Button>
      <Button variant="outline" data-kit="confirm-hold" onClick={async () => setLast((await confirm({ title: "删除这一笔记录？", description: "持仓和可用资金会按剩下的记录重新计算。", confirmLabel: "删除", tone: "danger", hold: true })) ? "confirmed" : "cancelled")}><Trash2 /> Hold to confirm</Button>
      <span className="text-sm text-muted-foreground" data-kit="confirm-result">Last answer: {last}</span>
    </div>
  </Row>;
}

function LongTasks() {
  const start = () => {
    const handle = tasks.start({ label: "扫描 SEC", stage: "读取申报列表" });
    window.setTimeout(() => handle.setStage("解析正文"), 2000);
    window.setTimeout(() => handle.done("SEC 扫描完成"), 5000);
  };
  return <Row n={8} title="Long task: stage and elapsed time; the end comes as a toast">
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="outline" data-kit="task-start" onClick={start}>Start a 5s task</Button>
      <Button variant="outline" data-kit="task-start-long" onClick={() => { tasks.start({ id: "demo-long", label: "历史回放", stage: "第 3 / 12 个决策日" }); }}>Start one that stays</Button>
      <Button variant="ghost" onClick={() => tasks.finish("demo-long", { ok: true, message: "历史回放完成" })}>Finish it</Button>
    </div>
    <TaskBar className="max-w-xl" />
    <ul className="max-w-xl" data-kit="task-static" aria-label="Static sample"><TaskRow label="扫描 SEC" stage="解析正文" elapsedMs={65000} /></ul>
  </Row>;
}

function Login() {
  return <Row n={9} title="Login needed: the one global dialog (opens above nothing else; the toaster stays above it)">
    <Button variant="outline" data-kit="login-open" onClick={() => openLoginDialog(true)}>Open the login dialog</Button>
  </Row>;
}

/** Bare-looking markup of the three components that end up inside old pages, for the scope probe. */
function LegacyIsland() {
  return <div data-legacy="" data-probe="state-island" className="space-y-3">
    <ErrorBar message="示例错误" onRetry={() => {}} />
    <EmptyState title="示例空状态" action={{ label: "示例操作", onClick: () => {} }} />
    <StatefulButton>示例按钮</StatefulButton>
  </div>;
}

export default function StatesPage() {
  return <main className="min-h-screen bg-background text-foreground" data-kit-page data-kit-states>
    <OfflineBanner />
    <div className="space-y-8 p-6">
      <h1 className="text-xl font-semibold">States (dev only)</h1>
      <Loading /><Empty /><Errors /><Offline /><Toasts /><Buttons /><Confirms /><LongTasks /><Login />
      <section className="space-y-3 border-t border-line pt-4" data-kit-section="Old-page island">
        <h2 className="text-sm font-semibold text-muted-foreground">The same three components inside an old page (data-legacy) and outside it</h2>
        <div data-probe="state-outside" className="space-y-3">
          <ErrorBar message="示例错误" onRetry={() => {}} />
          <EmptyState title="示例空状态" action={{ label: "示例操作", onClick: () => {} }} />
          <StatefulButton>示例按钮</StatefulButton>
        </div>
        <LegacyIsland />
      </section>
    </div>
    <ConfirmHost />
    <NotifyHost />
    <LoginDialog onModeChange={() => {}} />
  </main>;
}
