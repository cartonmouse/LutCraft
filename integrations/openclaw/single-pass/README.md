# 单次 LUT 调色 · OpenClaw 原生实现

当前主流程：用户提供图片和风格 → OpenClaw main 选择 LUT → 工具真实调色 → 返回结果图片。没有网页聊天、手动选择 LUT、确认应用或自建 LUT 步骤。

## 本地运行

- OpenClaw 固定为 `2026.6.11`，与 2026-10-29 查询的 [OpenAgent Program 基线](https://openagent.org/docs/program) 一致。
- 安装位置：`integrations/openclaw/local/node_modules`；不安装全局服务，不更改用户 `~/.openclaw`。
- 本地网页入口：`bash prototypes/lut-studio/start.sh`，访问 `http://127.0.0.1:4175/`。
- 本地模型沿用项目 `.env` 中的 `MODEL_API_URL`、`MODEL_NAME`、`MODEL_API_KEY`。它们仅用于本地开发；平台部署时使用平台模型配置。
- 每个任务有独立的 OpenClaw 配置、会话和工作区；只开放本插件的两个工具。浏览器不访问模型密钥。

首次安装本地运行时：

```bash
source scripts/env.sh
"$LUT_PNPM" --dir integrations/openclaw/local install --frozen-lockfile
```

依赖中未使用的渠道、Google SDK、命令解析器构建脚本显式禁用；原生 LUT 插件不依赖这些功能。OpenClaw 的渠道初始化可能给出未生成可选渠道模块的诊断，不影响这两个已验证的调色工具。

本地 `run_openclaw` 完成后会生成持久化预览，返回 `preview.url`。多个独立任务可用 `scripts/show_lut_results.py` 合并展示。网页没有上传、输入或生成接口；所有要求从 Codex 进入。

## 两个原生工具

| 工具 | 输入 | 输出 |
|---|---|---|
| `lut_inspect_request` | 无模型可填路径；宿主绑定当前输入 | 风格要求、图片亮度和 RGB 统计、真实 LUT 目录 |
| `lut_apply` | `lut_id`、`strength`、`reason` | 实际成品、LUT 信息、结果清单 |

模型不能填写用户身份、文件路径、输出目录或执行命令。插件使用 `execFile` 调用 Python，不拼接 shell 命令。Python 再校验图片数量/大小/格式、输入目录边界、LUT ID、文件 SHA-256 和强度。渲染复用现有 pyvips/OpenColorIO 引擎，从原图创建新文件。

默认最多 10 张 JPEG/PNG、每张 10 MB 和 2400 万像素，输出长边最多 2560 像素；PNG 保留透明通道。同一批次使用相同 LUT 与强度。选择依据是用户风格、LUT 描述和图像统计，尚未使用视觉模型识别人像或场景。

## 为后续 OpenAgent 调用准备

插件默认业务根目录 `/oasn`、正式输入 `/oasn/in/invocation.json`，读取 `input.user_prompt` 与 `input.attachments`。只处理明确列出的本次附件，不扫描目录。完整调用数据不输出到模型、日志或网页。

Codex/本地宿主负责生成这一输入结构，网页仅读取调色后的预览；环境变量 `LUT_PROGRAM_ROOT`、`LUT_INVOCATION_PATH`、`LUT_OUTPUT_DIR`、`LUT_PYTHON` 只由本地宿主绑定，用于隔离任务。这些路径不在模型参数中。

准备本地 Program 目录：

```bash
.venv/bin/python scripts/prepare_openagent.py --output data/openagent-program
```

脚本只复制允许的业务源代码、LUT 和许可文件、依赖清单、主 Agent 规则及原生插件，不上传、不上线，不包含 `.env`、用户图片、数据库或会话。目标目录必须不存在。

将来按官方开发入口同步至 `/oasn`，在平台现有配置中为 main 启用插件和两个工具，保留平台模型、鉴权和运行配置。最终通过 main 返回工具生成的真实图片附件/下载链接。当前页面只用于本地只读预览与验收，**它不是 OpenAgent WebUI 的已部署入口**；第一版的正式交付是图片，使用时不依赖网页。

## 验证

```bash
.venv/bin/python -m pytest backend/tests/test_single_pass.py prototypes/lut-studio/test_server.py -q
```

2026-10-29：已在本机固定版本中完成原生插件加载，并通过真实模型调用执行 `lut_inspect_request` → `lut_apply`，生成暖调 JPEG；另一次真实调用为两张样片选择 Silver Mono、100% 强度，返回两张黑白成品与可解压 ZIP。原生会话中确认执行了两个工具。已使用正式输入结构测试批量渲染、原图不变、透明通道保留、重复调用、错误 LUT、越界附件、网页下载和跨会话访问隔离（当时的上传界面）。当前只读版另验证禁止写请求、指定结果读取、重启恢复、文件白名单和越界链接拒绝。

OpenAgent 的实际远端模型、文件交付、发布与上线尚未执行，按当前决定留到之后验收。

## 参考

- [OpenAgent Program 规范](https://openagent.org/docs/program)
- [OpenAgent 输入与输出](https://openagent.org/docs/io-and-webui)
- [OpenClaw 原生插件开发](https://docs.openclaw.ai/plugins/building-plugins)
