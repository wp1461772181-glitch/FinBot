import { useEffect, useRef, useState, type ComponentProps, type MouseEvent } from "react";
import { Check, LoaderCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLocale } from "../../i18n";

export type ButtonPhase = "idle" | "loading" | "success" | "error";

/**
 * A button that carries its own progress (design 4.0, 操作进行中): the label stays, and a spinner takes its place while the
 * work runs, then a check or a cross (colours: `success` / `danger` tokens, not the up / down colours), then it is a button
 * again.  No second line of text, no change of width.  Drive it either way:
 *   · `onClick` returns a promise: loading until it settles, success when it resolves, error when it rejects;
 *   · `phase` is given: the button shows it (controlled).
 * While loading the button ignores presses but keeps focus (aria-disabled, not disabled).  A screen reader hears the phase.
 */
export function StatefulButton({ phase: controlled, onClick, onError, resetAfter = 1600, children, className, ...props }: Omit<ComponentProps<typeof Button>, "onClick"> & {
  phase?: ButtonPhase;
  onClick?: (event: MouseEvent<HTMLButtonElement>) => unknown;
  onError?: (error: unknown) => void;
  /** ms the check or cross stays before the button is idle again. */
  resetAfter?: number;
}) {
  const { t } = useLocale();
  const [own, setOwn] = useState<ButtonPhase>("idle");
  const alive = useRef(true);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => { alive.current = true; return () => { alive.current = false; window.clearTimeout(timer.current); }; }, []);
  const phase = controlled ?? own;
  const settle = (next: ButtonPhase) => {
    if (!alive.current) return;
    setOwn(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { if (alive.current) setOwn("idle"); }, resetAfter);
  };
  const press = (event: MouseEvent<HTMLButtonElement>) => {
    if (phase === "loading") { event.preventDefault(); return; }
    const result = onClick?.(event);
    if (result && typeof (result as Promise<unknown>).then === "function") {
      window.clearTimeout(timer.current);
      setOwn("loading");
      (result as Promise<unknown>).then(() => settle("success"), (error) => { settle("error"); onError?.(error); });
    }
  };
  const spoken = phase === "loading" ? t("处理中") : phase === "success" ? t("已完成") : phase === "error" ? t("没有成功") : "";
  return <Button {...props} data-phase={phase} aria-disabled={phase === "loading" || props["aria-disabled"] || undefined} aria-busy={phase === "loading"} onClick={press} className={`relative ${className ?? ""}`}>
    <span className="contents" style={phase === "idle" ? undefined : { visibility: "hidden" }}>{children}</span>
    {phase !== "idle" && <span aria-hidden="true" className="absolute inset-0 grid place-items-center">
      {phase === "loading" && <LoaderCircle className="size-4 motion-safe:animate-spin" />}
      {phase === "success" && <span className="grid size-5 place-items-center rounded-full bg-success text-background"><Check className="size-3.5" strokeWidth={3} /></span>}
      {phase === "error" && <span className="grid size-5 place-items-center rounded-full bg-danger text-background"><X className="size-3.5" strokeWidth={3} /></span>}
    </span>}
    <span role="status" className="sr-only">{spoken}</span>
  </Button>;
}
