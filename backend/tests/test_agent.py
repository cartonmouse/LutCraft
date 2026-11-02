"""Offline integration tests. GatewayHarness is NOT a real OpenClaw/model run."""

import asyncio
import json
import sqlite3
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from app.config import Settings
from app.errors import AppError
from app.main import create_app
from app.openclaw_client import OpenClawClient
from fastapi.testclient import TestClient
from test_app import create, wait
from test_luts import cube

AUTH = {"Authorization": "Bearer offline-test-bridge"}


class GatewayHarness:
    def __init__(self):
        self.replies = {}
        self.contexts = {}

    async def run(self, session, context):
        self.contexts[session] = context
        while session not in self.replies:
            await asyncio.sleep(0.01)
        result = self.replies[session]
        if isinstance(result, Exception):
            raise result
        return {"id": "offline-response", "text": result}


@pytest.fixture
def agent(tmp_path, monkeypatch):
    harness = GatewayHarness()
    monkeypatch.setattr(
        OpenClawClient,
        "run",
        lambda self, session, context: harness.run(session, context),
    )
    settings = Settings(
        tmp_path,
        "agent-test-secret",
        agent_runtime="openclaw",
        openclaw_url="http://127.0.0.1:19001",
        openclaw_token="offline-gateway-token",
        openclaw_version="test-harness-only",
        openclaw_verified=True,
        bridge_token="offline-test-bridge",
        agent_timeout=10,
    )
    with TestClient(create_app(settings)) as c:
        r = c.post(
            "/internal/openclaw/hello",
            headers=AUTH,
            json={"agent_id": "lut-color", "runtime_version": "test-harness-only"},
        )
        assert r.status_code == 200
        yield c, harness, settings


def start(c, p, text="把选中的照片暖一点", rid=None):
    body = {
        "context_revision": p["revision"],
        "request_id": rid or "request-" + str(time.time_ns()),
        "text": text,
    }
    r = c.post(f"/api/projects/{p['id']}/instructions", json=body)
    assert r.status_code == 202, r.text
    tid = r.json()["id"]
    with c.app.state.service.db.connect() as db:
        session = db.execute(
            "SELECT runtime_session FROM agent_turns WHERE id=?", (tid,)
        ).fetchone()[0]
    return tid, session, body


def invoke(c, session, tool, args=None, cid=None, **kwargs):
    return c.post(
        "/internal/openclaw/invoke",
        headers=kwargs.pop("headers", AUTH),
        json={
            "agent_id": "lut-color",
            "runtime_session": session,
            "call_id": cid or "call-" + str(time.time_ns()),
            "tool": tool,
            "arguments": args or {},
            **kwargs,
        },
    )


def done(c, tid):
    for _ in range(200):
        t = c.get("/api/agent-turns/" + tid).json()
        if t["status"] not in ("queued", "running"):
            return t
        time.sleep(0.01)
    pytest.fail(str(t))


def state(c, p):
    return c.get("/api/projects/" + p["id"]).json()


def test_offline_full_tools_preview_confirm_and_receipt(agent):
    c, h, _ = agent
    p = create(c)
    tid, session, body = start(c, p, "第 1、3 张暖一点")
    assert (
        invoke(c, session, "lut_get_context").json()["context"]["assets"][2]["ordinal"]
        == 3
    )
    args = {
        "scope": {"kind": "all"},
        "adjustments": [{"field": "warmth", "op": "add", "value": 0.2}],
    }
    result = invoke(c, session, "lut_preview", args, "same-call").json()
    oid = result["operation_id"]
    assert invoke(c, session, "lut_preview", args, "same-call").json() == result
    assert invoke(c, session, "lut_preview", args, "alias-call").json() == result
    different = {
        **args,
        "adjustments": [{"field": "warmth", "op": "add", "value": 0.3}],
    }
    assert invoke(c, session, "lut_preview", different, "same-call").status_code == 409
    assert (
        invoke(c, session, "lut_preview", different).json()["code"] == "action_conflict"
    )
    op = wait(c, oid)
    assert [x["ordinal"] for x in op["items"]] == [1, 3]
    assert all(x["recipe"]["warmth"] == 0.2 for x in op["items"])
    assert all(a["revision"] == 0 for a in state(c, p)["assets"])
    # A duplicate browser request returns the original turn even after its revision advanced.
    assert (
        c.post(f"/api/projects/{p['id']}/instructions", json=body).json()["id"] == tid
    )
    h.replies[session] = (
        "已帮你批量应用了所有照片"  # Must be overridden by actual receipt.
    )
    assert done(c, tid)["status"] == "awaiting_confirmation"
    assert "已帮你" not in state(c, p)["messages"][-1]["content"]
    assert invoke(c, session, "lut_preview", args).status_code == 409
    c.post(f"/api/operations/{oid}/apply")
    assert wait(c, oid, ("succeeded", "failed"))["status"] == "succeeded"
    assert [a["revision"] for a in state(c, p)["assets"]] == [1, 0, 1]


def test_binding_auth_project_and_operation_isolation(agent):
    c, h, _ = agent
    p, q = create(c, 1), create(c, 1)
    tid, session, _ = start(c, p)
    assert invoke(c, session, "lut_get_context", headers={}).status_code == 403
    assert (
        invoke(
            c,
            session,
            "lut_get_context",
            headers={**AUTH, "Origin": "http://127.0.0.1:8765"},
        ).status_code
        == 403
    )
    assert invoke(c, "forged-session", "lut_get_context").status_code == 403
    assert (
        invoke(c, session, "lut_get_context", agent_id="other-agent").status_code == 403
    )
    assert (
        invoke(c, session, "lut_get_context", {"owner": "forged"}).json()["code"]
        == "invalid_arguments"
    )
    other = c.post(
        f"/api/projects/{q['id']}/previews",
        json={"context_revision": q["revision"], "target_asset_ids": q["selected"]},
    ).json()
    assert (
        invoke(
            c, session, "lut_get_operation", {"operation_id": other["operation_id"]}
        ).json()["code"]
        == "operation_scope"
    )
    assert (
        invoke(
            c,
            session,
            "lut_preview",
            {"scope": {"kind": "ids", "asset_ids": q["selected"]}, "preset_id": "warm"},
        ).json()["status"]
        == "previewing"
    )  # Explicit '选中' resolves to project p.
    cookie = c.cookies.get("lut_session")
    c.cookies.clear()
    assert c.get("/api/agent-turns/" + tid).status_code == 404
    assert c.post("/api/agent-turns/" + tid + "/cancel").status_code == 404
    c.cookies.set("lut_session", cookie)
    h.replies[session] = "请确认预览"
    assert done(c, tid)["status"] == "awaiting_confirmation"


def test_scope_foreign_ids_and_nonexistent_numbers_rejected(agent):
    c, _, _ = agent
    p, q = create(c, 1), create(c, 1)
    _, session, _ = start(c, p, "调暖一点")
    r = invoke(
        c,
        session,
        "lut_preview",
        {"scope": {"kind": "ids", "asset_ids": q["selected"]}, "preset_id": "warm"},
    )
    assert r.json()["code"] == "asset_scope"
    assert not state(c, p)["operations"]


def test_manual_change_rejects_late_agent_results(agent):
    c, h, _ = agent
    p = create(c)
    tid, session, _ = start(c, p)
    c.patch(
        f"/api/projects/{p['id']}/workspace",
        json={
            "context_revision": p["revision"],
            "selected_asset_ids": p["selected"][:1],
            "viewed_asset_id": p["viewed"],
        },
    )
    assert (
        invoke(c, session, "lut_preview", {"preset_id": "warm"}).json()["code"]
        == "stale_state"
    )
    h.replies[session] = "好的"
    assert done(c, tid)["status"] == "interrupted"
    assert not state(c, p)["operations"]


@pytest.mark.parametrize("instruction", ["暖一点", "不要记住这个偏好"])
def test_no_implicit_or_negated_memory(agent, instruction):
    c, h, _ = agent
    p = create(c, 1)
    tid, session, _ = start(c, p, instruction)
    assert (
        invoke(c, session, "lut_project_memory", {"op": "set", "value": "暖色"}).json()[
            "code"
        ]
        == "memory_explicit"
    )
    assert state(c, p)["preferences"] == {}
    h.replies[session] = "未保存"
    done(c, tid)


def test_explicit_memory_clear_and_no_old_context(agent):
    c, h, _ = agent
    p = create(c, 1)
    tid, session, _ = start(c, p, "记住，我喜欢暖色")
    assert invoke(
        c, session, "lut_project_memory", {"op": "set", "value": "暖色"}
    ).json()["preferences"] == {"style_preference": "暖色"}
    h.replies[session] = "已保存"
    done(c, tid)
    p = state(c, p)
    other = create(c, 1)
    assert other["preferences"] == {}
    tid2, session2, _ = start(c, p, "继续")
    assert (
        invoke(c, session2, "lut_get_context").json()["context"]["preferences"][
            "style_preference"
        ]
        == "暖色"
    )
    c.delete(f"/api/projects/{p['id']}/preferences")
    assert (
        invoke(
            c, session2, "lut_project_memory", {"op": "set", "value": "暖色"}
        ).status_code
        == 409
    )
    assert done(c, tid2)["status"] == "interrupted"
    p = state(c, p)
    tid3, session3, _ = start(c, p, "读取当前偏好")
    assert session3 != session2 != session
    context = invoke(c, session3, "lut_get_context").json()["context"]
    assert context["preferences"] == {}
    assert "暖色" not in json.dumps(context["recent_messages"], ensure_ascii=False)
    c.delete(f"/api/projects/{p['id']}/messages")
    h.replies[session2] = "迟到的旧结果"
    h.replies[session3] = "迟到的新结果"
    time.sleep(0.05)
    assert state(c, p)["messages"] == []
    assert done(c, tid3)["status"] == "interrupted"


def test_timeout_preserves_preview_no_auto_retry(agent):
    c, h, _ = agent
    p = create(c, 1)
    tid, session, body = start(c, p)
    oid = invoke(c, session, "lut_preview", {"preset_id": "warm"}).json()[
        "operation_id"
    ]
    h.replies[session] = AppError("agent_timeout", "超时", 504)
    t = done(c, tid)
    assert t["status"] == "failed" and t["operation_id"] == oid
    assert wait(c, oid)["status"] == "ready"
    assert (
        c.post(f"/api/projects/{p['id']}/instructions", json=body).json()["id"] == tid
    )
    assert len(state(c, p)["operations"]) == 1
    assert invoke(c, session, "lut_project_memory", {"op": "read"}).status_code == 409


def test_cancel_and_concurrency_and_request_conflict(agent):
    c, _, _ = agent
    p = create(c, 1)
    tid, session, body = start(c, p)
    assert (
        c.post(
            f"/api/projects/{p['id']}/instructions", json={**body, "text": "改成黑白"}
        ).status_code
        == 409
    )
    assert (
        c.post(
            f"/api/projects/{p['id']}/instructions",
            json={**body, "request_id": "different-request"},
        ).json()["code"]
        == "agent_busy"
    )
    assert c.post(f"/api/agent-turns/{tid}/cancel").json()["status"] == "interrupted"
    assert invoke(c, session, "lut_preview", {"preset_id": "warm"}).status_code == 409
    assert not state(c, p)["operations"]


def test_tool_limit_and_invalid_actions(agent):
    c, h, settings = agent
    settings.agent_tool_limit = 4
    p = create(c, 1)
    tid, session, _ = start(c, p)
    assert (
        invoke(c, session, "exec", {"cmd": "echo bad"}).json()["code"]
        == "unsupported_tool"
    )
    assert (
        invoke(
            c,
            session,
            "lut_preview",
            {"adjustments": [{"field": "warmth", "op": "set", "value": 9}]},
        ).json()["code"]
        == "recipe_range"
    )
    assert (
        invoke(
            c, session, "lut_preview", {"preset_id": "warm", "personal_preset_id": "no"}
        ).json()["code"]
        == "invalid_arguments"
    )
    assert (
        invoke(
            c, session, "lut_preview", {"lut_action": {"op": "select", "id": "missing"}}
        ).json()["status"]
        == "failed"
    )
    assert invoke(c, session, "lut_get_context").status_code == 429
    assert not state(c, p)["operations"]
    h.replies[session] = "未执行"
    done(c, tid)


def test_atomic_preview_receipt_rollback(agent, monkeypatch):
    c, _, _ = agent
    p = create(c, 1)
    _, session, _ = start(c, p)
    # Force the receipt constraint to fail at the same time as operation insertion.
    with c.app.state.service.db.connect(write=True) as db:
        db.execute(
            "CREATE TRIGGER fail_receipt BEFORE INSERT ON tool_invocations BEGIN SELECT RAISE(ABORT,'test'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        invoke(c, session, "lut_preview", {"preset_id": "warm"})
    assert state(c, p)["revision"] == p["revision"]
    assert not state(c, p)["operations"]


def test_lut_and_pending_subset_continuation_and_reset(agent):
    c, h, _ = agent
    p = create(c)
    upload = c.post(
        "/api/luts",
        data={"color_space": "srgb", "name": "演示暖色"},
        files={"file": ("demo.cube", cube(), "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    lut = upload.json()
    tid, session, _ = start(c, p)
    styles = invoke(c, session, "lut_list_styles", {"kind": "lut"}).json()["styles"]
    assert styles[0]["id"] == lut["id"]
    found = invoke(c, session, "lut_search", {"query": "演示暖色", "exact_name": "演示暖色"}).json()
    detail = invoke(c, session, "lut_get_style", {"id": lut["id"]}).json()
    assert detail["style"]["compatibility"] == "confirmed"
    r = invoke(
        c,
        session,
        "lut_preview",
        {
            "adjustments": [{"field": "warmth", "op": "set", "value": 0.2}],
            "lut_action": {"op": "select", "id": lut["id"], "strength": 0.6},
            "search_id": found["search_id"],
        },
    ).json()
    assert wait(c, r["operation_id"])["status"] == "ready"
    h.replies[session] = "请确认"
    done(c, tid)
    p = state(c, p)
    tid2, session2, _ = start(c, p, "第3张颜色淡一点，保留 LUT")
    context = invoke(c, session2, "lut_get_context").json()["context"]
    assert context["lut_candidates"]["search_id"] == found["search_id"]
    r2 = invoke(
        c,
        session2,
        "lut_preview",
        {"adjustments": [{"field": "saturation", "op": "add", "value": -0.2}]},
    ).json()
    op = wait(c, r2["operation_id"])
    assert len(op["items"]) == 1 and op["items"][0]["ordinal"] == 3
    recipe = op["items"][0]["recipe"]
    assert (
        recipe["warmth"] == 0.2
        and recipe["lut"]["strength"] == 0.6
        and recipe["saturation"] == 0.8
    )
    h.replies[session2] = "请确认"
    done(c, tid2)
    p = state(c, p)
    _, session3, _ = start(c, p, "第3张恢复原图效果")
    reset = wait(c, invoke(c, session3, "lut_reset_preview").json()["operation_id"])
    assert reset["items"][0]["recipe"]["lut"] is None
    assert reset["items"][0]["recipe"]["warmth"] == 0


def test_health_gate_and_no_credentials_exposed(tmp_path):
    settings = Settings(
        tmp_path,
        "secret",
        agent_runtime="openclaw",
        openclaw_url="http://127.0.0.1:19001",
        openclaw_token="top-secret-token",
        bridge_token="top-secret-bridge",
        openclaw_version="unverified",
    )
    with TestClient(create_app(settings)) as c:
        p = create(c, 1)
        health = c.get("/api/health")
        assert "top-secret" not in health.text
        assert health.json()["agent"]["configured"] is True
        assert health.json()["agent"]["send_enabled"] is False
        assert health.json()["agent"]["last_call"] == "not_tested"
        assert (
            c.post(
                f"/api/projects/{p['id']}/instructions",
                json={
                    "text": "暖一点",
                    "request_id": "not-ready-01",
                    "context_revision": p["revision"],
                },
            ).status_code
            == 503
        )
        assert (
            c.get(
                "/internal/openclaw/catalog",
                headers={"Authorization": "Bearer top-secret-bridge"},
            ).status_code
            == 403
        )
        assert state(c, p)["messages"] == []


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(401), "gateway_auth"),
        (httpx.Response(302), "gateway_error"),
        (httpx.Response(200, json={"status": "incomplete"}), "gateway_incomplete"),
        (
            httpx.Response(200, json={"status": "completed", "id": "r", "output": []}),
            "gateway_format",
        ),
    ],
)
def test_gateway_transport_errors(tmp_path, monkeypatch, response, code):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.return_value = response
    monkeypatch.setattr(
        "app.openclaw_client.httpx.AsyncClient", lambda **kwargs: client
    )
    settings = Settings(tmp_path, "s", openclaw_url="http://127.0.0.1:19001")
    with pytest.raises(AppError) as exc:
        asyncio.run(OpenClawClient(settings).run("session", "context"))
    assert exc.value.code == code
    assert client.post.await_count == 1


def test_gateway_transport_success_and_timeout(tmp_path, monkeypatch):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.return_value = httpx.Response(
        200,
        json={
            "status": "completed",
            "id": "r-1",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "请查看预览"}],
                }
            ],
        },
    )
    options = {}

    def factory(**kwargs):
        options.update(kwargs)
        return client

    monkeypatch.setattr("app.openclaw_client.httpx.AsyncClient", factory)
    settings = Settings(
        tmp_path,
        "s",
        openclaw_url="http://127.0.0.1:19001",
        openclaw_token="server-token",
    )
    assert (
        asyncio.run(OpenClawClient(settings).run("bound-session", "context"))["text"]
        == "请查看预览"
    )
    args = client.post.call_args.kwargs
    assert args["headers"]["x-openclaw-session-key"] == "bound-session"
    assert args["json"]["model"] == "openclaw/lut-color"
    assert "tools" not in args["json"]  # Tool loop must run inside OpenClaw.
    assert options["follow_redirects"] is False
    client.post.side_effect = httpx.ReadTimeout("server-token must not leak")
    with pytest.raises(AppError) as exc:
        asyncio.run(OpenClawClient(settings).run("session", "context"))
    assert exc.value.code == "agent_timeout" and "server-token" not in exc.value.message


def test_v2_migration_and_interrupted_turn_survive_restart(tmp_path):
    settings = Settings(tmp_path, "restart-secret")
    with TestClient(create_app(settings)) as c:
        p = create(c, 1)
        cookie = c.cookies.get("lut_session")
    path = tmp_path / "lut.sqlite3"
    with sqlite3.connect(path) as db:
        for table in ("tool_invocations", "agent_turns", "agent_sessions"):
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=2")
    with TestClient(create_app(settings)) as c:
        c.cookies.set("lut_session", cookie)
        assert state(c, p)["assets"] == p["assets"]
        with c.app.state.service.db.connect(write=True) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4
            db.execute(
                "INSERT INTO agent_sessions VALUES (?,0,'2026','2026')", (p["id"],)
            )
            db.execute(
                "INSERT INTO agent_turns(id,project_id,request_id,instruction,expected_revision,runtime_session,agent_id,epoch,status,created_at,expires_at) VALUES ('t',?,'restart-request','暖一点',?,'old-session','lut-color',0,'running','2026',?)",
                (p["id"], p["revision"], time.time() + 100),
            )
    with TestClient(create_app(settings)) as c:
        c.cookies.set("lut_session", cookie)
        assert c.get("/api/agent-turns/t").json()["status"] == "interrupted"
        assert state(c, p)["assets"] == p["assets"]
    backups = list((tmp_path / "backups").glob("before-v4-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
