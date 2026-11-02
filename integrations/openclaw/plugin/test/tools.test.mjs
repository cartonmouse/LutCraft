import test from "node:test";
import assert from "node:assert/strict";
import { BackendClient } from "../src/backend-client.ts";
import { buildBusinessTools } from "../src/tools.ts";

test("工具身份由可信上下文提供，不采用模型参数；不暴露 apply 工具", async () => {
  let sent;
  const client = new BackendClient("http://127.0.0.1:8765", "test-bridge-secret", async (url, opts) => {
    sent = { url, opts, body: JSON.parse(opts.body) };
    return Response.json({ status: "previewing", operation_id: "op-1" });
  });
  const tools = buildBusinessTools(client, ["lut_preview", "apply", "exec"].map(name => ({ name, description: "test", parameters: {} })),
    { agentId: "lut-color", sessionKey: "trusted-session" });
  assert.equal(tools.length, 1);
  const result = await tools[0].execute("call-1", { runtime_session: "forged", scope: { kind: "all" } });
  assert.equal(sent.body.runtime_session, "trusted-session");
  assert.equal(sent.body.arguments.runtime_session, "forged"); // Backend Strict schema rejects this argument.
  assert.equal(sent.opts.redirect, "error");
  assert.equal(result.details.operation_id, "op-1");
});

test("拒绝缺少身份、非服务地址和重定向错误；错误不泄漏密钥", async () => {
  assert.throws(() => new BackendClient("http://remote.example", "secret"));
  assert.throws(() => new BackendClient("https://example.com/path", "secret"));
  assert.throws(() => new BackendClient("http://user:pass@localhost", "secret"));
  const client = new BackendClient("http://127.0.0.1:8765", "secret", async () => { throw new Error("secret at /private/path"); });
  assert.throws(() => buildBusinessTools(client, [], { agentId: "lut", sessionKey: "" }));
  await assert.rejects(client.invoke({ agentId: "lut", sessionKey: "session" }, "call", "lut_get_context", {}),
    e => !e.message.includes("secret") && !e.message.includes("/private"));
});

test("握手与目录协议可测试，但不代表 OpenClaw 原生加载", async () => {
  const requests = [];
  const client = new BackendClient("http://127.0.0.1:8765", "secret", async (url, opts) => {
    requests.push({ url, opts });
    return Response.json(url.endsWith("catalog") ? { contract_version: 1, tools: [] } : { status: "accepted" });
  });
  await client.hello("lut-color", "test-only");
  assert.deepEqual(await client.catalog(), []);
  assert.equal(JSON.parse(requests[0].opts.body).runtime_version, "test-only");
  assert.equal(requests[1].opts.method, "GET");
});
