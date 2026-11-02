"""OpenResponses candidate transport; target-version compatibility is a separate gate."""

import httpx

from .errors import AppError


class OpenClawClient:
    def __init__(self, settings):
        self.settings = settings

    async def run(self, session_key, context):
        s = self.settings
        try:
            async with httpx.AsyncClient(
                timeout=s.agent_timeout, follow_redirects=False
            ) as client:
                response = await client.post(
                    s.openclaw_url.rstrip("/") + "/v1/responses",
                    headers={
                        "Authorization": f"Bearer {s.openclaw_token}",
                        "x-openclaw-agent-id": s.openclaw_agent,
                        "x-openclaw-session-key": session_key,
                    },
                    json={
                        "model": f"openclaw/{s.openclaw_agent}",
                        "stream": False,
                        "input": context,
                    },
                )
            if response.status_code in (401, 403):
                raise AppError(
                    "gateway_auth", "OpenClaw 认证失败，请检查服务端配置。", 503
                )
            if response.status_code != 200:
                raise AppError(
                    "gateway_error",
                    "OpenClaw 未成功完成请求；可查看已有任务后再决定是否重试。",
                    502,
                )
            body = response.json()
            if body.get("status") != "completed":
                raise AppError(
                    "gateway_incomplete",
                    "OpenClaw 返回未完成状态；已有图片任务仍可在页面查看。",
                    502,
                )
            texts = [
                part["text"]
                for item in body.get("output", [])
                if item.get("type") == "message" and item.get("role") == "assistant"
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            ]
            text = "\n".join(texts).strip()
            if not text or not isinstance(body.get("id"), str):
                raise ValueError("Missing completed assistant output")
            return {"id": body["id"][:200], "text": text[:3000]}
        except httpx.TimeoutException as exc:
            raise AppError(
                "agent_timeout", "Agent 请求超时；已有预览会保留，请查看任务状态。", 504
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "gateway_unreachable", "无法连接 OpenClaw，仍可使用页面参数调色。", 503
            ) from exc
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AppError(
                "gateway_format", "OpenClaw 返回格式不符合已实现的协议。", 502
            ) from exc
