import { LoaderCircle } from "lucide-react";
import type { AgentTurn } from "./types";

export const isAgentActive = (turn?: AgentTurn) => !!turn && ["queued", "running"].includes(turn.status);

export function AgentStatus({ turn, onCancel }: { turn?: AgentTurn; onCancel: () => void }) {
  if (!turn) return null;
  const active = isAgentActive(turn);
  const names: Record<string, string> = {
    queued: "调色助手排队中", running: "调色助手正在处理", awaiting_confirmation: "请在图片区检查预览",
    completed: "本轮对话已结束", failed: "本轮未完成", interrupted: "本轮已停止",
  };
  return <div className="agent-turn-state" role="status">
    <div>{active && <LoaderCircle size={14} className="spin" />}<strong>{names[turn.status] || turn.status}</strong>
      {active && <button type="button" onClick={onCancel}>停止本轮</button>}</div>
    {turn.message && ["failed", "interrupted"].includes(turn.status) && <p>{turn.message}</p>}
    {turn.operation_id && ["failed", "interrupted"].includes(turn.status) && <p>已有图片任务已保留，请查看图片区。</p>}
  </div>;
}
