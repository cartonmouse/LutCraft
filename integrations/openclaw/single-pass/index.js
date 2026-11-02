import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const execute = promisify(execFile);
const result = (value, isError = false) => ({ content: [{ type: 'text', text: JSON.stringify(value) }], isError });

export default {
  id: 'lut-single-pass',
  name: 'LUT 单次调色',
  register(api) {
    // Paths come from the host, never from model arguments. Production defaults
    // match OpenAgent's /oasn formal invocation contract.
    const root = process.env.LUT_PROGRAM_ROOT || '/oasn';
    const input = process.env.LUT_INVOCATION_PATH || '/oasn/in/invocation.json';
    const python = process.env.LUT_PYTHON || path.join(root, '.venv/bin/python');
    let inspected = null;
    async function run(action, extra = []) {
      const raw = await readFile(input);
      const runKey = createHash('sha256').update(raw).digest('hex').slice(0, 24);
      const output = process.env.LUT_OUTPUT_DIR || path.join(root, 'out', runKey);
      const args = ['-m', 'backend.app.single_pass', action, '--input', input];
      if (action === 'apply') args.push('--output', output, ...extra);
      try {
        const { stdout } = await execute(python, args, {
          cwd: root, timeout: 180000, maxBuffer: 1024 * 1024,
          env: { PATH: process.env.PATH, PYTHONPATH: root, VIPS_CONCURRENCY: '2', PYTHONIOENCODING: 'utf-8' },
        });
        return JSON.parse(stdout);
      } catch (error) {
        try { return JSON.parse(error.stdout); }
        catch { return {status: 'failed', code: 'tool_failed', message: '调色工具未完成，请检查运行环境后重试。'}; }
      }
    }
    api.registerTool({
      name: 'lut_inspect_request', label: '读取本次图片与可用 LUT',
      description: '读取当前调用的风格要求、图片亮度/色彩统计和真实 LUT 列表。必须先调用，不接收路径。',
      parameters: {type: 'object', properties: {}, additionalProperties: false},
      async execute() {
        const value = await run('inspect');
        inspected = value.status !== 'failed' ? createHash('sha256').update(await readFile(input)).digest('hex') : null;
        return result(value, !inspected);
      },
    });
    api.registerTool({
      name: 'lut_apply', label: '应用 LUT 并生成成品',
      description: '对本次输入的全部图片应用一个真实 LUT，返回调色后的图片文件。不会覆盖原图。',
      parameters: {type: 'object', additionalProperties: false, required: ['lut_id', 'strength', 'reason'], properties: {
        lut_id: {type: 'string', minLength: 1, maxLength: 100},
        strength: {type: 'number', exclusiveMinimum: 0, maximum: 1},
        reason: {type: 'string', minLength: 1, maxLength: 500},
      }},
      async execute(_id, params) {
        const current = createHash('sha256').update(await readFile(input)).digest('hex');
        if (!inspected || current !== inspected) return result({status: 'failed', message: '请先调用 lut_inspect_request 读取当前任务。'}, true);
        if (typeof params.lut_id !== 'string' || !/^[a-z0-9-]+$/.test(params.lut_id) ||
            !Number.isFinite(params.strength) || params.strength <= 0 || params.strength > 1 ||
            typeof params.reason !== 'string' || !params.reason.trim() || params.reason.length > 500) {
          return result({status: 'failed', message: '调色参数无效。'}, true);
        }
        const value = await run('apply', ['--lut-id', params.lut_id, '--strength', String(params.strength), '--reason', params.reason]);
        return result(value, value.status === 'failed');
      },
    });
  },
};
