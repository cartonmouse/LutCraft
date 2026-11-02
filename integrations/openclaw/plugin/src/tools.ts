import { BackendClient } from "./backend-client.ts";
import type { RuntimeBinding, ToolDescriptor } from "./backend-client.ts";

const allowed = new Set(["lut_get_context", "lut_list_styles", "lut_preview", "lut_reset_preview",
  "lut_get_operation", "lut_project_memory", "lut_search", "lut_get_style"]);

/** This function does NOT register with OpenClaw. The version-specific entry is pending O0.
 * The adapter must get binding from SDK runtime context, never from tool args or prompt text.
 */
export function buildBusinessTools(client: BackendClient, descriptors: ToolDescriptor[], trustedBinding: RuntimeBinding) {
  if (!trustedBinding.agentId || !trustedBinding.sessionKey) throw new Error("缺少可信运行上下文");
  const binding = Object.freeze({ ...trustedBinding });
  return descriptors.filter(tool => allowed.has(tool.name)).map(tool => ({
    name: tool.name, description: tool.description, parameters: tool.parameters,
    async execute(callId: string, args: unknown) {
      const result = await client.invoke(binding, callId, tool.name, args);
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result,
        isError: result.status === "failed" };
    },
  }));
}
