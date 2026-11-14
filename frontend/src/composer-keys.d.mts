export type KeyLike = { key: string; shiftKey?: boolean; isComposing?: boolean; keyCode?: number };
export type ComposerKeyAction = "menu-next" | "menu-previous" | "menu-pick" | "menu-close" | "send" | "none";
export function isImeKey(event: Pick<KeyLike, "isComposing" | "keyCode">, composing?: boolean): boolean;
export function composerKeyAction(event: KeyLike, state: { composing: boolean; menuCount: number }): ComposerKeyAction;
