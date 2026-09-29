import { useEffect, useState } from "react";
import { request } from "./api";

type Conversation = {
  conversation_id: string;
  enabled: boolean;
  version: number;
};
type Operation = { path: string; key: string; body: string };
type Page = { items: Conversation[]; next_after: string | null };

export function ConversationControls({
  csrf,
  onExpired,
}: {
  csrf: string;
  onExpired: () => void;
}) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState<Operation | null>(null);
  async function load(after = "") {
    setLoading(true);
    setError("");
    try {
      const response = await request(
        `conversations?after=${encodeURIComponent(after)}`,
      );
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (!response.ok) throw new Error("read");
      const page: Page = await response.json();
      setItems((previous) =>
        after ? [...previous, ...page.items] : page.items,
      );
      setNext(page.next_after);
    } catch {
      setError("无法读取会话，请重试。");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function toggle(item: Conversation) {
    if (busy || loading || pending || error) return;
    await perform({
      path: `conversations/${encodeURIComponent(item.conversation_id)}`,
      key: crypto.randomUUID(),
      body: JSON.stringify({
        enabled: !item.enabled,
        expected_version: item.version,
      }),
    });
  }
  async function perform(operation: Operation) {
    setBusy(true);
    setError("");
    setNotice("");
    setPending(operation);
    try {
      const response = await request(operation.path, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
          "Idempotency-Key": operation.key,
        },
        body: operation.body,
      });
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (response.status >= 400 && response.status < 500) {
        setPending(null);
        setError(
          response.status === 409
            ? "会话设置已被修改，请刷新会话后再操作。"
            : "操作被拒绝，请刷新页面后重试。",
        );
        return;
      }
      if (!response.ok) throw new Error("write");
      setPending(null);
      await load();
      setNotice("原操作已确认，列表显示当前会话设置。");
    } catch {
      setError("无法确认操作结果，请重试原操作。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="conversation-controls"
      aria-label="会话管理"
      aria-busy={busy || loading}
    >
      <h2>会话管理</h2>
      <p>控制已登记会话是否允许回复。停用后，旧回复不会在恢复时补发。</p>
      <p className="hint">
        清单不代表实时在线状态。已经发往平台的消息可能仍会送达。
      </p>
      {loading && <p role="status">正在读取会话…</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {pending && (
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void perform(pending)}
        >
          重试原操作
        </button>
      )}
      {notice && <p role="status">{notice}</p>}
      {!loading && items.length === 0 && !error && (
        <p>暂无已登记会话。聊天服务启动后会登记已配置的群和私聊。</p>
      )}
      <ul className="conversation-list">
        {items.map((item) => (
          <li key={item.conversation_id}>
            <div>
              <strong>{item.conversation_id}</strong>
              <span>{item.enabled ? "已启用" : "已停用"}</span>
            </div>
            <button
              className="secondary"
              disabled={busy || loading || pending !== null || !!error}
              onClick={() => void toggle(item)}
            >
              {item.enabled ? "停用" : "恢复"}
            </button>
          </li>
        ))}
      </ul>
      <div className="conversation-actions">
        <button
          className="secondary"
          disabled={busy || loading || pending !== null}
          onClick={() => void load()}
        >
          刷新会话
        </button>
        {next && (
          <button
            className="secondary"
            disabled={busy || loading || pending !== null}
            onClick={() => void load(next)}
          >
            加载更多会话
          </button>
        )}
      </div>
    </section>
  );
}
