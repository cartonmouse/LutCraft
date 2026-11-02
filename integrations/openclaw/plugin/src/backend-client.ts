// Business protocol only. A target-version host adapter must supply trusted context.
export type RuntimeBinding = Readonly<{ agentId: string; sessionKey: string }>;
export type ToolDescriptor = { name: string; description: string; parameters: Record<string, unknown> };

export class BackendClient {
  private base: string;
  private token: string;
  private fetcher: typeof fetch;

  constructor(base: string, token: string, fetcher: typeof fetch = fetch) {
    const url = new URL(base);
    if (!token || url.username || url.password || url.search || url.hash || url.pathname !== "/"
      || !["http:", "https:"].includes(url.protocol)
      || (url.protocol === "http:" && !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)))
      throw new Error("业务接口地址或凭据配置无效");
    this.base = url.origin;
    this.token = token;
    this.fetcher = fetcher;
  }

  private async request(path: string, body?: unknown): Promise<Record<string, unknown>> {
    try {
      const response = await this.fetcher(this.base + "/internal/openclaw/" + path, {
        method: body === undefined ? "GET" : "POST", redirect: "error",
        headers: { Authorization: "Bearer " + this.token, "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error("业务接口未接受调用：HTTP " + response.status);
      return await response.json() as Record<string, unknown>;
    } catch {
      // Do not surface headers, tokens, internal URLs or echoed request bodies to the model.
      throw new Error("LUT 业务接口调用未完成；请查询已有任务，勿重复建立预览。");
    }
  }

  hello(agentId: string, runtimeVersion: string) {
    return this.request("hello", { agent_id: agentId, runtime_version: runtimeVersion });
  }

  async catalog(): Promise<ToolDescriptor[]> {
    const result = await this.request("catalog");
    if (result.contract_version !== 1 || !Array.isArray(result.tools))
      throw new Error("不支持的 LUT 工具协议");
    return result.tools as ToolDescriptor[];
  }

  invoke(binding: RuntimeBinding, callId: string, tool: string, args: unknown) {
    if (!binding.agentId || !binding.sessionKey || !callId) throw new Error("缺少可信运行上下文");
    return this.request("invoke", { agent_id: binding.agentId, runtime_session: binding.sessionKey,
      call_id: callId, tool, arguments: args });
  }
}
