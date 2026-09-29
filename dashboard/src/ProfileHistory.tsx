import { useEffect, useState } from "react";
import { request } from "./api";
import { type Profile } from "./profile";
import { ProfileDiff } from "./ProfileDiff";

type Release = { version: number; profile: Profile };
type Entry = { version: number; name: string; created_at: string };
export function ProfileHistory({
  current,
  disabled,
  onExpired,
  onRollback,
}: {
  current: Release | null;
  disabled: boolean;
  onExpired: () => void;
  onRollback: (version: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Entry[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selectionRequest, setSelectionRequest] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [release, setRelease] = useState<Release | null>(null);
  async function load(before?: number) {
    if (busy) return;
    setOpen(true);
    setBusy(true);
    setError("");
    try {
      const response = await request(
        `profile/releases${before ? `?before=${before}` : ""}`,
      );
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (!response.ok) throw new Error("history");
      const data = (await response.json()) as {
        items: Entry[];
        next_before: number | null;
      };
      setItems((old) => (before ? [...old, ...data.items] : data.items));
      setNext(data.next_before);
    } catch {
      setError("无法读取历史版本，请重试。");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (selected === null) return;
    let active = true;
    async function read() {
      try {
        const response = await request(`profile/releases/${selected}`);
        if (!active) return;
        if (response.status === 401) {
          onExpired();
          return;
        }
        if (!response.ok) throw new Error("release");
        const data = (await response.json()) as Release;
        if (active) setRelease(data);
      } catch {
        if (active) setError("无法读取此版本，请重新选择。");
      }
    }
    void read();
    return () => {
      active = false;
    };
  }, [selected, selectionRequest]);
  return (
    <section className="profile-history" aria-label="发布历史">
      <h3>发布历史</h3>
      <p>选择版本查看差异。回滚会创建新发布，保留已保存草稿。</p>
      <button
        type="button"
        className="secondary"
        disabled={busy}
        onClick={() => void load()}
      >
        查看历史版本
      </button>
      {busy && <p role="status">正在读取历史…</p>}
      {open && !busy && items.length === 0 && !error && <p>暂无发布记录。</p>}
      <ul className="release-list">
        {items.map((item) => (
          <li key={item.version}>
            <button
              type="button"
              className="secondary"
              aria-pressed={selected === item.version}
              onClick={() => {
                setRelease(null);
                setError("");
                setSelected(item.version);
                setSelectionRequest((value) => value + 1);
              }}
            >
              查看版本 {item.version}
            </button>
            <span>{item.name}</span>
            <time dateTime={item.created_at}>
              {new Date(item.created_at).toLocaleString()}
            </time>
          </li>
        ))}
      </ul>
      {next && (
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => void load(next)}
        >
          加载更早版本
        </button>
      )}
      {selected !== null && !release && !error && (
        <p role="status">正在读取版本 {selected}…</p>
      )}
      {release && (
        <section aria-label="回滚预览" className="profile-diff">
          <h3>版本 {release.version} 回滚预览</h3>
          <ProfileDiff
            before={current?.profile ?? null}
            after={release.profile}
            afterLabel={`版本 ${release.version}`}
          />
          <p>将生成新的发布版本，当前草稿保持不变。未保存修改时请先保存。</p>
          <button
            type="button"
            disabled={disabled || current?.version === release.version}
            onClick={() => onRollback(release.version)}
          >
            回滚到版本 {release.version}
          </button>
        </section>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </section>
  );
}
