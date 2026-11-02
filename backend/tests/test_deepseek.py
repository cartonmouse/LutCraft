import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.errors import AppError
from app.model import ModelClient


def test_deepseek_uses_bounded_json_without_thinking(tmp_path, monkeypatch):
    settings = Settings(tmp_path, "secret", "https://api.deepseek.com/chat/completions",
                        "deepseek-flash", "test-key", model_provider="deepseek")
    calls = []
    real = httpx.AsyncClient

    def respond(request):
        calls.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"status": "ready", "message": "生成预览", "adjustments": [
                {"field": "warmth", "op": "add", "value": 0.1}]})}}]})

    monkeypatch.setattr("app.model.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(respond), **kw))
    plan = asyncio.run(ModelClient(settings).plan({"instruction": "暖一点"}))
    assert plan.adjustments[0].value == .1
    assert calls[0]["thinking"] == {"type": "disabled"}
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["max_tokens"] == 1536 and calls[0]["stream"] is False


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
def test_incomplete_model_response_is_never_executed(tmp_path, monkeypatch, finish_reason):
    settings = Settings(tmp_path, "secret", "https://api.deepseek.com/chat/completions",
                        "deepseek-flash", "test-key", model_provider="deepseek")
    calls = []
    real = httpx.AsyncClient

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": finish_reason, "message": {
            "content": json.dumps({"status": "ready", "message": "不能执行这条未完成回复", "preset_id": "warm"})}}]})

    monkeypatch.setattr("app.model.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(AppError) as err:
        asyncio.run(ModelClient(settings).plan({"instruction": "暖一点"}))
    assert err.value.code == "model_format"
    assert len(calls) == 2
