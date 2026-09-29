import { useEffect, useState, type FormEvent } from "react";
import { request } from "./api";
import { labels, type Profile } from "./profile";
import { ProfileDiff } from "./ProfileDiff";
import { ProfileHistory } from "./ProfileHistory";

type State = {
  version: number;
  draft: Profile | null;
  published: { version: number; profile: Profile } | null;
};
const empty: Profile = {
  name: "",
  aliases: [],
  personality: "",
  participation_style: "",
  reply_style: "",
};
type Field = keyof Profile;
type Operation = {
  action: "draft" | "publish" | "rollback";
  key: string;
  body: string;
};

export function ProfileEditor({
  csrf,
  onExpired,
}: {
  csrf: string;
  onExpired: () => void;
}) {
  const [state, setState] = useState<State | null>(null);
  const [form, setForm] = useState<Profile>(empty);
  const [aliases, setAliases] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionInvalid, setSessionInvalid] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<Operation | null>(null);
  const locked = busy || pending !== null || conflict || sessionInvalid;
  const [invalid, setInvalid] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const value = {
    ...form,
    aliases: aliases
      .split("\n")
      .map((v) => v.trim())
      .filter(Boolean),
  };
  const dirty = JSON.stringify(value) !== JSON.stringify(state?.draft ?? empty);

  function apply(next: State) {
    setConflict(false);
    setState(next);
    setForm(next.draft ?? empty);
    setAliases((next.draft ?? empty).aliases.join("\n"));
  }
  async function load() {
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const response = await request("profile");
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (!response.ok) throw new Error("load");
      apply((await response.json()) as State);
    } catch {
      setError("无法读取资料，请重试。");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function mutate(
    action: "draft" | "publish" | "rollback",
    releaseVersion?: number,
  ) {
    if (locked || !state) return;
    await perform({
      action,
      key: crypto.randomUUID(),
      body: JSON.stringify({
        expected_version: state.version,
        ...(action === "draft" ? { profile: value } : {}),
        ...(action === "rollback" ? { release_version: releaseVersion } : {}),
      }),
    });
  }

  async function perform(operation: Operation, retry = false) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    setInvalid([]);
    try {
      const response = await request(`profile/${operation.action}`, {
        method: operation.action === "draft" ? "PUT" : "POST",
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
      if (response.status === 403) {
        setPending(null);
        setSessionInvalid(true);
        setError("无法验证此次请求，请刷新登录状态后重试。");
        return;
      }
      if (response.status === 422) {
        const detail = (await response.json()) as {
          errors?: { loc: unknown[] }[];
        };
        const fields = (detail.errors ?? []).flatMap((issue) =>
          issue.loc.filter(
            (part): part is string =>
              typeof part === "string" && Object.hasOwn(labels, part),
          ),
        );
        setInvalid(fields);
        setPending(null);
        setError("请检查标记的字段，修改后重新保存。");
        return;
      }
      if (response.status === 409) {
        setPending(null);
        setConflict(true);
        setError(
          "资料已被其他页面修改。本地内容已保留，请核对后加载最新资料。",
        );
        return;
      }
      if (!response.ok) throw new Error("write");
      let next = (await response.json()) as State;
      if (retry) {
        const current = await request("profile");
        if (current.status === 401) {
          onExpired();
          return;
        }
        if (!current.ok) throw new Error("refresh");
        next = (await current.json()) as State;
      }
      apply(next);
      setPending(null);
      setNotice(
        operation.action === "draft"
          ? "草稿已保存"
          : "发布已提交，后续回合将读取新版本。",
      );
    } catch {
      setPending(operation);
      setError("结果尚未确认。请重试原操作，避免重复提交。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="profile-editor" aria-busy={loading || busy}>
      <div className="editor-heading">
        <div>
          <h2>机器人资料</h2>
          <p>定义它的名字、个性和说话习惯。</p>
        </div>
      </div>
      {loading ? (
        <p role="status">正在读取资料…</p>
      ) : (
        state && (
          <>
            <div className="publication-state">
              <strong>
                {state.published
                  ? `已发布版本 ${state.published.version}`
                  : "尚未发布人设"}
              </strong>
              <p>保存仅更新草稿；发布后，后续聊天回合读取新版本。</p>
            </div>
            <form
              onSubmit={(event: FormEvent) => {
                event.preventDefault();
                void mutate("draft");
              }}
            >
              {(Object.keys(labels) as Field[]).map((field) => (
                <div className="profile-field" key={field}>
                  <label htmlFor={`profile-${field}`}>{labels[field]}</label>
                  {field === "name" ? (
                    <input
                      id={`profile-${field}`}
                      aria-invalid={invalid.includes(field)}
                      aria-describedby={
                        invalid.includes(field) ? `error-${field}` : undefined
                      }
                      value={form.name}
                      maxLength={64}
                      required
                      disabled={locked}
                      onChange={(event) => {
                        setNotice("");
                        setForm({ ...form, name: event.target.value });
                      }}
                    />
                  ) : (
                    <textarea
                      id={`profile-${field}`}
                      aria-invalid={invalid.includes(field)}
                      aria-describedby={
                        invalid.includes(field) ? `error-${field}` : undefined
                      }
                      rows={field === "personality" ? 4 : 2}
                      disabled={locked}
                      maxLength={
                        field === "aliases"
                          ? 2079
                          : field === "personality"
                            ? 2000
                            : 1000
                      }
                      value={field === "aliases" ? aliases : form[field]}
                      onChange={(event) => {
                        setNotice("");
                        field === "aliases"
                          ? setAliases(event.target.value)
                          : setForm({ ...form, [field]: event.target.value });
                      }}
                    />
                  )}
                  {invalid.includes(field) && (
                    <p className="error" id={`error-${field}`}>
                      {labels[field]}不符合要求，请检查长度或数量。
                    </p>
                  )}
                  {field === "aliases" && <small>每行一个，最多 32 个。</small>}
                </div>
              ))}
              <p className="edit-status">
                {dirty
                  ? "有未保存的修改，请先保存草稿。"
                  : state.draft
                    ? "当前显示已保存草稿。"
                    : "填写资料后保存草稿。"}
              </p>
              <div className="editor-actions">
                <button
                  type="submit"
                  disabled={locked || !dirty || !form.name.trim()}
                >
                  保存草稿
                </button>
                <button
                  className="secondary"
                  type="button"
                  disabled={locked || dirty || !state.draft}
                  onClick={() => void mutate("publish")}
                >
                  发布草稿
                </button>
              </div>
            </form>
            {state.draft && (
              <section aria-label="发布差异" className="profile-diff">
                <h3>发布差异</h3>
                <p>比较已保存草稿与当前发布；未保存修改不包含在内。</p>
                <ProfileDiff
                  before={state.published?.profile ?? null}
                  after={state.draft}
                  afterLabel="已保存草稿"
                />
              </section>
            )}
            <ProfileHistory
              key={state.published?.version ?? 0}
              current={state.published}
              disabled={locked || dirty}
              onExpired={onExpired}
              onRollback={(version) => void mutate("rollback", version)}
            />
          </>
        )
      )}
      {!state && !loading && (
        <button className="secondary" onClick={() => void load()}>
          重新读取资料
        </button>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {sessionInvalid && (
        <button className="secondary" onClick={() => window.location.reload()}>
          刷新登录状态（放弃未保存内容）
        </button>
      )}
      {conflict && (
        <button
          className="secondary"
          disabled={loading}
          onClick={() => void load()}
        >
          放弃本地修改并加载最新资料
        </button>
      )}
      {pending && (
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void perform(pending, true)}
        >
          重试原操作
        </button>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
