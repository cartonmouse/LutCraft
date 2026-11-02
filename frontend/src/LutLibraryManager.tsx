import { useEffect, useState } from "react";
import { api, post } from "./api";
import type { Lut, LutCandidate, LutMetadata, LutProfile, LutSearchResult } from "./types";

const spaces = { unknown: "使用条件待确认", confirmed: "已确认适用于 sRGB", incompatible: "不适用于当前处理流程" };
const sources: Record<string, string> = { file: "导入资料", publisher: "发布方资料", measured: "标准样本测量", ai: "AI 建议", user: "人工填写" };
const fields: Record<string, string> = { description: "描述", tags: "标签", compatibility: "使用条件", publisher: "作者", source_page: "来源", license_note: "许可" };

export function LutCandidates({ result, disabled, onPreview }: {
  result?: LutSearchResult | null; disabled: boolean;
  onPreview: (result: LutSearchResult, candidate: LutCandidate, strength: number) => void;
}) {
  const [strengths, setStrengths] = useState<Record<string, number>>({});
  if (!result) return null;
  return <section className="lut-search-results" aria-label="LUT 风格候选">
    <div className="section-label"><strong>风格候选</strong><span>{result.mode === "hybrid" ? "语义与关键词" : "关键词与同义词"}</span></div>
    <p className="muted">{result.query}</p>
    {result.message && <p role="status" className="lut-search-note">{result.message}</p>}
    <div className="lut-candidate-grid">{result.candidates.slice(0, 3).map((c, i) => {
      const key = result.search_id + c.id;
      const strength = strengths[key] ?? c.recommended_strength ?? c.trial_strength;
      return <article key={key} className="lut-candidate">
        <small>{i === 0 ? "首选候选" : `备选 ${i}`}</small><strong>{c.name}</strong>
        <p>{c.description || "尚未填写效果描述，请检查预览。"}</p>
        <p className="muted">{c.reasons.join(" · ")}</p>
        {!!c.conflicts.length && <p className="inline-warning">可能偏离需求：{c.conflicts.join("、")}</p>}
        <label>{c.recommended_strength === null ? "试用强度" : "建议强度"} {Math.round(strength * 100)}%
          <input aria-label={`${c.name} 试用强度`} type="range" min="0" max="1" step="0.05" value={strength}
            onChange={(e) => setStrengths((s) => ({ ...s, [key]: Number(e.target.value) }))} /></label>
        {c.strength_basis && <small>{c.strength_basis}</small>}
        <button className="button small" disabled={disabled} onClick={() => onPreview(result, c, strength)}>生成这款预览</button>
      </article>;
    })}</div>
    {!!result.candidates.length && <p className="muted">预览后由你确认应用，匹配理由不代表实际效果已验证。</p>}
  </section>;
}

export function LutLibraryManager({ luts, projectId, busy, canApply, onRefresh, onChoose, onPreview }: {
  luts: Lut[]; projectId?: string; busy: boolean; canApply: boolean;
  onRefresh: () => Promise<void>; onChoose: (id: string) => void;
  onPreview: (result: LutSearchResult, candidate: LutCandidate, strength: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<LutSearchResult | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  useEffect(() => { setResult(null); }, [projectId]);
  const pending = luts.some((l) => ["queued", "running"].includes(l.profile?.job?.status || ""));
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => { void onRefresh().catch(() => {}); }, 1800);
    return () => window.clearInterval(timer);
  }, [pending, onRefresh]);
  async function task(fn: () => Promise<void>) {
    setWorking(true); setError("");
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "操作失败。"); }
    finally { setWorking(false); }
  }
  return <div className="lut-manager">
    <form className="lut-search-form" onSubmit={(e) => { e.preventDefault(); void task(async () => {
      const found = await post<LutSearchResult>("/luts/search", { query, project_id: projectId || null });
      setResult(found); await onRefresh();
    }); }}>
      <label htmlFor="lut-style-query">按你想要的风格找 LUT</label>
      <div><input id="lut-style-query" value={query} maxLength={500} placeholder="例如：日式小清新，但不要太黄" onChange={(e) => setQuery(e.target.value)} />
        <button className="button primary" disabled={busy || working || !query.trim()}>查找风格</button></div>
    </form>
    {error && <p className="inline-warning" role="alert">{error}</p>}
    <LutCandidates result={result} disabled={busy || working || !canApply} onPreview={onPreview} />
    {!!luts.length && <button className="text-button" disabled={busy || working || pending} onClick={() => void task(async () => {
      for (const lut of luts.filter((l) => l.profile?.compatibility === "confirmed" && l.profile.enabled)) await post(`/luts/${lut.id}/analyze`);
      await onRefresh();
    })}>为可用 LUT 分析效果并建立索引</button>}
    <div className="library-list">{luts.map((l) => <article className="lut-managed-row" key={l.id}>
      <div className="library-row"><div><strong>{l.name}</strong><small>{l.grid_size}³ · {(l.byte_size / 1024).toFixed(0)} KB · {spaces[l.profile?.compatibility || "unknown"]}</small></div>
        <div className="library-actions"><button className="button small" disabled={busy || !canApply || !l.profile?.enabled || l.profile.compatibility !== "confirmed"} onClick={() => onChoose(l.id)}>选择并调节</button>
          <button className="button small" onClick={() => setEditing(editing === l.id ? null : l.id)}>管理元信息</button></div></div>
      {l.profile?.metadata.description && <p>{l.profile.metadata.description}</p>}
      <div className="lut-tags">{l.profile?.metadata.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
      <small>{!l.profile?.enabled ? "已停用 · " : ""}{l.profile?.index_status === "ready" ? "语义索引就绪" : l.profile?.index_status === "unconfigured" ? "关键词可用 · Embedding 待配置" : "语义索引待建立"}
        {pending && ["queued", "running"].includes(l.profile?.job?.status || "") ? " · 正在分析/建索引" : ""}</small>
      {l.profile?.job?.error && <p className="inline-warning">{l.profile.job.error}</p>}
      {editing === l.id && <MetadataEditor key={l.id} id={l.id} disabled={busy || working} onSaved={onRefresh} />}
    </article>)}</div>
  </div>;
}

function MetadataEditor({ id, disabled, onSaved }: { id: string; disabled: boolean; onSaved: () => Promise<void> }) {
  const [profile, setProfile] = useState<LutProfile | null>(null);
  const [metadata, setMetadata] = useState<LutMetadata | null>(null);
  const [compatibility, setCompatibility] = useState<LutProfile["compatibility"]>("unknown");
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  async function load() {
    const p = await api<LutProfile>(`/luts/${id}/metadata`);
    setProfile(p); setMetadata(p.metadata); setCompatibility(p.compatibility); setEnabled(!!p.enabled);
  }
  useEffect(() => { void load().catch((e) => setError(e.message)); }, [id]);
  async function perform(fn: () => Promise<void>) {
    setSaving(true); setError("");
    try { await fn(); await load(); await onSaved(); }
    catch (e) { setError(e instanceof Error ? e.message : "保存失败。"); }
    finally { setSaving(false); }
  }
  if (!profile || !metadata) return <p role="status">{error || "正在读取元信息…"}</p>;
  const update = (patch: Partial<LutMetadata>) => setMetadata({ ...metadata, ...patch });
  const blocked = disabled || saving;
  return <form className="lut-metadata-editor" onSubmit={(e) => { e.preventDefault(); void perform(async () => {
    const cleaned = { ...metadata, tags: metadata.tags.map((s) => s.trim()).filter(Boolean), aliases: metadata.aliases.map((s) => s.trim()).filter(Boolean), use_cases: metadata.use_cases.map((s) => s.trim()).filter(Boolean) };
    const changed = Object.fromEntries(Object.entries(cleaned).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(profile.metadata[k as keyof LutMetadata])));
    await api(`/luts/${id}/metadata`, { method: "PATCH", body: JSON.stringify({ revision: profile.revision, metadata: changed, compatibility, enabled }) });
  }); }}>
    <label>效果描述<textarea value={metadata.description} maxLength={1200} onChange={(e) => update({ description: e.target.value })} /></label>
    <div className="lut-field-grid">
      <label>标签（逗号分隔）<input value={metadata.tags.join(",")} onChange={(e) => update({ tags: e.target.value.split(/[,，]/) })} /></label>
      <label>别名（逗号分隔）<input value={metadata.aliases.join(",")} onChange={(e) => update({ aliases: e.target.value.split(/[,，]/) })} /></label>
      <label>分类<input maxLength={80} value={metadata.category} onChange={(e) => update({ category: e.target.value })} /></label>
      <label>作者 / 发布方<input maxLength={160} value={metadata.publisher} onChange={(e) => update({ publisher: e.target.value })} /></label>
    </div>
    <label>来源链接<input maxLength={1000} value={metadata.source_page} onChange={(e) => update({ source_page: e.target.value })} /></label>
    <label>使用条件<select value={compatibility} onChange={(e) => {
      const next = e.target.value as LutProfile["compatibility"]; setCompatibility(next);
      if (next === "confirmed") update({ input_space: "srgb", output_space: "srgb" });
    }}>{Object.entries(spaces).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
    <label>使用条件的确认依据<textarea maxLength={800} value={metadata.compatibility_basis} placeholder="例如：作者说明链接及输入/输出要求" onChange={(e) => update({ compatibility_basis: e.target.value })} /></label>
    <label>注意事项<textarea maxLength={800} value={metadata.cautions} onChange={(e) => update({ cautions: e.target.value })} /></label>
    <label>已验证的适用场景（逗号分隔）<input value={metadata.use_cases.join(",")} placeholder="只填写有样张或来源依据的场景" onChange={(e) => update({ use_cases: e.target.value.split(/[,，]/) })} /></label>
    <details><summary>许可与建议强度</summary>
      <label>许可说明<textarea maxLength={1200} value={metadata.license_note} onChange={(e) => update({ license_note: e.target.value })} /></label>
      <label>建议强度（0–100%，无依据可留空）<input type="number" min="0" max="100" value={metadata.recommended_strength === null ? "" : Math.round(metadata.recommended_strength * 100)} onChange={(e) => update({ recommended_strength: e.target.value === "" ? null : Number(e.target.value) / 100 })} /></label>
      <label>强度建议依据<input maxLength={500} value={metadata.strength_basis} onChange={(e) => update({ strength_basis: e.target.value })} /></label>
    </details>
    <label className="srgb-check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />启用此 LUT</label>
    <div className="library-actions"><button className="button primary" disabled={blocked}>保存元信息</button>
      <button className="button" type="button" disabled={blocked} onClick={() => void perform(async () => { await post(`/luts/${id}/analyze`); })}>重新分析与建索引</button>
      <button className="text-button" type="button" disabled={blocked} onClick={() => void perform(async () => {})}>重新加载</button></div>
    {error && <p role="alert" className="inline-warning">{error}</p>}
    {!!Object.keys(profile.suggestions).length && <div className="lut-suggestion"><strong>待审核建议</strong><p>{profile.suggestions.description}</p><p>{profile.suggestions.tags?.join("、")}</p>
      <p className="muted">接受建议会替换对应字段；系统保留它来自导入资料或标准样本测量的记录。</p>
      {(["description", "tags"] as const).filter((key) => profile.suggestions[key] !== undefined).map((key) => <button key={key} type="button" className="button small" disabled={blocked} onClick={() => void perform(async () => {
        await api(`/luts/${id}/metadata`, { method: "PATCH", body: JSON.stringify({ revision: profile.revision, accept_suggestions: [key] }) });
      })}>接受{key === "description" ? "描述" : "标签"}建议</button>)}
    </div>}
    <details><summary>查看信息来源</summary><dl>{Object.entries(fields).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{sources[profile.evidence[key]?.source || ""] || "尚无记录"} · {profile.evidence[key]?.review === "accepted" ? "已接受" : "来源声明 / 待核对"}</dd></div>)}</dl></details>
  </form>;
}
