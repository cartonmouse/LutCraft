"""Isolated local OpenClaw runner; deployment uses the platform's main agent."""
import asyncio
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

from .errors import AppError

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "integrations/openclaw/single-pass"
ENTRY = ROOT / "integrations/openclaw/local/node_modules/openclaw/openclaw.mjs"


def local_settings():
    values = {**dotenv_values(ROOT / ".env"), **os.environ}
    node = shutil.which("node")
    if not node:
        bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        node = str(bundled) if bundled.is_file() else None
    return {"node": node, "url": values.get("MODEL_API_URL", ""),
            "model": values.get("MODEL_NAME", ""), "key": values.get("MODEL_API_KEY", "")}


def runtime_status():
    settings = local_settings()
    return {"runtime": "openclaw", "version": "2026.6.11", "installed": bool(ENTRY.is_file() and settings["node"]),
            "configured": bool(ENTRY.is_file() and settings["node"] and all(settings[k] for k in ("url", "model", "key"))),
            "rendering": "cube-lut", "vision": "image-statistics"}


def prepare_runtime(job_dir):
    settings = local_settings()
    if not runtime_status()["configured"]:
        raise AppError("runtime_unavailable", "本地 OpenClaw 或模型配置尚未就绪。", 503)
    endpoint = urlparse(settings["url"])
    if (endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username or endpoint.password
            or endpoint.query or endpoint.fragment or (endpoint.scheme == "http" and endpoint.hostname not in ("127.0.0.1", "localhost"))):
        raise AppError("model_url", "模型服务地址无效。", 503)
    base = settings["url"].removesuffix("/chat/completions").rstrip("/")
    state = Path(job_dir) / "runtime"
    workspace = state / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PLUGIN / "AGENTS.md", workspace / "AGENTS.md")
    config = {
        "agents": {"defaults": {"workspace": str(workspace), "skipBootstrap": True,
                    "model": {"primary": f"lut-model/{settings['model']}"}, "thinkingDefault": "off",
                    "timeoutSeconds": 120, "memorySearch": {"enabled": False}}},
        "models": {"mode": "replace", "providers": {"lut-model": {
            "baseUrl": base, "apiKey": "${LUT_AGENT_MODEL_KEY}", "api": "openai-completions",
            "models": [{"id": settings["model"], "name": settings["model"], "reasoning": False,
                        "input": ["text"], "contextWindow": 64000, "maxTokens": 4096}],
        }}},
        "tools": {"allow": ["lut_inspect_request", "lut_apply"]},
        "skills": {"allowBundled": []},
        "plugins": {"allow": ["lut-single-pass"], "load": {"paths": [str(PLUGIN)]},
                    "entries": {"lut-single-pass": {"enabled": True}}},
    }
    config_path = state / "openclaw.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    env = {**os.environ, "OPENCLAW_STATE_DIR": str(state), "OPENCLAW_CONFIG_PATH": str(config_path),
           "LUT_AGENT_MODEL_KEY": settings["key"], "LUT_PROGRAM_ROOT": str(ROOT),
           "LUT_INVOCATION_PATH": str(Path(job_dir) / "input/invocation.json"),
           "LUT_OUTPUT_DIR": str(Path(job_dir) / "output"), "LUT_PYTHON": str(ROOT / ".venv/bin/python"),
           "OPENCLAW_NO_RESPAWN": "1"}
    return settings, env


async def run_openclaw(job_dir, publish_preview=True):
    job_dir = Path(job_dir).resolve()
    settings, env = prepare_runtime(job_dir)
    process = await asyncio.create_subprocess_exec(
        settings["node"], str(ENTRY), "agent", "--local", "--agent", "main", "--session-id", job_dir.name,
        "--message", "请按 AGENTS.md 执行当前调色任务。先调用 lut_inspect_request 读取本次输入，然后选择合适的 LUT 并调用 lut_apply，最后返回真实结果图片。",
        "--json", "--timeout", "120", env=env, cwd=ROOT,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=150)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise AppError("agent_timeout", "调色任务超时，请稍后重试。", 504) from None
    manifest = job_dir / "output/result.json"
    if manifest.is_file():
        result = json.loads(manifest.read_text())
        if result.get("status") == "completed" and result.get("photos"):
            for photo in result["photos"]:
                target = (job_dir / "output" / photo["filename"]).resolve()
                if target.parent != (job_dir / "output").resolve() or not target.is_file():
                    raise AppError("result_missing", "调色结果不完整，请重试。", 502)
            if publish_preview:
                from .preview_gallery import publish_jobs
                try:
                    result["preview"] = await asyncio.to_thread(publish_jobs, [job_dir])
                except (AppError, OSError, ValueError, KeyError):
                    # A viewer handoff failure must not discard rendered photos.
                    result["preview"] = {"status": "unavailable"}
            return result
    message = "OpenClaw 未生成调色文件，请检查模型配置或换一种风格要求重试。"
    try:
        response = json.loads(stdout)
        payloads = response.get("payloads", response.get("result", {}).get("payloads", []))
        text = "\n".join(p.get("text", "") for p in payloads if not p.get("isError"))
        if text and process.returncode == 0:
            message = text[:500]
    except (ValueError, TypeError, AttributeError):
        pass
    raise AppError("agent_no_result", message, 502)
