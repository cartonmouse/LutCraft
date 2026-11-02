import threading
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.errors import AppError
from app.main import create_app
from app.schemas import Plan
from test_app import client, create, wait
from test_library import add, edit


def instruct(c, p, text="第2张暖一点", rid="receipt-request-01"):
    response = c.post(f"/api/projects/{p['id']}/instructions", json={
        'context_revision':p['revision'], 'request_id':rid, 'text':text})
    assert response.status_code == 200, response.text
    return response.json()['operation_id']


def current(c, p):
    return c.get(f"/api/projects/{p['id']}").json()


def assistant(c, p, oid):
    return next(m for m in current(c,p)['messages'] if m['role']=='assistant' and m['operation_id']==oid)


def warm_plan(c):
    c.app.state.service.model.plan=AsyncMock(return_value=Plan(status='ready', message='模型声称已应用全部照片',
        adjustments=[{'field':'warmth','op':'add','value':.1}]))


def test_chat_tracks_async_preview_without_applying_or_duplicate_messages(client, monkeypatch):
    c=client; s=c.app.state.service; p=create(c,2); warm_plan(c)
    release=threading.Event(); original=s.render_recipe
    def delayed(*args,**kwargs):
        assert release.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(s,'render_recipe',delayed)
    try:
        oid=instruct(c,p)
        pending=assistant(c,p,oid)
        assert '正在为第 2 张生成预览' in pending['content']
        assert pending['operation']['status']=='previewing'
        release.set(); wait(c,oid)
        ready=assistant(c,p,oid)
        assert ready['id']==pending['id']
        assert '预览已生成，尚未应用' in ready['content']
        assert '冷暖 0.00 → 0.10' in ready['operation']['summary']
        assert '处理范围：第 2 张；预览样张：第 2 张' in ready['operation']['summary']
        assert '模型声称' not in ready['content']+ready['operation']['summary']
        assert all(a['revision']==0 for a in current(c,p)['assets'])
        assert len(current(c,p)['messages'])==2
        assert assistant(c,p,oid)==ready
        c.post(f'/api/operations/{oid}/apply'); wait(c,oid,('succeeded',))
        assert '应用已完成：1 张成功' in assistant(c,p,oid)['content']
    finally:
        release.set()


def test_render_finishes_before_reply_is_recorded(client, monkeypatch):
    c=client; s=c.app.state.service; p=create(c,1); warm_plan(c)
    def immediate(fn,n,*args):
        try: fn(*args)
        finally: s.pending-=n
    monkeypatch.setattr(s,'submit',immediate)
    oid=instruct(c,p,'暖一点')
    assert '预览已生成' in assistant(c,p,oid)['content']


def test_preview_failure_is_reported_in_chat(client, monkeypatch):
    c=client; p=create(c,1); warm_plan(c)
    def fail(*args,**kwargs): raise AppError('render_failed','测试渲染失败。')
    monkeypatch.setattr(c.app.state.service,'render_recipe',fail)
    oid=instruct(c,p,'暖一点'); assert wait(c,oid)['status']=='failed'
    message=assistant(c,p,oid)
    assert '预览生成失败：测试渲染失败' in message['content']
    assert '已有照片效果未改变' in message['content']
    assert current(c,p)['assets'][0]['recipe']['warmth']==0


@pytest.mark.parametrize('state,expected',[('discarded','已放弃'),('stale','已失效'),('superseded','已被后续预览替代'),('interrupted','已中断')])
def test_terminal_states_cannot_keep_claiming_generation(client,state,expected):
    c=client; p=create(c,1); warm_plan(c); oid=instruct(c,p,'暖一点'); wait(c,oid)
    with c.app.state.service.db.connect(write=True) as db:
        db.execute('UPDATE operations SET status=? WHERE id=?',(state,oid))
    assert expected in assistant(c,p,oid)['content']


def test_lut_receipt_freezes_search_evidence_and_actual_recipe(client):
    c=client; p=create(c,1); lut=add(c,'暖调胶片',['暖色','复古'])
    async def plan(context):
        if not context['search_complete']:
            return Plan(status='search',message='搜索',search_intent={'query':'整体偏暖'})
        return Plan(status='ready',message='未经验证的模型解释',search_id=context['lut_candidates']['search_id'],
                    lut_action={'op':'select','id':lut['id'],'strength':.6})
    c.app.state.service.model.plan=plan
    oid=instruct(c,p,'想要整体偏暖的风格'); wait(c,oid)
    explanation=assistant(c,p,oid)['operation']['summary']
    assert '暖调胶片 · LUT 强度 60%' in explanation
    assert '检索需求：「整体偏暖」' in explanation and '关键词与同义词检索' in explanation
    assert '相关特征：暖色' in explanation
    assert '基础参数保持不变' in explanation
    edit(c,lut,metadata={'description':'后来的资料','tags':['冷色']})
    assert assistant(c,p,oid)['operation']['summary']==explanation
    # Legacy rows have no before-values; recover this request's search, not the latest one.
    with c.app.state.service.db.connect(write=True) as db:
        db.execute("UPDATE operations SET summary='旧版固定说明' WHERE id=?",(oid,))
    legacy=assistant(c,p,oid)
    assert '预览已生成' in legacy['content']
    assert '最终基础参数' in legacy['operation']['summary']
    assert '相关特征：暖色' in legacy['operation']['summary']


def test_clearing_chat_during_render_does_not_resurrect_receipts(client,monkeypatch):
    c=client; s=c.app.state.service; p=create(c,1); warm_plan(c)
    release=threading.Event(); original=s.render_recipe
    def delayed(*args,**kwargs):
        assert release.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(s,'render_recipe',delayed)
    try:
        oid=instruct(c,p,'暖一点')
        assert c.delete(f"/api/projects/{p['id']}/messages").status_code==200
        release.set(); wait(c,oid)
        assert current(c,p)['messages']==[]
    finally: release.set()


def test_receipts_survive_restart_and_older_operation_window(tmp_path):
    settings=Settings(tmp_path,'receipt-secret',agent_runtime='direct')
    with TestClient(create_app(settings)) as c:
        p=create(c,1); warm_plan(c); oid=instruct(c,p,'暖一点'); wait(c,oid)
        cookie=dict(c.cookies)
        with c.app.state.service.db.connect(write=True) as db:
            for i in range(31):
                db.execute("INSERT INTO operations(id,project_id,status,source_revision,targets_json,summary,created_at) VALUES (?,?, 'discarded',0,'[]','later',?)",
                           (f'later-{i}',p['id'],f'2099-01-01T00:00:{i:02d}Z'))
    with TestClient(create_app(settings)) as c:
        c.cookies.update(cookie)
        assert oid not in [op['id'] for op in current(c,p)['operations']]
        assert assistant(c,p,oid)['operation']['status']=='ready'
        assert '预览已生成' in assistant(c,p,oid)['content']
