import { useEffect, useState } from "react";
import { request } from "./api";

type Call = {
  call_id: string;
  conversation_id: string;
  provider_id: string;
  model: string;
  reserved_cny: string;
  charged_cny: string | null;
  outcome: string | null;
  evidence: string | null;
};
type Operation = { path: string; key: string; body: string };

export function SpeechCosts({
  csrf,
  onExpired,
}: {
  csrf: string;
  onExpired: () => void;
}) {
  const [items, setItems] = useState<Call[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<Call | null>(null);
  const [amount, setAmount] = useState("");
  const [evidence, setEvidence] = useState("");
  const [preview, setPreview] = useState(false);
  const [pending, setPending] = useState<Operation | null>(null);

  async function load(after = "") {
    setLoading(true);
    setError("");
    try {
      const response = await request(
        `speech-calls?after=${encodeURIComponent(after)}`,
      );
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (!response.ok) throw new Error("read");
      const page: { items: Call[]; next_after: string | null } =
        await response.json();
      setItems((previous) =>
        after ? [...previous, ...page.items] : page.items,
      );
      setNext(page.next_after);
    } catch {
      setError("无法读取语音费用，请刷新重试。");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  function choose(item: Call) {
    setSelected(item);
    setAmount("");
    setEvidence("");
    setPreview(false);
    setNotice("");
  }
  async function perform(operation: Operation) {
    setBusy(true);
    setError("");
    setPending(operation);
    try {
      const response = await request(operation.path, {
        method: "POST",
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
        setSelected(null);
        setPreview(false);
        await load();
        setError(
          response.status === 409
            ? "调用状态已变化，请核对当前记录后再操作。"
            : "核对被拒绝，请刷新后检查输入和会话。",
        );
        return;
      }
      if (!response.ok) throw new Error("write");
      setPending(null);
      setSelected(null);
      setPreview(false);
      await load();
      setNotice("费用已核对");
    } catch {
      setError("无法确认核对结果，请重试原核对。");
    } finally {
      setBusy(false);
    }
  }
  const locked = busy || loading || pending !== null;
  return (
    <section
      className="conversation-controls speech-costs"
      aria-label="语音费用核对"
      aria-busy={busy || loading}
    >
      <h2>语音费用核对</h2>
      <p>
        依据供应商账单登记实际人民币费用。未知费用保留预留；确认后不能覆盖。
      </p>
      {loading && <p role="status">正在读取语音费用…</p>}
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
          重试原核对
        </button>
      )}
      {notice && <p role="status">{notice}</p>}
      {!loading && !error && items.length === 0 && <p>暂无语音调用记录。</p>}
      <ul className="conversation-list">
        {items.map((item) => (
          <li key={item.call_id}>
            <div>
              <strong>{item.call_id}</strong>
              <span>
                {item.conversation_id} · {item.provider_id} / {item.model}
              </span>
              <span>
                预留 ¥{item.reserved_cny} ·{" "}
                {item.outcome === "confirmed"
                  ? "平台已接收"
                  : item.outcome === "expired"
                    ? "回合已过期"
                    : item.outcome === "superseded"
                      ? "已被新回合替代"
                      : "结果待核查"}
              </span>
              <span>
                {item.charged_cny === null
                  ? "费用未知"
                  : `${item.evidence ? "已核对" : "已知费用"} ¥${item.charged_cny}`}
              </span>
              {item.evidence && <span>{item.evidence}</span>}
            </div>
            {item.charged_cny === null && (
              <button
                className="secondary"
                disabled={locked || !!error}
                onClick={() => choose(item)}
              >
                核对此笔费用
              </button>
            )}
          </li>
        ))}
      </ul>
      {selected && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setPreview(true);
          }}
        >
          <h3>核对 {selected.call_id}</h3>
          <label>
            实际费用（人民币）
            <input
              inputMode="decimal"
              required
              pattern="[0-9]{1,14}(\.[0-9]{1,6})?"
              value={amount}
              disabled={locked || preview}
              onChange={(event) => setAmount(event.target.value)}
            />
          </label>
          <label>
            核对凭据
            <textarea
              required
              maxLength={1000}
              value={evidence}
              disabled={locked || preview}
              onChange={(event) => setEvidence(event.target.value)}
            />
          </label>
          {preview ? (
            <div className="speech-preview">
              <p>确认金额：¥{amount}</p>
              <p>{evidence}</p>
              <p>仅在凭据确认未收费时登记 0。提交后不能覆盖已确认金额。</p>
              <div className="conversation-actions">
                <button
                  disabled={locked}
                  type="button"
                  onClick={() =>
                    void perform({
                      path: `speech-calls/${encodeURIComponent(selected.call_id)}/reconcile`,
                      key: crypto.randomUUID(),
                      body: JSON.stringify({
                        charged_cny: amount,
                        evidence: evidence.trim(),
                      }),
                    })
                  }
                >
                  确认登记费用
                </button>
                <button
                  className="secondary"
                  type="button"
                  disabled={locked}
                  onClick={() => setPreview(false)}
                >
                  返回修改
                </button>
              </div>
            </div>
          ) : (
            <button disabled={locked || !evidence.trim()} type="submit">
              预览核对
            </button>
          )}
        </form>
      )}
      <div className="conversation-actions">
        <button
          className="secondary"
          disabled={locked}
          onClick={() => {
            setSelected(null);
            void load();
          }}
        >
          刷新费用
        </button>
        {next && (
          <button
            className="secondary"
            disabled={locked}
            onClick={() => void load(next)}
          >
            加载更多费用
          </button>
        )}
      </div>
    </section>
  );
}
