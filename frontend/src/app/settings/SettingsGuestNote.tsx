
/** What the model and notification pages show a guest: one sentence, no form and no request. */
export function SettingsGuestNote({ text }: { text: string }) {
  return <div data-testid="settings-guest-note" className="rounded-md border border-line bg-surface p-4 text-small text-ink-2">{text}</div>;
}
