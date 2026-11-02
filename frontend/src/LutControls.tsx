import type { Lut, LutAction, Recipe } from "./types";

export function LutControls({ luts, recipes, draft, disabled, available, onChange, onLibrary }: {
  luts: Lut[]; recipes: Recipe[]; draft: LutAction | null;
  disabled: boolean; available: boolean; onChange: (value: LutAction) => void; onLibrary: () => void;
}) {
  const ids = new Set(recipes.map((r) => r.lut?.id || ""));
  const mixed = ids.size > 1;
  const current = recipes[0]?.lut;
  const selected = draft?.op === "select" ? draft.id : draft?.op === "clear" ? "" : mixed ? "mixed" : current?.id || "";
  const strengths = new Set(recipes.map((r) => r.lut?.strength ?? 1));
  const mixedStrength = !draft && !mixed && strengths.size > 1;
  const strength = draft && draft.op !== "clear" ? draft.strength : current?.strength ?? 1;
  return <div className="lut-controls">
    <div className="small-label"><strong>LUT 风格</strong><button className="text-button" onClick={onLibrary}>导入 / 管理</button></div>
    <select aria-label="选择 LUT" value={selected} disabled={disabled} onChange={(e) => onChange(e.target.value ? { op: "select", id: e.target.value, strength: 1 } : { op: "clear" })}>
      <option value="">不使用 LUT</option>
      {mixed && <option value="mixed" disabled>多个 LUT · 请统一选择</option>}
      {luts.map((l) => <option value={l.id} key={l.id} disabled={!available}>{l.name}</option>)}
    </select>
    <label className="lut-strength"><span>LUT 强度 <output>{mixedStrength ? "各张不同" : `${Math.round(strength * 100)}%`}</output></span>
      <input type="range" aria-label="LUT 强度" min="0" max="100" step="1" value={Math.round(strength * 100)} disabled={disabled || !available || !selected || selected === "mixed"}
        onChange={(e) => onChange(draft?.op === "select" ? { ...draft, strength: +e.target.value / 100 } : { op: "strength", strength: +e.target.value / 100 })} />
    </label>
    <p className="panel-footnote">0% 保留基础调色。调整后点击生成预览。</p>
    {!available && <p className="inline-warning">LUT 引擎未就绪；仍可关闭 LUT 或恢复原图效果。</p>}
  </div>;
}
