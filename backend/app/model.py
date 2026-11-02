import json
from pathlib import Path
import httpx
from pydantic import ValidationError
from .schemas import Plan
from .errors import AppError


class ModelClient:
    """Provider adapter for services with the chat-completions JSON envelope."""

    def __init__(self, settings):
        self.settings = settings

    async def plan(self, context):
        s = self.settings
        if not s.model_configured:
            raise AppError(
                "model_unconfigured",
                "对话模型尚未配置。请在项目 .env 中填写模型 API；现在可使用预设和参数调色。",
                503,
            )
        messages = [
            {
                "role": "system",
                "content": (Path(__file__).parent / "prompts/agent.md").read_text(),
            },
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]
        payload = {
            "model": s.model_name,
            "messages": messages,
            "temperature": 0.1,
        }
        if s.model_provider == "deepseek":
            # Small structured planning tasks use bounded, non-thinking JSON output.
            payload.update(
                thinking={"type": "disabled"},
                response_format={"type": "json_object"},
                max_tokens=1536,
                stream=False,
            )
        try:
            async with httpx.AsyncClient(
                timeout=s.timeout, follow_redirects=False
            ) as client:
                for attempt in range(2):
                    response = await client.post(
                        s.model_url,
                        headers={"Authorization": f"Bearer {s.model_key}"},
                        json=payload,
                    )
                    if response.status_code != 200:
                        raise AppError(
                            "model_http",
                            f"模型服务返回 HTTP {response.status_code}，请检查地址、模型及密钥配置。",
                            502,
                        )
                    try:
                        choice = response.json()["choices"][0]
                        if choice.get("finish_reason") not in (None, "stop"):
                            raise ValueError("incomplete response")
                        content = choice["message"]["content"]
                        if not isinstance(content, str):
                            raise ValueError("content")
                        if content.strip().startswith("```"):
                            content = (
                                content.strip().split("\n", 1)[1].rsplit("```", 1)[0]
                            )
                        return Plan.model_validate_json(content)
                    except (
                        ValueError,
                        KeyError,
                        IndexError,
                        TypeError,
                        ValidationError,
                    ):
                        if attempt:
                            raise AppError(
                                "model_format",
                                "模型没有返回有效调色方案，请换一种说法后重试。",
                                502,
                            )
                        messages.append(
                            {
                                "role": "user",
                                "content": "上次返回格式不符合约定。重新输出完整合法 JSON，禁止额外文字。",
                            }
                        )
        except httpx.TimeoutException as exc:
            raise AppError(
                "model_timeout", "模型响应超时，已有照片和配方未改变，请重试。", 504
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "model_network", "无法连接模型服务，请检查配置与网络。", 502
            ) from exc
