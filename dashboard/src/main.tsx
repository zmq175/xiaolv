import { useEffect, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { request } from "./api";
import { SpeechCosts } from "./SpeechCosts";
import { ConversationControls } from "./ConversationControls";
import { ProfileEditor } from "./ProfileEditor";

function messageFor(status: number): string {
  if (status === 401) return "密码不正确，请重新输入。";
  if (status === 429) return "尝试次数过多，请稍后再试。";
  if (status === 403) return "无法验证此次请求，请刷新页面后重试。";
  return "服务暂时不可用，请稍后重试。";
}

async function sessionToken(response: Response): Promise<string> {
  const value: unknown = await response.json();
  if (
    typeof value === "object" &&
    value !== null &&
    "authenticated" in value &&
    value.authenticated === true &&
    "csrf_token" in value &&
    typeof value.csrf_token === "string" &&
    value.csrf_token
  ) {
    return value.csrf_token;
  }
  throw new Error("invalid_session");
}

function App() {
  const [checking, setChecking] = useState(true);
  const [sessionFailed, setSessionFailed] = useState(false);
  const [csrf, setCsrf] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function check() {
      try {
        const response = await request("session");
        const token = response.ok ? await sessionToken(response) : null;
        if (!mounted) return;
        if (response.status !== 401 && !response.ok) {
          setError(messageFor(response.status));
          setSessionFailed(true);
        }
        setCsrf(token);
      } catch {
        if (mounted) {
          setError("连接失败，请重试。");
          setSessionFailed(true);
        }
      } finally {
        if (mounted) setChecking(false);
      }
    }
    void check();
    return () => {
      mounted = false;
    };
  }, []);

  async function login(event: FormEvent) {
    event.preventDefault();
    if (submitting || !password) return;
    setSubmitting(true);
    setError("");
    const submitted = password;
    setPassword("");
    try {
      const response = await request("login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: submitted }),
      });
      if (!response.ok) {
        setError(messageFor(response.status));
        return;
      }
      setCsrf(await sessionToken(response));
    } catch {
      setError("连接失败，请重试。");
    } finally {
      setSubmitting(false);
    }
  }

  async function logout() {
    if (submitting || !csrf) return;
    setSubmitting(true);
    setError("");
    try {
      const response = await request("logout", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf },
      });
      if (response.ok || response.status === 401) setCsrf(null);
      else setError(messageFor(response.status));
    } catch {
      setError("连接失败，无法确认退出结果。请重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <header className="topbar">
        <span className="brand">
          <span className="mark" aria-hidden="true" />
          机器人管理
        </span>
        <span className="scope">管理员入口</span>
      </header>
      <main className={csrf ? "workspace" : undefined}>
        <section className="access" aria-busy={checking || submitting}>
          <div className="accent" aria-hidden="true" />
          {checking ? (
            <>
              <h1>正在检查登录状态</h1>
              <p role="status">请稍候…</p>
            </>
          ) : sessionFailed ? (
            <>
              <h1>暂时无法连接</h1>
              <p role="alert" className="error">
                {error}
              </p>
              <button onClick={() => window.location.reload()}>重新连接</button>
            </>
          ) : csrf ? (
            <>
              <span className="eyebrow">当前会话</span>
              <h1>已登录管理台</h1>
              <p className="description">管理员身份已验证。</p>
              <div className="session-status">
                <span aria-hidden="true" className="status-dot" />
                会话有效
              </div>
              {error && (
                <p role="alert" className="error">
                  {error}
                </p>
              )}
              <button
                className="secondary"
                disabled={submitting}
                onClick={() => void logout()}
              >
                {submitting ? "正在退出…" : "退出登录"}
              </button>
            </>
          ) : (
            <>
              <span className="eyebrow">欢迎回来</span>
              <h1>登录管理台</h1>
              <p className="description">使用管理员密码继续。</p>
              <form onSubmit={(event) => void login(event)}>
                <label htmlFor="password">管理员密码</label>
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  maxLength={1024}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={submitting}
                  autoFocus
                  aria-describedby={error ? "login-error" : undefined}
                />
                {error && (
                  <p id="login-error" role="alert" className="error">
                    {error}
                  </p>
                )}
                <button type="submit" disabled={submitting || !password}>
                  {submitting ? "正在登录…" : "登录"}
                </button>
              </form>
            </>
          )}
        </section>
        {csrf && (
          <ConversationControls csrf={csrf} onExpired={() => setCsrf(null)} />
        )}
        {csrf && <SpeechCosts csrf={csrf} onExpired={() => setCsrf(null)} />}
        {csrf && <ProfileEditor csrf={csrf} onExpired={() => setCsrf(null)} />}
        <footer>管理员访问 · 会话验证</footer>
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
