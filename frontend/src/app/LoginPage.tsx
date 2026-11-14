import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { personalChatLogin, setChatMode } from "../api";
import { friendlyError } from "../AgentChatPanel";
import { BrandLogo } from "../BotOrb";
import { BOT_AVATAR_SIZE } from "../bot-sizes.mjs";
import { useLocale } from "../i18n";
import { LiveBotOrb } from "../LiveBotOrb";
import { DEFAULT_AVATAR } from "../orb.mjs";
import { paths } from "../routes.mjs";

/** FinBot's own look on this page: the round, ink-black body (the default bot's). */
const FINBOT_LOOK = { shape: "cercle", color: "encre" };

/**
 * The login page (design 4.1, D3).  One centred card: FinBot's Bloub, large, its eyes following the pointer; the
 * login-code field with its error right under it; 登录; and, below, the quieter way in, 只读浏览.  The robot
 * illustration stays here as a small brand mark (D5).  It stands in for any address while no mode is chosen, so a deep
 * link survives the login (the reader lands on the page they asked for); only the bare "/" and "/login" go on to the chat.
 */
export default function LoginPage({ onMode }: { onMode: (mode: "guest" | "personal") => void }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const enter = (mode: "guest" | "personal") => {
    onMode(mode);
    if (pathname === "/" || pathname === paths.login()) navigate(paths.chat(), { replace: true });
  };
  async function login(event: FormEvent) {
    event.preventDefault();
    if (!code || busy) return;
    setBusy(true); setError("");
    try {
      const credential = await personalChatLogin(code);
      setChatMode("personal", credential);
      enter("personal");
    } catch (failure) {
      setError(failure instanceof Error && failure.message && failure.message !== "个人登录暂不可用。" ? friendlyError(failure.message, t) : t("个人登录暂不可用，请检查登录码后重试。"));
      setBusy(false);
    }
  }
  return <main className="grid min-h-dvh place-items-center bg-background p-4">
    <section aria-labelledby="login-title" className="relative flex w-full max-w-sm flex-col items-center gap-5 rounded-md border border-line bg-surface px-6 py-8">
      <span aria-hidden="true" className="absolute top-4 left-4 origin-top-left scale-75"><BrandLogo /></span>
      <LiveBotOrb avatar={DEFAULT_AVATAR} look={FINBOT_LOOK} name="FinBot" seed="FinBot" size={BOT_AVATAR_SIZE.login} chatState="idle" messages={[]} />
      <div className="text-center">
        <h1 id="login-title" className="text-title-m text-ink">FinBot</h1>
        <p className="text-small text-muted-foreground">{t("理财助手")}</p>
      </div>
      <form className="grid w-full gap-3" onSubmit={login}>
        <label className="grid gap-1.5 text-small text-ink-2">
          {t("个人聊天登录码")}
          <Input type="password" value={code} maxLength={256} autoComplete="current-password" autoFocus aria-invalid={error ? true : undefined} aria-describedby={error ? "login-error" : undefined}
            onChange={event => { setCode(event.target.value); setError(""); }} />
        </label>
        {error && <p id="login-error" role="alert" className="text-small text-danger">{error}</p>}
        <Button type="submit" disabled={!code || busy}>{t(busy ? "正在登录…" : "登录")}</Button>
      </form>
      <Button type="button" variant="link" className="h-auto p-0 text-small" onClick={() => { setChatMode("guest"); enter("guest"); }}>{t("只读浏览")}</Button>
    </section>
  </main>;
}
