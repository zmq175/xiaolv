import { labels, type Profile } from "./profile";

export function ProfileDiff({
  before,
  after,
  afterLabel,
}: {
  before: Profile | null;
  after: Profile;
  afterLabel: string;
}) {
  const fields = (Object.keys(labels) as (keyof Profile)[]).filter(
    (field) =>
      !before || JSON.stringify(before[field]) !== JSON.stringify(after[field]),
  );
  const display = (value: string | string[]) =>
    (Array.isArray(value) ? value.join("\n") : value) || "（空）";
  return (
    <>
      {!before && <p>首次发布，目前没有已发布资料。</p>}
      {fields.length === 0 ? (
        <p>内容与当前发布一致。</p>
      ) : (
        fields.map((field) => (
          <div className="diff-field" key={field}>
            <h4>{labels[field]}</h4>
            <div className="diff-columns">
              <div>
                <small>当前发布</small>
                <pre>{before ? display(before[field]) : "（尚未发布）"}</pre>
              </div>
              <div>
                <small>{afterLabel}</small>
                <pre>{display(after[field])}</pre>
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}
