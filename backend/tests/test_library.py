import hashlib
import json
import sqlite3
import time
from unittest.mock import AsyncMock
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.embeddings import Embeddings
from app.errors import AppError
from app.library_schemas import SearchIntent
from app.main import create_app
from app.schemas import Plan
from test_app import client, create, wait
from test_luts import cube, state


def add(c, name="柔和", tags=None, space="srgb", raw=None, salt=""):
    data = cube() + f"# {name}{salt}\n".encode()
    metadata = {"description": "、".join(tags or []), "tags": tags or [], **(raw or {})}
    response = c.post('/api/luts', data={'color_space': space, 'name': name, 'metadata': json.dumps(metadata)}, files={'file': ('test.cube', data)})
    assert response.status_code == 200, response.text
    return response.json()


def profile(c, lut):
    return c.get(f"/api/luts/{lut['id']}/metadata").json()


def edit(c, lut, **values):
    return c.patch(f"/api/luts/{lut['id']}/metadata", json={'revision': profile(c,lut)['revision'], **values})


def job_done(c, lut):
    for _ in range(200):
        p = profile(c, lut)
        if p['job'] and p['job']['status'] not in ('queued', 'running'):
            return p
        time.sleep(.01)
    pytest.fail(str(p))


def search(c, query, pid=None, **extra):
    r = c.post('/api/luts/search', json={'query': query, 'project_id': pid, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_metadata_unknown_import_and_user_confirmation(client):
    c=client
    lut=add(c, tags=['低饱和'], space='unknown')
    p=create(c,1)
    assert not search(c,'低饱和')['candidates']
    r=c.post(f"/api/projects/{p['id']}/previews",json={'context_revision':p['revision'],'target_asset_ids':p['selected'],'lut_action':{'op':'select','id':lut['id']}})
    assert r.status_code==409
    assert edit(c,lut,compatibility='confirmed').status_code==400
    r=edit(c,lut,compatibility='confirmed',metadata={'input_space':'srgb','output_space':'srgb','compatibility_basis':'作者资料确认'})
    assert r.status_code==200
    assert r.json()['evidence']['compatibility']['source']=='user'
    assert search(c,'低饱和')['candidates'][0]['id']==lut['id']
    assert job_done(c,lut)['job']['stage']=='keyword_ready'


def test_metadata_review_revision_and_digest_guards(client):
    c=client
    lut=add(c,tags=['柔和'])
    p=job_done(c,lut)
    assert p['analysis']['sample_count']==249
    assert p['analysis']['out_of_range_fraction']==0
    assert edit(c,lut,metadata={'description':'我的描述','tags':['冷色']}).status_code==200
    c.post(f"/api/luts/{lut['id']}/analyze")
    p=job_done(c,lut)
    assert p['metadata']['description']=='我的描述'
    assert p['evidence']['description']['source']=='user'
    assert c.patch(f"/api/luts/{lut['id']}/metadata",json={'revision':0,'metadata':{'description':'旧值'}}).status_code==409
    assert edit(c,lut,metadata={'recommended_strength':.5}).status_code==400
    assert edit(c,lut,accept_suggestions=['description']).status_code==200
    assert profile(c,lut)['evidence']['description']['source']=='measured'
    raw={'original_sha256':'0'*64}
    assert c.post('/api/luts',data={'color_space':'srgb','metadata':json.dumps(raw)},files={'file':('wrong.cube',cube())}).status_code==400
    assert len(c.get('/api/luts').json())==1


def test_catalog_hash_match_and_manual_edit_preservation(client):
    from app.config import ROOT
    c=client
    rows=json.loads((ROOT/'lut-library/catalog.json').read_text())['items']
    row=rows[0]
    path=ROOT/'lut-library'/row['path']
    if not path.exists(): pytest.skip('Local binary missing')
    data=path.read_bytes()
    r=c.post('/api/luts',data={'color_space':'srgb','metadata':'{}'},files={'file':('renamed.cube',data)})
    assert r.status_code==200,r.text
    lut=r.json()
    assert profile(c,lut)['metadata']['description']==row['style_zh']
    assert profile(c,lut)['evidence']['origin']['catalog_id']==row['id']
    edit(c,lut,metadata={'description':'人工修订'})
    c.post('/api/luts',data={'color_space':'srgb'},files={'file':('again.cube',data)})
    assert profile(c,lut)['metadata']['description']=='人工修订'
    assert hashlib.sha256(data).hexdigest()==row['original_sha256']


@pytest.mark.parametrize('query,excluded',[('复古但不要黑白','黑白'),('清新但不要太黄','偏黄')])
def test_negation_and_search_explanations(client,query,excluded):
    c=client
    good=add(c,'清淡胶片',['清新','低饱和','复古'])
    bad=add(c,'另一款',['清新','复古',excluded])
    result=search(c,query)
    assert result['mode']=='keyword_fallback'
    assert result['candidates'][0]['id']==good['id']
    assert result['candidates'][0]['reasons']
    if excluded=='黑白': assert all(i['id']!=bad['id'] for i in result['candidates'])
    else: assert next(i for i in result['candidates'] if i['id']==bad['id'])['conflicts']==['偏黄']


def test_generic_style_words_do_not_recommend_unrelated_luts(client):
    c=client
    good=add(c,'暖调电影',['暖色'])
    add(c,'红外风格黑白',['黑白'])
    assert [i['id'] for i in search(c,'暖调青橙电影风格')['candidates']]==[good['id']]


def test_no_match_exact_name_scope_and_disabled(client):
    c=client
    lut=add(c,'Aspen',['柔和','冷色'])
    assert search(c,'找一个',exact_name='不存在')['status']=='no_match'
    assert search(c,'海底荧光')['status']=='no_match'
    assert c.post('/api/luts/search',json={'query':'暖色','project_id':''}).status_code==422
    assert search(c,'去路人再暖色')['status']=='no_match'
    assert search(c,'aspen',exact_name='aspen')['candidates'][0]['id']==lut['id']
    edit(c,lut,enabled=False)
    assert not search(c,'aspen')['candidates']
    c.cookies.clear()
    assert c.get(f"/api/luts/{lut['id']}/metadata").status_code==404
    assert c.patch(f"/api/luts/{lut['id']}/metadata",json={'revision':0}).status_code==404
    assert c.post(f"/api/luts/{lut['id']}/analyze").status_code==404
    assert not search(c,'柔和')['candidates']


def test_candidate_preview_reuse_and_staleness(client):
    c=client
    lut=add(c,tags=['清新'])
    p=create(c,2)
    found=search(c,'清新',p['id'])
    body={'search_id':found['search_id'],'lut_id':lut['id'],'context_revision':p['revision'],'target_asset_ids':p['selected'],'strength':.5}
    r=c.post(f"/api/projects/{p['id']}/candidate-preview",json=body)
    assert r.status_code==200,r.text
    op=wait(c,r.json()['operation_id'])
    assert op['items'][0]['recipe']['lut']['strength']==.5
    p=state(c,p)
    assert all(a['recipe']['lut'] is None for a in p['assets'])
    assert p['lut_search']['search_id']==found['search_id']
    body['context_revision']=p['revision']
    edit(c,lut,metadata={'tags':['冷色']})
    assert c.post(f"/api/projects/{p['id']}/candidate-preview",json=body).status_code==409


def test_snapshot_invalidated_by_workspace_and_cross_project(client):
    c=client; lut=add(c,tags=['柔和']); p=create(c,2); other=create(c,1)
    found=search(c,'柔和',p['id'])
    body={'search_id':found['search_id'],'lut_id':lut['id'],'context_revision':other['revision'],'target_asset_ids':other['selected']}
    assert c.post(f"/api/projects/{other['id']}/candidate-preview",json=body).status_code==409
    c.patch(f"/api/projects/{p['id']}/workspace",json={'context_revision':p['revision'],'selected_asset_ids':[p['selected'][0]],'viewed_asset_id':p['viewed']})
    assert state(c,p)['lut_search'] is None


def configure_fake(s,monkeypatch):
    s.settings.embedding_provider='compatible'
    s.settings.embedding_url='https://embedding.example/embeddings'
    s.settings.embedding_model='test-model'
    s.settings.embedding_dimensions=3
    monkeypatch.setattr(s.embeddings,'embed_documents',lambda texts: np.array([[1,0,0] if '柔和' in t else [0,1,0] for t in texts],dtype=np.float32))
    monkeypatch.setattr(s.embeddings,'embed_query',lambda text: np.array([1,0,0],dtype=np.float32))


def test_vector_index_hybrid_uncalibrated_and_fallback(client,monkeypatch):
    c=client; s=c.app.state.service; configure_fake(s,monkeypatch)
    lut=add(c,tags=['柔和'])
    assert job_done(c,lut)['index_status']=='ready'
    result=search(c,'像春日空气一样')
    assert result['mode']=='hybrid'
    assert result['status']=='needs_clarification'  # No invented universal similarity threshold.
    s.settings.embedding_min_similarity=.8
    assert search(c,'像春日空气一样')['status']=='ok'
    monkeypatch.setattr(s.embeddings,'embed_query',lambda text: (_ for _ in ()).throw(AppError('embedding_network','模拟不可用',503)))
    result=search(c,'柔和')
    assert result['mode']=='keyword_fallback' and result['candidates'][0]['id']==lut['id']
    assert result['message']=='模拟不可用'
    s.settings.embedding_version='new-generation'
    assert profile(c,lut)['index_status']=='pending'
    assert search(c,'柔和')['mode']=='keyword_fallback'


def test_stale_vector_write_cannot_replace_new_metadata(client,monkeypatch):
    c=client; s=c.app.state.service
    lut=add(c,tags=['柔和']); job_done(c,lut); configure_fake(s,monkeypatch)
    called=[]
    def embeds(texts):
        if not called:
            called.append(True)
            with s.db.connect(write=True) as db:
                db.execute('UPDATE lut_profiles SET revision=revision+1 WHERE lut_id=?',(lut['id'],))
        return np.array([[1,0,0]],dtype=np.float32)
    monkeypatch.setattr(s.embeddings,'embed_documents',embeds)
    c.post(f"/api/luts/{lut['id']}/analyze")
    assert job_done(c,lut)['job']['status']=='stale'
    with s.db.connect() as db:
        assert db.execute('SELECT count(*) FROM lut_embeddings').fetchone()[0]==0


def test_embedding_http_contract_and_invalid_vectors(tmp_path,monkeypatch):
    settings=Settings(tmp_path,'s',embedding_provider='compatible',embedding_url='https://example.com/embeddings',embedding_model='example',embedding_dimensions=3,embedding_query_prefix='query: ')
    real=httpx.Client
    calls=[]
    def respond(request):
        payload=json.loads(request.content); calls.append(payload)
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[2,0,0]} for i in reversed(range(len(payload['input'])))]})
    monkeypatch.setattr('app.embeddings.httpx.Client',lambda **kwargs: real(transport=httpx.MockTransport(respond),**kwargs))
    embed=Embeddings(settings)
    assert np.array_equal(embed.embed_query('柔和'),[1,0,0])
    assert calls[-1]['input']==['query: 柔和']
    assert calls[-1]['dimensions']==3
    assert embed.embed_documents(['A','B']).shape==(2,3)
    for values in [[[0,0,0]], [[float('nan'),1,0]], [[1,2]]]:
        with pytest.raises(AppError): embed.normalize(values,1,3)


def test_fixed_dimension_endpoint_omits_parameter_but_validates_response(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('EMBEDDING_PROVIDER','compatible')
    monkeypatch.setenv('EMBEDDING_API_URL','https://example.com/embeddings')
    monkeypatch.setenv('EMBEDDING_MODEL','BAAI/bge-m3')
    monkeypatch.setenv('EMBEDDING_DIMENSIONS','1024')
    monkeypatch.setenv('EMBEDDING_SEND_DIMENSIONS','false')
    settings=Settings.load()
    assert settings.embedding_send_dimensions is False
    real=httpx.Client
    dimensions=[1024]
    def respond(request):
        payload=json.loads(request.content)
        assert 'dimensions' not in payload
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[1.0]*dimensions[0]} for i in range(len(payload['input']))]})
    monkeypatch.setattr('app.embeddings.httpx.Client',lambda **kwargs: real(transport=httpx.MockTransport(respond),**kwargs))
    embed=Embeddings(settings)
    assert embed.embed_documents(['暖色','冷色']).shape==(2,1024)
    dimensions[0]=768
    with pytest.raises(AppError) as exc:
        embed.embed_query('柔和')
    assert exc.value.code=='embedding_format'


def test_configured_search_bypass_does_not_claim_unconfigured(client,monkeypatch):
    c=client; s=c.app.state.service; lut=add(c,name='柔和',tags=['柔和'])
    job_done(c,lut)
    s.settings.embedding_provider='compatible'
    s.settings.embedding_url='https://example.com/embeddings'
    s.settings.embedding_model='BAAI/bge-m3'
    def unexpected_query(*args):
        pytest.fail('Exact names and unsupported edits should not call embeddings')
    monkeypatch.setattr(s.embeddings,'embed_query',unexpected_query)
    found=search(c,'查找柔和',exact_name='柔和')
    assert found['candidates'][0]['id']==lut['id'] and found['message'] is None
    missing=search(c,'查找不存在',exact_name='不存在')
    assert missing['status']=='no_match' and '尚未配置' not in missing['message']
    unsupported=search(c,'抠图')
    assert unsupported['status']=='no_match' and unsupported['candidates']==[]
    assert 'LUT 无法执行' in unsupported['message']


def test_direct_two_stage_selects_real_candidate_and_preserves_params(client):
    c=client; s=c.app.state.service; lut=add(c,tags=['柔和']); p=create(c,2)
    async def plan(context):
        if not context.get('search_complete'):
            return Plan(status='search',message='检索柔和风格',search_intent=SearchIntent(query='柔和'))
        found=context['lut_candidates']
        return Plan(status='ready',message='试用这款',lut_action={'op':'select','id':found['candidates'][0]['id'],'strength':.6},search_id=found['search_id'])
    s.model.plan=plan
    r=c.post(f"/api/projects/{p['id']}/instructions",json={'context_revision':p['revision'],'request_id':'two-stage-01','text':'选中照片用柔和风格'})
    assert r.status_code==200,r.text
    op=wait(c,r.json()['operation_id'])
    assert op['items'][0]['recipe']['lut']['id']==lut['id']
    assert op['items'][0]['recipe']['saturation']==1
    assert all(a['recipe']['lut'] is None for a in state(c,p)['assets'])
    p=state(c,p)
    s.model.plan=AsyncMock(return_value=Plan(status='ready',message='调强度',lut_action={'op':'strength','strength':.3}))
    r=c.post(f"/api/projects/{p['id']}/instructions",json={'context_revision':p['revision'],'request_id':'strength-01','text':'第2张强度30%'})
    op=wait(c,r.json()['operation_id'])
    assert len(op['items'])==1 and op['items'][0]['ordinal']==2 and op['items'][0]['recipe']['lut']['strength']==.3


def test_direct_no_match_and_forged_selection(client):
    c=client; s=c.app.state.service; lut=add(c,tags=['暖色']); p=create(c,1)
    s.model.plan=AsyncMock(return_value=Plan(status='search',message='检索',search_intent=SearchIntent(query='水下荧光')))
    r=c.post(f"/api/projects/{p['id']}/instructions",json={'context_revision':p['revision'],'request_id':'no-match-01','text':'水下荧光'})
    assert r.json()['status']=='clarify' and s.model.plan.await_count==1
    assert state(c,p)['operations']==[]
    s.model.plan=AsyncMock(return_value=Plan(status='ready',message='随便选',lut_action={'op':'select','id':lut['id']}))
    r=c.post(f"/api/projects/{p['id']}/instructions",json={'context_revision':p['revision'],'request_id':'forged-01','text':'随便选一个'})
    assert r.status_code==409 and state(c,p)['operations']==[]


def test_v3_migration_preserves_images_and_marks_legacy(tmp_path):
    settings=Settings(tmp_path,'secret')
    with TestClient(create_app(settings)) as c:
        p=create(c,1); lut=add(c,tags=['暖色']); cookie=c.cookies.get('lut_session')
    path=tmp_path/'lut.sqlite3'
    with sqlite3.connect(path) as db:
        for table in ['lut_search_runs','lut_embeddings','lut_index_jobs','lut_profiles']:
            db.execute(f'DROP TABLE {table}')
        db.execute('PRAGMA user_version=3')
    with TestClient(create_app(settings)) as c:
        c.cookies.set('lut_session',cookie)
        assert state(c,p)['assets']==p['assets']
        assert profile(c,lut)['evidence']['compatibility']['review']=='legacy_declaration'
        assert profile(c,lut)['metadata']['tags']==[]
    backups=list((tmp_path/'backups').glob('before-v4-*'))
    assert len(backups)==1


def test_reimport_suggestions_preserve_manual_text_and_file_provenance(client):
    c=client
    lut=add(c, tags=['柔和']); job_done(c,lut)
    edit(c,lut,metadata={'description':'人工保留'}); job_done(c,lut)
    again=add(c,tags=['冷色'],raw={'description':'新资料的描述'})
    assert again['id']==lut['id']
    p=profile(c,lut)
    assert p['metadata']['description']=='人工保留'
    assert p['suggestions']['description']=='新资料的描述'
    assert edit(c,lut,accept_suggestions=['description']).status_code==200
    assert profile(c,lut)['evidence']['description']['source']=='file'


def test_ambiguous_name_unverified_skin_and_broken_file(client):
    c=client; s=c.app.state.service
    a=add(c,'同名',['冷色']); b=add(c,'同名',['冷色'],salt='other')
    result=search(c,'同名',exact_name='同名')
    assert result['status']=='needs_clarification' and len(result['candidates'])==2
    assert all(i['requires_review'] for i in result['candidates'])
    assert search(c,'冷调但保持肤色自然')['status']=='needs_clarification'
    with s.db.connect() as db:
        row=s.luts.get(db,a['id'],db.execute('SELECT owner FROM luts WHERE id=?',(a['id'],)).fetchone()[0])
    s.path(row['file_ref']).write_text('corrupted')
    assert [i['id'] for i in search(c,'冷色')['candidates']]==[b['id']]


def test_direct_lut_and_explicit_memory_share_valid_candidate(client):
    c=client; s=c.app.state.service; lut=add(c,tags=['柔和']); p=create(c,1)
    async def plan(context):
        if not context['search_complete']:
            return Plan(status='search',message='检索',search_intent=SearchIntent(query='柔和'))
        return Plan(status='ready',message='生成柔和预览',
                    search_id=context['lut_candidates']['search_id'],
                    lut_action={'op':'select','id':lut['id'],'strength':.5},
                    memory_actions=[{'op':'set','key':'style_preference','value':'喜欢柔和'}])
    s.model.plan=plan
    r=c.post(f"/api/projects/{p['id']}/instructions",json={'context_revision':p['revision'],'request_id':'memory-lut-01','text':'调成柔和，记住我喜欢柔和'})
    assert r.status_code==200,r.text
    assert wait(c,r.json()['operation_id'])['status']=='ready'
    current=state(c,p)
    assert current['preferences']['style_preference']=='喜欢柔和'
    assert current['assets'][0]['recipe']['lut'] is None
    assert current['lut_search']


def test_direct_recommendation_message_is_not_replaced_by_memory(client):
    c=client; s=c.app.state.service; p=create(c,1)
    s.model.plan=AsyncMock(return_value=Plan(status='ready',message='可以先试用低饱和方向。'))
    r=c.post(f"/api/projects/{p['id']}/instructions",json={'context_revision':p['revision'],'request_id':'advice-01','text':'先推荐一个方向'})
    assert r.json()['message']=='可以先试用低饱和方向。'


def test_ordinal_candidate_choice_uses_current_snapshot_and_selection(client):
    c=client; s=c.app.state.service; p=create(c,2)
    add(c,'柔和 A',['柔和']); add(c,'柔和 B',['柔和'])
    found=search(c,'柔和',p['id'])
    s.model.plan=AsyncMock(side_effect=AssertionError('Ordinal choices must not use historical model guesses'))
    r=c.post(f"/api/projects/{p['id']}/instructions",json={'context_revision':p['revision'],'request_id':'choice-01','text':'换第二个候选，先预览。'})
    assert r.status_code==200,r.text
    op=wait(c,r.json()['operation_id'])
    assert len(op['items'])==2
    assert all(i['recipe']['lut']['id']==found['candidates'][1]['id'] for i in op['items'])
    p=state(c,p)
    r=c.post(f"/api/projects/{p['id']}/instructions",json={'context_revision':p['revision'],'request_id':'choice-02','text':'换第六个'})
    assert r.json()['status']=='clarify'
    s.model.plan.assert_not_called()
