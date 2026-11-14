import { useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { useLocale } from "./i18n";
import { getChatMode, personalChatLogin, setChatMode } from "./api";
import { paths } from "./routes.mjs";

/** The mode a stored choice restores: null until the reader has picked guest or personal chat once. */
export function storedChatMode(): "guest" | "personal" | null {
  return localStorage.getItem("market-evidence-agent:chat-mode:v1") ? getChatMode() : null;
}

// The entry page (moved out of App.tsx; P2.2 replaces it with the login page).  It stands in for any address while
// no mode is chosen, so a deep link survives the login: the reader lands on the page they asked for, and only the
// bare "/" and "/login" go on to the chat.
export function AppEntry({ onMode }: { onMode: (mode: "guest" | "personal") => void }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [code, setCode] = useState(""), [error, setError] = useState("");
  const enter = (mode: "guest" | "personal") => {
    onMode(mode);
    if (pathname === "/" || pathname === paths.login()) navigate(paths.chat(), { replace: true });
  };
  async function login() { try { const credential = await personalChatLogin(code); setChatMode("personal", credential); enter("personal"); } catch { setError("个人登录暂不可用，请检查登录码后重试。"); } }
  return <main className="entry-choice"><p className="eyebrow">FinBot</p><h1>{t("选择聊天模式")}</h1><p>{t("访客与个人聊天记录保存在服务端 PostgreSQL。登录个人账户后即可进行站点操作。")}</p><div><button className="primary-action" onClick={() => { setChatMode("guest"); enter("guest"); }}>{t("继续访客聊天")}</button><label>{t("个人聊天登录码")}<input type="password" value={code} maxLength={256} autoComplete="current-password" onChange={e => setCode(e.target.value)} /></label><button className="secondary-action" disabled={!code} onClick={() => void login()}>{t("登录个人聊天")}</button>{error && <p role="alert">{error}</p>}</div></main>;
}
