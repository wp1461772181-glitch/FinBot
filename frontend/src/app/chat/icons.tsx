// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { type ReactNode } from "react";

function Icon({ children }: { children: ReactNode }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}
export const CopyIcon = () => <Icon><rect x="9" y="9" width="11" height="11" rx="2.5" /><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15" /></Icon>;
export const CheckIcon = () => <Icon><path d="M5 12.5l4.5 4.5L19 7.5" /></Icon>;
export const ThumbUpIcon = () => <Icon><path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3z" /><path d="M7 11l4-7a2 2 0 0 1 2 2v3h5.2a2 2 0 0 1 2 2.3l-1.1 7A2 2 0 0 1 17.1 20H7" /></Icon>;
export const ThumbDownIcon = () => <Icon><path d="M17 13V4h3a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-3z" /><path d="M17 13l-4 7a2 2 0 0 1-2-2v-3H5.8a2 2 0 0 1-2-2.3l1.1-7A2 2 0 0 1 6.9 4H17" /></Icon>;
export const PencilIcon = () => <Icon><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3z" /><path d="M13.5 6.5l3 3" /></Icon>;
export const ArchiveIcon = () => <Icon><path d="M4 5h16v3H4V5z" /><path d="M5.5 8v10.5a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5V8" /><path d="M9.5 12h5" /></Icon>;
export const SendIcon = () => <Icon><path d="M12 19V5" /><path d="M5.5 11.5L12 5l6.5 6.5" /></Icon>;
