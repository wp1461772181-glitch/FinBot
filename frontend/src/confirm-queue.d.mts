export type ConfirmOptions = {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "default";
  /** Press and hold to confirm: for what cannot be undone. */
  hold?: boolean;
  /** Where focus goes back to; defaults to the element that had it when the ask was made. */
  returnFocus?: HTMLElement | null;
};
export type ConfirmAsk = ConfirmOptions & { id: number };
export function createConfirmQueue(): {
  ask(options: ConfirmOptions): Promise<boolean>;
  getSnapshot(): ConfirmAsk | null;
  subscribe(listener: () => void): () => void;
  answer(value: boolean): void;
  attachHost(on: boolean): void;
  size(): number;
};
