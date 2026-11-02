import { useRef, useState } from "react";
import { Upload, FolderOpen, Palette, Trash2, Pencil } from "lucide-react";
import type { Lut, PersonalPreset, LutCandidate, LutSearchResult } from "./types";
import { selectLutFiles, type LutImportItem, type LutImportStatus, type LutImportOptions } from "./lutImport";
import { LutLibraryManager } from "./LutLibraryManager";

const importLabels: Record<LutImportStatus, string> = {
  queued: "待导入", uploading: "正在导入…", imported: "已导入", existing: "已存在 · 已跳过", failed: "导入失败",
};

export function LibraryPanel({ luts, presets, busy, canApply, available, imports, onSelectFiles, onImport, onChooseLut, onApply, onRename, onDelete, projectId, onRefresh, onCandidatePreview }: {
  luts: Lut[]; presets: PersonalPreset[]; busy: boolean; canApply: boolean; available: boolean;
  imports: LutImportItem[]; onSelectFiles: (items: LutImportItem[]) => void;
  onImport: (options: LutImportOptions) => Promise<boolean>; onChooseLut: (id: string) => void;
  projectId?: string; onRefresh: () => Promise<void>;
  onCandidatePreview: (result: LutSearchResult, candidate: LutCandidate, strength: number) => void;
  onApply: (id: string) => void; onRename: (preset: PersonalPreset, name: string) => Promise<boolean>;
  onDelete: (id: string) => Promise<boolean>;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const [selectionMessage, setSelectionMessage] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const [srgb, setSrgb] = useState(false);
  const [publisher, setPublisher] = useState("");
  const [sourcePage, setSourcePage] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const count = (status: LutImportStatus) => imports.filter((item) => item.status === status).length;
  const completed = count("imported") + count("existing") + count("failed");
  const remaining = count("queued") + count("failed");
  const importing = imports.some((item) => item.status === "uploading");
  function selectFiles(files: FileList | null) {
    if (!files?.length) return;
    setSelectionError("");
    setSelectionMessage("");
    setSrgb(false);
    onSelectFiles([]);
    try {
      const { items, ignored } = selectLutFiles(Array.from(files));
      onSelectFiles(items);
      setSrgb(false);
      setSelectionMessage(`已选择 ${items.length} 个 LUT，匹配 ${items.filter((i) => i.metadataFile).length} 份元信息${ignored ? `（其余文件不作为 LUT 上传）` : ""}。`);
    } catch (error) {
      setSelectionError(error instanceof Error ? error.message : "文件选择失败。");
    }
  }
  return <div className="library-sections">
    <section className="library-section">
      <div className="section-label"><Upload size={17} /><strong>我的 LUT</strong><span>{luts.length} 个</span></div>
      <p className="muted">批量导入照片用 .cube，支持 13 / 17 / 32 / 33 / 65 网格。每批最多 50 个、共 100 MB，单个不超过 10 MB。</p>
      <form className="lut-import" onSubmit={async (e) => { e.preventDefault(); if (remaining && !busy) await onImport({ color_space: srgb ? "srgb" : "unknown", publisher, source_page: sourcePage }); }}>
        <input ref={fileInput} hidden type="file" multiple aria-label="批量选择 cube 文件" accept=".cube" disabled={busy || !available}
          onChange={(e) => { selectFiles(e.target.files); e.target.value = ""; }} />
        <input ref={(node) => { folderInput.current = node; node?.setAttribute("webkitdirectory", ""); }} hidden type="file" multiple aria-label="选择 LUT 文件夹" disabled={busy || !available}
          onChange={(e) => { selectFiles(e.target.files); e.target.value = ""; }} />
        <div className="lut-import-pickers">
          <button type="button" className="button" disabled={busy || !available} onClick={() => fileInput.current?.click()}><Upload size={16} />选择多个文件</button>
          <button type="button" className="button" disabled={busy || !available} onClick={() => folderInput.current?.click()}><FolderOpen size={16} />选择文件夹</button>
        </div>
        <p className="lut-import-hint">已有项目素材：选择 lut-library 下的 luts 文件夹，会查找各风格子目录中的 .cube；无需选择 _sources 原始下载包或预览图片。</p>
        {selectionMessage && <p className="lut-import-hint" role="status">{selectionMessage}</p>}
        {selectionError && <p className="inline-warning" role="alert">{selectionError}</p>}
        <label className="srgb-check"><input type="checkbox" checked={srgb} disabled={busy} onChange={(e) => setSrgb(e.target.checked)} />根据提供方说明，所选 LUT 适用于 sRGB 照片，不是 Log / HDR 转换</label>
        <p className="lut-import-hint">未确认时先保存为“使用条件待确认”，补充依据后才可用于调色。文件夹中的 metadata.json 会按目录匹配。</p>
        <details><summary>批量填写公共信息（可选）</summary>
          <label>作者 / 发布方<input value={publisher} maxLength={160} onChange={(e) => setPublisher(e.target.value)} /></label>
          <label>来源链接<input value={sourcePage} maxLength={1000} onChange={(e) => setSourcePage(e.target.value)} /></label>
        </details>
        <button type="submit" className="button primary" disabled={busy || !available || !remaining}>
          {importing ? `正在导入 ${completed + 1} / ${imports.length}` : imports.length && !remaining ? "导入完成" : count("failed") && !count("queued") ? `重试失败项（${count("failed")}）` : `开始批量导入${remaining ? `（${remaining}）` : ""}`}
        </button>
        {!!imports.length && <div className="lut-import-results">
          <div className="lut-import-summary" role="status" aria-live="polite">已处理 {completed} / {imports.length} · 新增 {count("imported")} · 已存在 {count("existing")} · 失败 {count("failed")}</div>
          <progress aria-label="LUT 导入进度" value={completed} max={imports.length} />
          <ul aria-label="LUT 导入结果">{imports.map((item, index) => <li key={index} className={`lut-import-item ${item.status}`}>
            <div><strong>{item.name || item.file.name}</strong><small>{item.file.webkitRelativePath || item.file.name}</small>{item.error && <p>{item.error}</p>}</div>
            <span>{importLabels[item.status]}</span>
          </li>)}</ul>
          <p className="lut-import-hint">相同内容自动跳过；失败项可单独重试。导入后在下方点击“选择并调节”，生成照片预览。</p>
        </div>}
      </form>
      {!available && <p className="inline-warning">LUT 引擎未就绪，请运行环境安装脚本后重启。</p>}
      <LutLibraryManager luts={luts} projectId={projectId} busy={busy} canApply={canApply && available}
        onRefresh={onRefresh} onChoose={onChooseLut} onPreview={onCandidatePreview} />
      {!luts.length && <p className="library-empty">还没有 LUT。导入后可在各影集中主动选用。</p>}
    </section>
    <section className="library-section">
      <div className="section-label"><Palette size={17} /><strong>个人预设</strong><span>{presets.length} 个</span></div>
      <p className="muted">在工作区保存某张照片的已应用效果。预设包含基础参数、LUT 与强度；选择后先预览。</p>
      <div className="library-list">{presets.map((p) => <div className="library-row" key={p.id}>
        {editing === p.id ? <form className="rename-form" onSubmit={async (e) => { e.preventDefault(); if (await onRename(p, name)) setEditing(null); }}>
          <input aria-label="新的预设名称" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="button small" disabled={busy || !name.trim()}>保存名称</button>
          <button type="button" className="text-button" onClick={() => setEditing(null)}>取消</button>
        </form> : <><div className="library-description"><strong>{p.name}</strong><small>{p.recipe.lut ? `${p.recipe.lut.name} · ${Math.round(p.recipe.lut.strength * 100)}%` : "基础调色 · 无 LUT"}</small></div>
          <div className="library-actions"><button className="button small" disabled={busy || !canApply || (!!p.recipe.lut && !available)} onClick={() => onApply(p.id)}>预览应用</button>
          <button className="icon-button" aria-label={`改名 ${p.name}`} disabled={busy} onClick={() => { setEditing(p.id); setName(p.name); }}><Pencil size={15} /></button>
          <button className="icon-button" aria-label={`删除 ${p.name}`} disabled={busy} onClick={() => void onDelete(p.id)}><Trash2 size={15} /></button></div></>}
      </div>)}</div>
      {!presets.length && <p className="library-empty">将喜欢的效果保存为个人预设，下个影集即可复用。</p>}
      <p className="panel-footnote">仅当前浏览器会话可见。删除预设不会改变照片与历史批次；项目偏好仍分别保存。</p>
    </section>
  </div>;
}

export function SavePreset({ ordinal, disabled, hasPending, onSave }: {
  ordinal?: number; disabled: boolean; hasPending: boolean; onSave: (name: string) => Promise<boolean>;
}) {
  const [name, setName] = useState("");
  return <form className="save-preset" onSubmit={async (e) => { e.preventDefault(); if (await onSave(name)) setName(""); }}>
    <label htmlFor="preset-name">保存第 {ordinal ?? "—"} 张的已应用效果</label>
    <input id="preset-name" placeholder="给个人预设起个名字" maxLength={80} value={name} disabled={disabled} onChange={(e) => setName(e.target.value)} />
    <button className="button full" type="submit" disabled={disabled || hasPending || !name.trim()}>保存个人预设</button>
    {hasPending && <p className="panel-footnote">请先生成并应用预览，或放弃待确认方案，再保存效果。</p>}
  </form>;
}
