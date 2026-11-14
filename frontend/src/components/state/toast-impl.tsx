import { useEffect, useState } from "react";
import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon } from "lucide-react";
import { Toaster as Sonner, toast, type ToasterProps } from "sonner";

// This file is the whole of sonner as far as the app is concerned; it is loaded the first time a toast is wanted.

let mounted: () => void = () => {};
/** Resolves once a Toaster is on screen: a toast made before that would have nowhere to go. */
export const toasterReady: Promise<void> = new Promise((resolve) => { mounted = resolve; });

/** The page's resolved theme ("light" | "dark"), read from the root element the theme code sets it on. */
function useTheme(): "light" | "dark" {
  const read = () => document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const [theme, setTheme] = useState<"light" | "dark">(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

/**
 * The toaster (design 4.0, 操作成功): bottom right, one layer above the dialogs (--z-toast).  Colours are the design's surface
 * tokens (the shadcn variables the stock Toaster reads are not defined here); success and failure are the `success` / `danger`
 * tokens on the icon, never the up / down colours.
 */
export default function Toaster(props: ToasterProps) {
  const theme = useTheme();
  useEffect(() => { mounted(); }, []);
  return <Sonner
    theme={theme} position="bottom-right" closeButton={false} visibleToasts={3} gap={8}
    icons={{
      success: <CircleCheckIcon aria-hidden="true" className="size-4 text-success" />,
      info: <InfoIcon aria-hidden="true" className="size-4" />,
      error: <OctagonXIcon aria-hidden="true" className="size-4 text-danger" />,
      loading: <Loader2Icon aria-hidden="true" className="size-4 motion-safe:animate-spin" />,
    }}
    // A modal dialog turns pointer events off for everything outside it (body); a toast above the dialog has to stay usable.
    toastOptions={{ style: { pointerEvents: "auto" }, classNames: { actionButton: "!bg-primary !text-primary-foreground", cancelButton: "!bg-sunken !text-ink" } }}
    style={{
      "--normal-bg": "var(--surface)", "--normal-text": "var(--ink)", "--normal-border": "var(--line)",
      "--border-radius": "var(--radius-md, 8px)", zIndex: "var(--z-toast)", fontSize: "var(--text-small, 14px)",
    } as React.CSSProperties}
    {...props}
  />;
}

export { toast };
