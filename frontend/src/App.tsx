import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUp,
  Check,
  ChevronRight,
  FolderPlus,
  ImagePlus,
  Images,
  Layers3,
  LoaderCircle,
  MessageSquare,
  Palette,
  Plus,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
  Brain,
  PanelLeft,
  CheckCheck,
  Maximize2,
  Minimize2,
} from "lucide-react";
import { api, post, ApiError } from "./api";
import type { Asset, Health, Operation, Project, Recipe, Lut, LutAction, PersonalPreset, LutCandidate, LutSearchResult } from "./types";
import { LutCandidates } from "./LutLibraryManager";
import { LutControls } from "./LutControls";
import { LibraryPanel, SavePreset } from "./LibraryPanel";
import { AgentStatus, isAgentActive } from "./AgentStatus";
import { importLutFiles, type LutImportItem, type LutUploadResult } from "./lutImport";

const labels: Record<string, string> = {
  previewing: "生成预览中",
  ready: "待确认",
  queued: "排队中",
  running: "处理中",
  succeeded: "已完成",
  partial_failed: "部分失败",
  failed: "失败",
  interrupted: "已中断",
  stale: "预览已过期",
  discarded: "已放弃",
  superseded: "已更新",
  planned: "待处理",
};
const controls = [
  ["exposure_ev", "曝光", -2, 2, 0.1, "EV"],
  ["warmth", "冷暖", -1, 1, 0.05, ""],
  ["contrast", "对比度", 0.5, 1.5, 0.05, ""],
  ["saturation", "饱和度", 0, 2, 0.05, ""],
] as const;
const presets = [
  {
    id: "natural",
    name: "自然本色",
    sub: "还原轻盈、真实的日常",
    className: "natural",
  },
  {
    id: "warm",
    name: "暖调时光",
    sub: "柔和暖色，留住温度",
    className: "warm",
  },
  {
    id: "mono",
    name: "经典黑白",
    sub: "收起色彩，留下光影",
    className: "mono",
  },
];
const base: Recipe = {
  schema_version: 2,
  preset_id: "natural",
  exposure_ev: 0,
  warmth: 0,
  contrast: 1,
  saturation: 1,
  lut: null,
};
const ongoing = (op?: Operation) =>
  !!op && ["previewing", "queued", "running"].includes(op.status);

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [tab, setTab] = useState("workspace");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [chatExpanded, setChatExpanded] = useState(false);
  const [split, setSplit] = useState(50);
  const [showPreview, setShowPreview] = useState(true);
  const [manual, setManual] = useState<Recipe>(base);
  const [changedFields, setChangedFields] = useState<string[]>([]);
  const [lutDraft, setLutDraft] = useState<LutAction | null>(null);
  const [blockedPreview, setBlockedPreview] = useState<string | null>(null);
  const [luts, setLuts] = useState<Lut[]>([]);
  const [lutImports, setLutImports] = useState<LutImportItem[]>([]);
  const [personalPresets, setPersonalPresets] = useState<PersonalPreset[]>([]);
  const [preference, setPreference] = useState("");
  const [drag, setDrag] = useState(false);
  const [sidebar, setSidebar] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const chat = useRef<HTMLDivElement>(null);
  const pidRef = useRef<string | null>(null);
  const boot = useRef(false);
  const sendAttempt = useRef<{pid: string; text: string; request_id: string; context_revision: number} | null>(null);
  const agentTurn = project?.agent_turns?.[0];
  const agentWorking = isAgentActive(agentTurn);
  const canChat = !!health?.agent.send_enabled;
  const pending = project?.operations.find((o) =>
    ["ready", "previewing"].includes(o.status),
  );
  const batch = project?.operations.find((o) =>
    ["queued", "running"].includes(o.status),
  );
  const latest = project?.operations[0];
  const chatVersion = project?.messages.map((m) => `${m.id}:${m.content}`).join("|");
  const locked = busy || !!batch || pending?.status === "previewing";
  const viewed =
    project?.assets.find((a) => a.id === project.viewed) || project?.assets[0];
  const sample =
    showPreview && pending?.preview_url
      ? project?.assets.find((a) => a.id === pending.preview_asset_id)
      : undefined;
  const photo = sample || viewed;
  const edited = sample ? pending?.preview_url : photo?.result_url;
  const displayedRecipe =
    (sample
      ? pending?.items.find((i) => i.asset_id === sample.id)?.recipe
      : photo?.recipe) || base;
  const recipeKey = JSON.stringify(displayedRecipe);
  const draftDirty = changedFields.length > 0 || !!lutDraft;
  const previewBlocked = draftDirty || (!!pending && blockedPreview === pending.id);
  const selectedRecipes = project?.assets.filter((a) => project.selected.includes(a.id)).map((a) =>
    pending ? pending.items.find((i) => i.asset_id === a.id)?.recipe || a.recipe : a.recipe) || [];

  function clearDraft() {
    setChangedFields([]);
    setLutDraft(null);
    setBlockedPreview(null);
  }
  function changeLut(value: LutAction) {
    setLutDraft(value);
    if (pending) setBlockedPreview(pending.id);
  }
  async function refreshLibrary() {
    const [ls, ps] = await Promise.all([api<Lut[]>("/luts"), api<PersonalPreset[]>("/personal-presets")]);
    setLuts(ls);
    setPersonalPresets(ps);
  }

  function receive(p: Project) {
    if (pidRef.current === p.id) setProject((current) =>
      current?.id === p.id && current.revision > p.revision ? current : p);
  }
  async function refresh(id = pidRef.current) {
    if (id) receive(await api<Project>("/projects/" + id));
  }
  async function load(id: string) {
    clearDraft();
    pidRef.current = id;
    localStorage.setItem("lut.project", id);
    setShowPreview(true);
    setProject(null);
    receive(await api<Project>("/projects/" + id));
  }
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
      try {
        await refresh();
      } catch {
        /* keep the original error */
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (boot.current) return;
    boot.current = true;
    void action(async () => {
      const h = await api<Health>("/health");
      setHealth(h);
      await refreshLibrary();
      let list = await api<{ id: string; name: string }[]>("/projects");
      if (!list.length) {
        const p = await post<Project>("/projects", { name: "我的第一组照片" });
        list = [p];
      }
      setProjects(list);
      const saved = localStorage.getItem("lut.project");
      await load(list.find((p) => p.id === saved)?.id || list[0].id);
    });
  }, []);
  useEffect(() => {
    setManual(displayedRecipe);
    setChangedFields([]);
    setLutDraft(null);
  }, [recipeKey, photo?.id, project?.id, pending?.id]);
  useEffect(() => {
    setPreference(project?.preferences.style_preference || "");
  }, [project?.preferences.style_preference, project?.id]);
  useEffect(() => {
    chat.current?.scrollTo({
      top: chat.current.scrollHeight,
      behavior: "smooth",
    });
  }, [chatVersion, busy, agentTurn?.status]);
  useEffect(() => {
    setChatExpanded(false);
  }, [tab, project?.id]);
  useEffect(() => {
    if (!chatExpanded) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setChatExpanded(false);
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [chatExpanded]);
  useEffect(() => {
    const timer = setInterval(() => { void api<Health>("/health").then(setHealth).catch(() => {}); }, 15000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!project || !(project.operations.some(ongoing) || project.agent_turns?.some(isAgentActive))) return;
    let dead = false,
      timer: ReturnType<typeof setTimeout>,
      delay = 1000;
    const id = project.id;
    async function poll() {
      try {
        const p = await api<Project>("/projects/" + id);
        if (!dead) {
          receive(p);
          delay = 1000;
          if (p.operations.some(ongoing) || p.agent_turns?.some(isAgentActive)) timer = setTimeout(poll, delay);
        }
      } catch {
        if (!dead) {
          delay = Math.min(delay * 2, 8000);
          timer = setTimeout(poll, delay);
        }
      }
    }
    timer = setTimeout(poll, delay);
    return () => {
      dead = true;
      clearTimeout(timer);
    };
  }, [project?.id, project?.operations.map((o) => o.id + o.status).join(","), agentTurn?.id, agentTurn?.status]);

  async function upload(files: FileList | File[] | null) {
    if (!files || !project) return;
    const picked = Array.from(files);
    if (picked.length + project.assets.length > 10) {
      setError("每个影集最多 10 张照片，请减少文件或新建影集。");
      return;
    }
    await action(async () => {
      const form = new FormData();
      picked.forEach((f) => form.append("files", f));
      const result = await api<{
        files: { name: string; status: string; error?: string }[];
        project: Project;
      }>("/projects/" + project.id + "/assets", { method: "POST", body: form });
      receive(result.project);
      setTab("workspace");
      setShowPreview(false);
      const failed = result.files.filter((f) => f.status === "failed");
      if (failed.length)
        setError(failed.map((f) => f.name + "：" + f.error).join("；"));
      else setNotice(`已导入 ${picked.length} 张照片，可以开始调色。`);
    });
    if (input.current) input.current.value = "";
  }
  async function workspace(selected: string[], viewedId: string | null) {
    if (!project) return;
    await action(async () =>
      receive(
        await api<Project>("/projects/" + project.id + "/workspace", {
          method: "PATCH",
          body: JSON.stringify({
            context_revision: project.revision,
            selected_asset_ids: selected,
            viewed_asset_id: viewedId,
          }),
        }),
      ),
    );
  }
  async function preview(preset?: string, personalId?: string) {
    if (!project) return;
    await action(async () => {
      if (!project.selected.length) throw new Error("请先勾选需要调整的照片。");
      await post("/projects/" + project.id + "/previews", {
        context_revision: project.revision,
        target_asset_ids: project.selected,
        preset_id: preset || null,
        personal_preset_id: personalId || null,
        lut_action: preset || personalId ? null : lutDraft,
        adjustments: preset || personalId
          ? []
          : controls.filter(([field]) => changedFields.includes(field)).map(([field]) => ({
              field,
              op: "set",
              value: manual[field],
            })),
      });
      clearDraft();
      setShowPreview(true);
      setTab("workspace");
      await refresh();
    });
  }
  async function send() {
    if (!project || !text.trim() || !canChat || agentWorking || locked || draftDirty) return;
    const value = text.trim();
    if (!sendAttempt.current || sendAttempt.current.pid !== project.id || sendAttempt.current.text !== value)
      sendAttempt.current = { pid: project.id, text: value, request_id: crypto.randomUUID(), context_revision: project.revision };
    const attempt = sendAttempt.current;
    await action(async () => {
      try {
        await post("/projects/" + attempt.pid + "/instructions", {
          context_revision: attempt.context_revision, request_id: attempt.request_id, text: attempt.text,
        });
      } catch (e) {
        if (e instanceof ApiError && e.status < 500) sendAttempt.current = null;
        throw e;
      }
      sendAttempt.current = null;
      if (pidRef.current === attempt.pid) {
        setText("");
        setShowPreview(true);
        await refresh(attempt.pid);
      }
    });
  }
  async function opAction(op: Operation, verb: string) {
    if (verb === "apply" && previewBlocked) return;
    await action(async () => {
      await post("/operations/" + op.id + "/" + verb);
      clearDraft();
      setShowPreview(true);
      await refresh();
    });
  }
  async function reset() {
    if (!project) return;
    await action(async () => {
      await post("/projects/" + project.id + "/reset-preview", {
        context_revision: project.revision, target_asset_ids: project.selected,
      });
      clearDraft();
      setShowPreview(true);
      setNotice("恢复方案已提交；预览就绪后点击“确认应用”，所选照片才会恢复原图效果。");
      await refresh();
    });
  }
  function candidatePreview(result: LutSearchResult, candidate: LutCandidate, strength: number) {
    if (!project || !project.selected.length || draftDirty) return;
    void action(async () => {
      await post(`/projects/${project.id}/candidate-preview`, {
        search_id: result.search_id, lut_id: candidate.id, strength,
        context_revision: project.revision, target_asset_ids: project.selected,
      });
      clearDraft(); setShowPreview(true); setTab("workspace"); await refresh();
    });
  }
  function chooseTab(id: string) {
    setTab(id);
    setSidebar(false);
  }
  const panelTitle =
    tab === "memory"
      ? "项目记忆"
      : tab === "export"
        ? "导出照片"
        : tab === "presets"
          ? "选择一种心情"
          : "照片工作区";

  return (
    <div className="app">
      <aside className={"sidebar " + (sidebar ? "open" : "")}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            chooseTab("workspace");
          }}
        >
          <span className="brandmark">
            <Layers3 size={25} />
          </span>
          <span>
            LUT<span className="brand-light"> Studio</span>
            <small>让色彩，成为你的语言</small>
          </span>
        </a>
        <div className="nav-caption">工作空间</div>
        <nav>
          {[
            { id: "workspace", name: "照片工作区", Icon: Images },
            { id: "presets", name: "调色预设", Icon: Palette },
            { id: "memory", name: "项目记忆", Icon: Brain },
            { id: "export", name: "导出照片", Icon: ArrowDownToLine },
          ].map(({ id, name, Icon }) => (
            <button
              key={id}
              className={tab === id ? "nav-item active" : "nav-item"}
              onClick={() => chooseTab(id)}
            >
              <Icon size={18} />
              {name}
              {id === "workspace" && (
                <span className="nav-number">
                  {project?.assets.length || 0}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="project-section">
          <div className="nav-caption">当前影集</div>
          <select
            aria-label="切换影集"
            value={project?.id || ""}
            disabled={busy}
            onChange={(e) => void action(() => load(e.target.value))}
          >
            {projects.map((p) => (
              <option value={p.id} key={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            className="new-project"
            disabled={busy}
            onClick={() =>
              void action(async () => {
                const p = await post<Project>("/projects", {
                  name: `我的影集 ${projects.length + 1}`,
                });
                setProjects([p, ...projects]);
                await load(p.id);
              })
            }
          >
            <FolderPlus size={15} />
            新建影集
          </button>
        </div>
        <div className="sidebar-note">
          <span className="tiny-star">✳</span>
          <h4>你的照片，你的风格。</h4>
          <p>
            从一组日常影像开始，
            <br />
            找到属于自己的色彩。
          </p>
        </div>
        <div className="local-status">
          <span className="status-dot" />
          本机工作空间<small>原图与结果保存在本机</small>
        </div>
      </aside>
      <main className={chatExpanded ? "chat-focus" : undefined}>
        <header className="topbar">
          <div>
            <button
              className="mobile-toggle"
              aria-label="打开菜单"
              onClick={() => setSidebar(!sidebar)}
            >
              <PanelLeft size={20} />
            </button>
            <span className="crumb">工作空间</span>
            <ChevronRight size={14} />
            <strong>{project?.name || "正在载入"}</strong>
          </div>
          <span className="saved">
            <Check size={13} />
            项目自动保存
          </span>
        </header>
        <div className="page-heading">
          <div>
            <div className="eyebrow">YOUR COLOR WORKSPACE</div>
            <h1>{panelTitle}</h1>
            <p>
              {tab === "memory"
                ? "保存明确的偏好，让每一次继续调整都有依据。"
                : tab === "export"
                  ? "把喜欢的效果带走。原图始终保留。"
                  : "选好照片，说说你想要的感觉。"}
            </p>
          </div>
          <button
            className="button primary"
            disabled={locked || !project || project.assets.length >= 10}
            onClick={() => input.current?.click()}
          >
            <Plus size={17} />
            导入照片
          </button>
        </div>
        <input
          ref={input}
          type="file"
          accept="image/jpeg,image/png"
          multiple
          hidden
          onChange={(e) => void upload(e.target.files)}
        />
        {error && (
          <div className="alert error" role="alert">
            {error}
            <button aria-label="关闭错误" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {notice && (
          <div className="alert notice" role="status">
            {notice}
            <button aria-label="关闭提示" onClick={() => setNotice("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {!canChat && health && (
          <div className="model-banner">
            <Sparkles size={16} />
            <span>{health.agent.message} · 可先使用预设和参数完成真实调色</span>
            <span className="config-hint">在 .env 配置模型后重启</span>
          </div>
        )}

        <div className="content">
          {tab === "workspace" && (
            <div className="workspace-grid">
              <section className="canvas-card">
                <div className="canvas-toolbar">
                  <div>
                    <Images size={16} />
                    <strong>{project?.assets.length || 0} 张照片</strong>
                    <span className="divider" />
                    <span>已选 {project?.selected.length || 0} 张</span>
                  </div>
                  <button
                    className="text-button"
                    disabled={locked || !project?.assets.length}
                    onClick={() =>
                      project &&
                      void workspace(
                        project.selected.length === project.assets.length
                          ? []
                          : project.assets.map((a) => a.id),
                        project.viewed,
                      )
                    }
                  >
                    <CheckCheck size={15} />
                    {project?.selected.length === project?.assets.length &&
                    !!project?.assets.length
                      ? "取消全选"
                      : "选择全部"}
                  </button>
                </div>
                {!photo ? (
                  <div
                    className={"empty-canvas " + (drag ? "dragging" : "")}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDrag(true);
                    }}
                    onDragLeave={() => setDrag(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setDrag(false);
                      if (!locked) void upload(e.dataTransfer.files);
                    }}
                  >
                    <div className="empty-art">
                      <div className="photo-back" />
                      <div className="photo-front">
                        <ImagePlus size={44} strokeWidth={1} />
                        <span>YOUR NEXT STORY</span>
                      </div>
                    </div>
                    <h2>好照片，值得一种好色调。</h2>
                    <p>
                      把照片拖到这里，或从电脑中选择。
                      <br />
                      统一风格，也保留每张照片的个性。
                    </p>
                    <button
                      className="button primary"
                      disabled={busy || !project}
                      onClick={() => input.current?.click()}
                    >
                      <ImagePlus size={16} />
                      选择照片
                    </button>
                    <small>JPEG / PNG · 最多 10 张 · 每张不超过 10 MB</small>
                  </div>
                ) : (
                  <>
                    <div className="viewer">
                      <img
                        src={photo.original_url}
                        alt={`第 ${photo.ordinal} 张原图`}
                        className="viewer-image"
                      />
                      {edited && (
                        <div
                          className="edited-layer"
                          style={{ clipPath: `inset(0 0 0 ${split}%)` }}
                        >
                          <img
                            src={edited}
                            alt="调整后的照片"
                            className="viewer-image"
                          />
                        </div>
                      )}
                      {edited && (
                        <>
                          <div
                            className="compare-line"
                            style={{ left: `${split}%` }}
                          >
                            <span>↔</span>
                          </div>
                          <input
                            className="compare-range"
                            type="range"
                            min="0"
                            max="100"
                            value={split}
                            aria-label="原图与效果对比"
                            onChange={(e) => setSplit(+e.target.value)}
                          />
                          <span className="image-tag tag-left">原图</span>
                          <span className="image-tag tag-right">
                            {sample ? "待确认预览" : "已应用效果"}
                          </span>
                        </>
                      )}
                      <span className="image-name">
                        {String(photo.ordinal).padStart(2, "0")} / {photo.name}
                      </span>
                    </div>
                    <div className="viewer-caption">
                      <span>
                        {photo.width} × {photo.height}
                        <span className="muted">
                          {" "}
                          · {photo.format.toUpperCase()}
                        </span>
                      </span>
                      <span>
                        {edited ? "拖动分隔线对比效果" : "原图 · 尚未应用调色"}
                      </span>
                    </div>
                    <div className="filmstrip">
                      {project?.assets.map((a) => (
                        <div
                          className={
                            "thumb " + (photo.id === a.id ? "viewed" : "")
                          }
                          key={a.id}
                        >
                          <button
                            className="thumb-image"
                            aria-label={`查看第 ${a.ordinal} 张`}
                            disabled={busy}
                            onClick={() => {
                              setShowPreview(!!pending?.preview_url && a.id === pending.preview_asset_id);
                              void workspace(project.selected, a.id);
                            }}
                          >
                            <img
                              src={a.result_url || a.thumbnail_url}
                              alt={a.name}
                            />
                          </button>
                          <label className="thumb-check">
                            <input
                              type="checkbox"
                              aria-label={`选择第 ${a.ordinal} 张`}
                              checked={project.selected.includes(a.id)}
                              disabled={locked}
                              onChange={(e) =>
                                void workspace(
                                  e.target.checked
                                    ? [...project.selected, a.id]
                                    : project.selected.filter(
                                        (id) => id !== a.id,
                                      ),
                                  project.viewed,
                                )
                              }
                            />
                          </label>
                          <span className="thumb-number">
                            {String(a.ordinal).padStart(2, "0")}
                          </span>
                          {a.result_url && (
                            <span className="thumb-done">
                              <Check size={10} />
                            </span>
                          )}
                        </div>
                      ))}
                      <button
                        className="add-thumb"
                        aria-label="添加照片"
                        disabled={
                          locked || !project || project.assets.length >= 10
                        }
                        onClick={() => input.current?.click()}
                      >
                        <Plus size={22} />
                      </button>
                    </div>
                  </>
                )}
                {pending && (
                  <div className="preview-bar">
                    <div>
                      <span className="preview-dot" />
                      {pending.status === "previewing" ? (
                        <>
                          <LoaderCircle className="spin" size={16} />
                          正在生成预览…
                        </>
                      ) : (
                        <>
                          <strong>{previewBlocked ? "参数已变化，请重新生成预览" : "预览已就绪，尚未应用"}</strong>
                          <span>
                            确认后应用到第{" "}
                            {pending.items.map((i) => i.ordinal).join("、")} 张
                          </span>
                        </>
                      )}
                    </div>
                    <div>
                      {pending.status === "ready" && (
                        <>
                          <button
                            className="text-button"
                            onClick={() => setShowPreview(true)}
                          >
                            查看第 {project?.assets.find((a) => a.id === pending.preview_asset_id)?.ordinal} 张预览
                          </button>
                          <button
                            className="button small"
                            disabled={busy}
                            onClick={() => void opAction(pending, "discard")}
                          >
                            放弃
                          </button>
                          <button
                            className="button primary small"
                            disabled={locked || previewBlocked}
                            onClick={() => void opAction(pending, "apply")}
                          >
                            <Check size={14} />
                            确认应用
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                )}
                {pending?.status === "ready" && <div className="preview-detail">
                  <span>{pending.summary.split("\n")[0]}</span>
                  {pending.items.map((i) => <span key={i.asset_id}>第 {i.ordinal} 张 · 曝光 {i.recipe.exposure_ev.toFixed(1)} · 冷暖 {i.recipe.warmth.toFixed(2)} · 对比 {i.recipe.contrast.toFixed(2)} · 饱和 {i.recipe.saturation.toFixed(2)} · {i.recipe.lut ? `${i.recipe.lut.name} ${Math.round(i.recipe.lut.strength * 100)}%` : "无 LUT"}</span>)}
                </div>}
                {batch && (
                  <div className="batch-bar">
                    <LoaderCircle size={16} className="spin" />
                    <span>
                      {labels[batch.status]} ·{" "}
                      {
                        batch.items.filter((i) => i.status === "succeeded")
                          .length
                      }{" "}
                      / {batch.items.length} 张完成
                    </span>
                    <progress
                      max={batch.items.length}
                      value={
                        batch.items.filter((i) =>
                          ["succeeded", "failed"].includes(i.status),
                        ).length
                      }
                    />
                  </div>
                )}
                {!pending &&
                  !batch &&
                  latest &&
                  ["failed", "partial_failed", "interrupted"].includes(
                    latest.status,
                  ) && (
                    <div className="batch-bar error">
                      <span>
                        {latest.error ||
                          `${labels[latest.status]}，可重新预览失败项。`}
                      </span>
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => void opAction(latest, "retry")}
                      >
                        <RotateCcw size={14} />
                        重试
                      </button>
                    </div>
                  )}
              </section>
              <aside className="adjust-card">
                <div className="adjust-scroll">
                <div className="section-label">
                  <SlidersHorizontal size={16} />
                  <strong>调色配方</strong>
                </div>
                <LutControls luts={luts} recipes={selectedRecipes} draft={lutDraft}
                  disabled={locked || !project?.selected.length} available={!!health?.lut_engine.available}
                  onChange={changeLut} onLibrary={() => setTab("presets")} />
                <details className="quick-presets">
                <summary>内置基础预设</summary>
                <div className="preset-mini">
                  {presets.map((p) => (
                    <button
                      key={p.id}
                      disabled={locked || !project?.selected.length}
                      onClick={() => void preview(p.id)}
                    >
                      <span className={"preset-swatch " + p.className} />
                      <span>{p.name}</span>
                      <ChevronRight size={13} />
                    </button>
                  ))}
                </div>
                <p className="panel-footnote">选择内置预设会重置基础参数并关闭 LUT。</p>
                </details>
                <div className="line" />
                <div className="small-label">
                  细调参数 <span>参考第 {photo?.ordinal || "—"} 张</span>
                </div>
                <p className="panel-footnote">仅修改过的参数应用于所选照片。</p>
                <div className="sliders">
                  {controls.map(([key, label, min, max, step, unit]) => (
                    <label key={key}>
                      <div>
                        <span>{label}</span>
                        <output>
                          {manual[key].toFixed(2)} {unit}
                        </output>
                      </div>
                      <input
                        aria-label={label}
                        type="range"
                        min={min}
                        max={max}
                        step={step}
                        value={manual[key]}
                        disabled={locked}
                        onChange={(e) => {
                          setManual({ ...manual, [key]: +e.target.value });
                          setChangedFields((fields) => [...new Set([...fields, key])]);
                          if (pending) setBlockedPreview(pending.id);
                        }}
                      />
                    </label>
                  ))}
                </div>
                <SavePreset ordinal={viewed?.ordinal} disabled={locked || !viewed} hasPending={!!pending || draftDirty}
                  onSave={(name) => action(async () => {
                    if (!viewed || !project) return;
                    await post("/personal-presets", { name, project_id: project.id, asset_id: viewed.id, asset_revision: viewed.revision });
                    await refreshLibrary();
                    setNotice("已保存个人预设，可在调色预设中管理并跨影集使用。");
                  })} />
                </div>
                <div className="adjust-actions">
                  <button className="button primary full" disabled={locked || !project?.selected.length} onClick={() => void preview()}>
                    <Sparkles size={15} />生成预览
                  </button>
                  <button className="text-button" disabled={locked || !project?.selected.length} onClick={() => void reset()}>
                    <RotateCcw size={14} />恢复原图效果（先预览）
                  </button>
                </div>
              </aside>
            </div>
          )}

          {tab === "presets" && (
            <section className="preset-page">
              <div className="section-label">
                <Palette size={17} />
                <strong>三种起点，无限种感觉</strong>
                <span>选择后生成预览</span>
              </div>
              <div className="preset-grid">
                {presets.map((p) => (
                  <button
                    className="preset-card"
                    key={p.id}
                    disabled={locked || !project?.selected.length}
                    onClick={() => void preview(p.id)}
                  >
                    <div className={"preset-art " + p.className}>
                      <div className="art-sun" />
                      <div className="art-land" />
                      <span>{p.id.toUpperCase()}</span>
                    </div>
                    <div className="preset-info">
                      <div>
                        <h3>{p.name}</h3>
                        <p>{p.sub}</p>
                      </div>
                      <span className="round-arrow">
                        <ChevronRight size={20} />
                      </span>
                    </div>
                  </button>
                ))}
              </div>
              <p className="muted">
                当前选中 {project?.selected.length || 0}{" "}
                张。预设使用固定参数，可在预览后继续细调。
              </p>
              <LibraryPanel luts={luts} presets={personalPresets} busy={locked}
                projectId={project?.id} onRefresh={async () => { await refreshLibrary(); await refresh(); }} onCandidatePreview={candidatePreview}
                canApply={!!project?.selected.length} available={!!health?.lut_engine.available}
                imports={lutImports} onSelectFiles={setLutImports}
                onImport={(options) => action(async () => {
                  const results = await importLutFiles(lutImports, async (file, metadata) => {
                    const data = new FormData();
                    data.append("file", file); data.append("color_space", options.color_space);
                    data.append("metadata", JSON.stringify({ ...metadata,
                      ...(options.publisher ? { publisher: options.publisher } : {}),
                      ...(options.source_page ? { source_page: options.source_page } : {}),
                    }));
                    return api<LutUploadResult>("/luts", { method: "POST", body: data });
                  }, (index, item, lut) => {
                    setLutImports((current) => current.map((entry, i) => i === index ? item : entry));
                    if (lut) setLuts((current) => current.some((entry) => entry.id === lut.id) ? current : [lut, ...current]);
                  });
                  const count = (status: string) => results.filter((item) => item.status === status).length;
                  setNotice(`LUT 导入完成：新增 ${count("imported")} 个，已存在 ${count("existing")} 个，失败 ${count("failed")} 个。`);
                  await refreshLibrary();
                })}
                onChooseLut={(id) => { changeLut({ op: "select", id, strength: 1 }); setTab("workspace"); }}
                onApply={(id) => void preview(undefined, id)}
                onRename={(p, name) => action(async () => {
                  await api("/personal-presets/" + p.id, { method: "PATCH", body: JSON.stringify({ name, revision: p.revision }) });
                  await refreshLibrary(); setNotice("预设名称已更新。");
                })}
                onDelete={(id) => action(async () => {
                  await api("/personal-presets/" + id, { method: "DELETE" });
                  await refreshLibrary(); setNotice("已删除个人预设，照片和历史批次已保留。");
                })} />
            </section>
          )}

          {tab === "memory" && (
            <section className="memory-page">
              <div className="memory-card">
                <div className="section-label">
                  <Brain size={18} />
                  <strong>这个影集里的偏好</strong>
                  <span className="tag">仅当前项目</span>
                </div>
                <p>明确保存你喜欢的色调。偏好不会自动修改已经处理的照片。</p>
                <textarea
                  aria-label="项目偏好"
                  value={preference}
                  onChange={(e) => setPreference(e.target.value)}
                  placeholder="例如：喜欢温暖、低饱和的色调"
                  maxLength={500}
                />
                <div className="button-row">
                  <button
                    className="button primary"
                    disabled={locked || !project}
                    onClick={() =>
                      void action(async () => {
                        receive(
                          await api<Project>(
                            "/projects/" + project!.id + "/preferences",
                            {
                              method: "PUT",
                              body: JSON.stringify({
                                value: preference,
                                context_revision: project!.revision,
                              }),
                            },
                          ),
                        );
                        setNotice("已保存当前项目偏好。");
                      })
                    }
                  >
                    保存偏好
                  </button>
                  <button
                    className="button"
                    disabled={locked || !project}
                    onClick={() =>
                      void action(async () =>
                        receive(
                          await api<Project>(
                            "/projects/" + project!.id + "/preferences",
                            { method: "DELETE" },
                          ),
                        ),
                      )
                    }
                  >
                    <Trash2 size={14} />
                    清除偏好
                  </button>
                </div>
              </div>
              <div className="memory-card">
                <div className="section-label">
                  <MessageSquare size={18} />
                  <strong>对话与当前状态</strong>
                </div>
                <div className="memory-stats">
                  <div>
                    <b>{project?.messages.length || 0}</b>
                    <span>条对话记录</span>
                  </div>
                  <div>
                    <b>
                      {project?.assets.filter((a) => a.result_url).length || 0}
                    </b>
                    <span>张已应用效果</span>
                  </div>
                  <div>
                    <b>{pending ? 1 : 0}</b>
                    <span>个待确认方案</span>
                  </div>
                </div>
                <p>
                  照片、配方和明确偏好保存在本机。清空后开启新对话上下文；已发送到 OpenClaw 的日志不在此删除。
                </p>
                <button
                  className="button"
                  disabled={locked || !project?.messages.length}
                  onClick={() =>
                    void action(async () => {
                      receive(
                        await api<Project>(
                          "/projects/" + project!.id + "/messages",
                          { method: "DELETE" },
                        ),
                      );
                      setNotice("已清空对话，照片、配方和偏好已保留。");
                    })
                  }
                >
                  <Trash2 size={14} />
                  仅清空对话
                </button>
                <div className="recipe-memory">
                  {pending && (
                    <p>
                      待确认方案：第{" "}
                      {pending.items.map((i) => i.ordinal).join("、")}{" "}
                      张。确认应用前不会覆盖已有结果。
                    </p>
                  )}
                  {project?.assets.map((a) => (
                    <div key={a.id}>
                      <strong>
                        第 {a.ordinal} 张 · {a.result_url ? "已应用" : "原图"}
                      </strong>
                      <span>
                        曝光 {a.recipe.exposure_ev.toFixed(2)} EV · 冷暖{" "}
                        {a.recipe.warmth.toFixed(2)}
                        <br />
                        对比度 {a.recipe.contrast.toFixed(2)} · 饱和度{" "}
                        {a.recipe.saturation.toFixed(2)}
                        <br />{a.recipe.lut ? `LUT：${a.recipe.lut.name} · ${Math.round(a.recipe.lut.strength * 100)}%` : "无 LUT"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}

          {tab === "export" && (
            <section className="export-page">
              <div className="export-intro">
                <span className="export-symbol">
                  <ArrowDownToLine size={26} />
                </span>
                <div>
                  <h2>把这一组喜欢，保存下来。</h2>
                  <p>成品长边最多 2560 像素 · 原图保留 · PNG 保留透明通道</p>
                </div>
              </div>
              {project?.operations
                .filter((o) =>
                  [
                    "succeeded",
                    "partial_failed",
                    "failed",
                    "interrupted",
                  ].includes(o.status),
                )
                .map((op) => (
                  <div className="export-batch" key={op.id}>
                    <div className="export-head">
                      <div>
                        <strong>
                          {new Date(op.created_at).toLocaleString("zh-CN")}
                        </strong>
                        <span
                          className={
                            "tag " +
                            (op.status === "succeeded" ? "success" : "")
                          }
                        >
                          {labels[op.status]}
                        </span>
                      </div>
                      {op.download_url && (
                        <a
                          className="button primary small"
                          href={op.download_url}
                        >
                          <ArrowDownToLine size={14} />
                          下载本批 ZIP
                        </a>
                      )}
                    </div>
                    <div className="export-items">
                      {op.items.map((i) => (
                        <div className="export-item" key={i.asset_id}>
                          <div className="export-thumb">
                            {i.result_url ? (
                              <img src={i.result_url} alt={i.name} />
                            ) : (
                              <Images size={23} />
                            )}
                          </div>
                          <div>
                            <strong>
                              第 {i.ordinal} 张 · {i.name}
                            </strong>
                            <small>
                              {i.error || labels[i.status] || i.status}
                            </small>
                          </div>
                          {i.result_url && (
                            <a
                              href={i.result_url + "?download=1"}
                              aria-label={`下载第 ${i.ordinal} 张`}
                              className="icon-button"
                            >
                              <ArrowDownToLine size={18} />
                            </a>
                          )}
                        </div>
                      ))}
                    </div>
                    {["failed", "partial_failed", "interrupted"].includes(
                      op.status,
                    ) && (
                      <button
                        className="text-button"
                        disabled={locked}
                        onClick={() =>
                          void action(async () => {
                            await post("/operations/" + op.id + "/retry");
                            setTab("workspace");
                            setShowPreview(true);
                            await refresh();
                          })
                        }
                      >
                        <RotateCcw size={14} />
                        重新预览失败项
                      </button>
                    )}
                  </div>
                ))}
              {!project?.operations.some((o) =>
                [
                  "succeeded",
                  "partial_failed",
                  "failed",
                  "interrupted",
                ].includes(o.status),
              ) && (
                <div className="export-empty">
                  <Images size={35} />
                  <p>还没有处理结果</p>
                  <span>在工作区确认应用后，这里会出现可下载的照片。</span>
                  <button
                    className="button"
                    onClick={() => setTab("workspace")}
                  >
                    返回工作区
                  </button>
                </div>
              )}
            </section>
          )}

          {tab !== "presets" && <LutCandidates result={project?.lut_search} disabled={locked || draftDirty || !project?.selected.length} onPreview={candidatePreview} />}
          <section className="chat-card" aria-label="调色助手">
            <div className="chat-heading">
              <div>
                <span className="agent-icon">
                  <Sparkles size={15} />
                </span>
                <strong>调色助手</strong>
                <span className="muted">用你的话，描述你的风格</span>
              </div>
              <div className="chat-heading-actions">
                <span className={"model-state " + (canChat ? "connected" : "")}>
                  {health?.agent.message || "读取运行状态…"}
                </span>
                <button
                  type="button"
                  className="chat-expand"
                  aria-expanded={chatExpanded}
                  aria-controls="chat-messages"
                  title={chatExpanded ? "返回工作区（Esc）" : "展开对话，阅读完整记录"}
                  onClick={() => setChatExpanded((expanded) => !expanded)}
                >
                  {chatExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                  {chatExpanded ? "返回工作区" : "展开对话"}
                </button>
              </div>
            </div>
            <div ref={chat} className="chat-messages" id="chat-messages" role="log" aria-live="polite" aria-relevant="additions text" aria-label="对话记录" tabIndex={0}>
              {!project?.messages.length ? (
                <div className="welcome-message">
                  你好，先导入一组照片吧。你可以说“调亮一点、偏暖”，也可以指定“第
                  3 张颜色淡一点”。
                </div>
              ) : (
                project.messages.map((m) => (
                  <div key={m.id} className={"message " + m.role}>
                    <span className="message-avatar">
                      {m.role === "user" ? "你" : <Sparkles size={13} />}
                    </span>
                    {m.operation ? <div className="message-receipt" data-state={m.operation.status}>
                      <p className="receipt-status">{m.operation.status === "ready" && <Check size={16} aria-hidden="true" />}{m.content}</p>
                      <p className="receipt-plan">{m.operation.summary.split("\n")[0]}</p>
                      <details className="receipt-details"><summary>查看处理说明</summary>
                        <div>{m.operation.summary.split("\n").slice(1).join("\n")}</div>
                      </details>
                      {m.operation.status === "ready" && pending?.id === m.operation.id && <button
                        type="button" className="button small" disabled={previewBlocked}
                        title={previewBlocked ? "参数草稿已变化，请重新生成预览" : "查看本次样张的原图与效果对比"}
                        onClick={() => { setTab("workspace"); setShowPreview(true); setChatExpanded(false); window.scrollTo({ top: 0, behavior: "smooth" }); }}
                      >查看预览</button>}
                    </div> : <p>{m.content}</p>}
                  </div>
                ))
              )}
              <AgentStatus turn={agentTurn} onCancel={() => void action(async () => {
                if (!agentTurn) return;
                await post("/agent-turns/" + agentTurn.id + "/cancel");
                await refresh();
              })} />
              {busy && (
                <div className="chat-working">
                  <LoaderCircle size={14} className="spin" />
                  正在处理请求…
                </div>
              )}
            </div>
            <div className="suggestions">
              {[
                "调亮一点，偏暖",
                "第 3 张颜色淡一点",
                "记住，我喜欢自然色调",
              ].map((t) => (
                <button key={t} disabled={locked} onClick={() => setText(t)}>
                  {t}
                </button>
              ))}
            </div>
            <form
              className="composer"
              onSubmit={(e) => {
                e.preventDefault();
                void send();
              }}
            >
              <textarea
                aria-label="给调色助手的指令"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    e.preventDefault();
                    if (!locked && canChat && !agentWorking && !draftDirty && text.trim())
                      void send();
                  }
                }}
                placeholder={
                  canChat
                    ? "说说想要的效果，例如：整体暖一点，颜色淡一点…"
                    : health?.agent.runtime === "direct"
                      ? "配置模型 API 后，即可用自然语言调色…"
                      : "接入 OpenClaw 后，即可用自然语言调色…"
                }
                rows={2}
                maxLength={2000}
              />
              <button
                aria-label="发送指令"
                type="submit"
                disabled={locked || agentWorking || draftDirty || !text.trim() || !canChat}
              >
                {busy ? (
                  <LoaderCircle size={19} className="spin" />
                ) : (
                  <ArrowUp size={19} />
                )}
              </button>
            </form>
            <div className="composer-foot">
              <span>
                {project?.selected.length || 0} 张已选 · 所有调色先预览后应用
              </span>
              <span>{draftDirty ? "请先生成或重置参数草稿，再发送指令" : "Enter 发送 · Shift + Enter 换行"}</span>
            </div>
          </section>
        </div>
        <footer className="page-footer">
          <span>LutCraft</span>
          <span>留住原图，让创作自由一点。</span>
          <span>LOCAL EDITION · 03</span>
        </footer>
      </main>
    </div>
  );
}
