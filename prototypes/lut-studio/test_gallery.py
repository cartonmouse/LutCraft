import json
from pathlib import Path
import shutil
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import create_app
import server
from backend.app import style_gallery as module
from backend.app.errors import AppError
from backend.app.single_pass import catalog

ROOT = Path(__file__).resolve().parents[2]
PHOTO = ROOT/'prototypes/lut-studio/assets/amalfi.jpg'
BUILD = 'a'*32
IDS = ['xmosaique-silver-mono', 'on1-free-photo-portrait1-01d43fd003', 'rawtherapee-fuji-velvia-50-e8e61b75']


@pytest.fixture
def setup(tmp_path):
    store=tmp_path/'styles';preview=tmp_path/'results'
    files=store/'builds'/BUILD/'files';files.mkdir(parents=True)
    shutil.copyfile(PHOTO, files/'sample.jpg')
    rows={r['id']:r for r in catalog()}
    value={'id':BUILD,'catalog_count':len(rows),'strengths':[50,100],
        'scenes':[{'id':s,'name':s,'original':'sample.jpg','thumbnail':'sample.jpg'} for s in ('portrait','landscape','street')],
        'items':[{'id':i,'label':rows[i]['name'],'collection':'Fixture','category':'color','tags':[],
            'lut_sha256':rows[i]['sha256'],'previews':{s:{str(n):{'image':'sample.jpg','thumbnail':'sample.jpg'} for n in (50,100)} for s in ('portrait','landscape','street')}} for i in IDS],
        'assets':{'sample.jpg':module.digest(PHOTO)}}
    (files.parent/'manifest.json').write_text(json.dumps(value))
    (store/'current.json').write_text(json.dumps({'id':BUILD}))
    app=create_app(preview,style_dir=store)
    with TestClient(app) as client:
        headers={'x-lut-preview-token':client.get('/api/styles').json()['token'],'x-photo-name':'test-photo.jpg'}
        yield store,preview,app,client,headers


def request(client,headers,lut=IDS[0],**kwargs):
    return client.post('/api/styles/apply',params={'build_id':BUILD,'lut_id':lut,'strength':kwargs.pop('strength',1)},
        headers=headers,content=kwargs.pop('content',PHOTO.read_bytes()),**kwargs)


def test_gallery_public_assets_and_page_routes(setup):
    store,preview,app,client,headers=setup
    data=client.get('/api/styles').json()
    assert data['status']=='ready' and len(data['items'])==3 and len(data['scenes'])==3
    assert str(store) not in json.dumps(data) and 'lut_sha256' not in json.dumps(data)
    assert client.get(data['scenes'][0]['original_url']).content==PHOTO.read_bytes()
    assert 'immutable' in client.get(data['scenes'][0]['original_url']).headers['cache-control']
    assert client.get('/api/styles').headers['cache-control']=='no-store'
    assert 'id="style-grid"' in client.get('/').text
    assert 'id="preview-grid"' in client.get('/results').text
    assert 'id="preview-grid"' in client.get('/?run='+BUILD).text
    prefix=f'/api/styles/{BUILD}/files/'
    for name in ('manifest.json','secret.png','../current.json'):
        assert client.get(prefix+name).status_code==404
    sample=store/'builds'/BUILD/'files/sample.jpg'
    sample.unlink();sample.symlink_to(PHOTO)
    assert client.get(prefix+'sample.jpg').status_code==404
    assert client.get('/api/manual/luts').json()['enabled'] is False
    assert client.post('/api/manual/apply',json={}).status_code==405


@pytest.mark.parametrize('lut',IDS)
def test_real_application_preserves_original_and_survives_restart(setup,lut):
    store,preview,app,client,headers=setup
    original=PHOTO.read_bytes()
    response=request(client,headers,lut)
    assert response.status_code==200,response.text
    result=response.json()
    assert client.get(result['original_url']).content==original
    graded=client.get(result['result_url'])
    assert graded.status_code==200 and graded.content.startswith(b'\xff\xd8\xff') and graded.content!=original
    assert not list((store/'uploads').iterdir())
    assert client.get('/api/preview').json()['gallery']['id']==result['run_id']
    assert client.get('/api/history').json()['total']==1
    receipt=json.loads((preview/'runs'/result['run_id']/'style-application.json').read_text())
    assert receipt['lut_id']==lut and receipt['source_sha256']==module.digest(PHOTO)
    with TestClient(create_app(preview,style_dir=store)) as restarted:
        assert restarted.get(result['result_url']).content==graded.content
        assert restarted.get('/api/history').json()['total']==1
    assert PHOTO.read_bytes()==original


def test_upload_validation_origin_limit_and_stale_lut(setup,monkeypatch):
    store,preview,app,client,headers=setup
    assert request(client,{}).status_code==403
    assert request(client,{**headers,'Origin':'https://elsewhere.invalid'}).status_code==403
    assert request(client,headers,strength=.75).status_code==422
    assert request(client,headers,lut='../../private').status_code==422
    assert request(client,headers,lut='not-in-pilot').status_code==404
    assert request(client,headers,content=b'').status_code==422
    assert request(client,headers,content=b'<html>not a photograph</html>').status_code==400
    assert request(client,headers,content=b'\xff\xd8\xffbroken').status_code==422
    monkeypatch.setattr(server,'MAX_UPLOAD',100)
    assert request(client,headers).status_code==413
    assert request(client,{**headers,'content-length':'0'}).status_code==413
    assert not list((store/'uploads').iterdir())
    assert not preview.exists()
    monkeypatch.setattr(server,'MAX_UPLOAD',10*1024*1024)
    manifest=store/'builds'/BUILD/'manifest.json'
    value=json.loads(manifest.read_text());value['items'][0]['lut_sha256']='0'*64;manifest.write_text(json.dumps(value))
    assert request(client,headers).status_code==409


def test_failure_and_busy_keep_previous_result(setup,monkeypatch):
    store,preview,app,client,headers=setup
    assert request(client,headers).status_code==200
    before=(preview/'current.json').read_bytes()
    app.state.style_gallery.lock.acquire()
    try: assert request(client,headers).status_code==409
    finally: app.state.style_gallery.lock.release()
    def fail(*args,**kwargs): raise AppError('render_failed','测试渲染失败',422)
    monkeypatch.setattr(module,'render',fail)
    assert request(client,headers).status_code==422
    assert (preview/'current.json').read_bytes()==before
    assert not list((store/'uploads').iterdir())
    assert not any(p.name.startswith('.') for p in (preview/'runs').iterdir())
    assert client.get('/api/history').json()['total']==1


def test_unillustrated_style_is_hidden_without_deleting_its_configuration(setup):
    store,preview,app,client,headers=setup
    manifest=store/'builds'/BUILD/'manifest.json'
    value=json.loads(manifest.read_text())
    value['items'][0].update(sample_id=None,previews={},availability='ready')
    manifest.write_text(json.dumps(value))
    assert IDS[0] not in {i['id'] for i in client.get('/api/styles').json()['items']}
    assert json.loads(manifest.read_text())==value
    response=request(client,headers)
    assert response.status_code==200,response.text
    assert client.get(response.json()['result_url']).status_code==200
    # Once its sample is configured, it is listed again without re-importing it.
    value['items'][0].update(sample_id='portrait',previews=value['items'][1]['previews'])
    manifest.write_text(json.dumps(value))
    assert IDS[0] in {i['id'] for i in client.get('/api/styles').json()['items']}


def test_detail_story_is_per_lut_and_exposes_only_public_fields(setup):
    store,preview,app,client,headers=setup
    manifest=store/'builds'/BUILD/'manifest.json'
    value=json.loads(manifest.read_text())
    value['items'][0]['story']={'headline':'光影之间','description':'细腻灰阶。','traits':['黑白'],
        'examples':[{'title':f'场景 {n}','caption':'真实效果。','image':'sample.jpg',
                     'source':'private/source.webp','source_url':'private-provenance',
                     'recipe':{'lut':{'strength':1.0}}} for n in range(3)]}
    manifest.write_text(json.dumps(value))
    data=client.get('/api/styles').json()
    story=data['items'][0]['story']
    assert story['headline']=='光影之间' and len(story['examples'])==3
    assert 'story' not in data['items'][1]
    assert 'private' not in json.dumps(data) and 'recipe' not in json.dumps(data)
    for example in story['examples']:
        assert example['strength']==100
        assert client.get(example['url']).content==PHOTO.read_bytes()


def test_unadapted_story_is_text_only_and_never_enters_renderer(tmp_path,monkeypatch):
    from scripts import style_story_assets as stories
    def unexpected(*args,**kwargs):
        pytest.fail('An unadapted story reached the renderer')
    monkeypatch.setattr(stories,'load_catalog_processor',unexpected)
    config=tmp_path/'stories.json'
    record={'lut_id':'pending','headline':'待适配风格','description':'效果待确认。','traits':['已收录'],'examples':[]}
    config.write_text(json.dumps({'items':[record]}))
    value={'items':[{'id':'pending','availability':'needs_profile'}],'pipeline_sha256':{},'assets':{}}
    stories.add_stories(value,tmp_path,config)
    assert value['items'][0]['story']['headline']=='待适配风格'
    assert value['items'][0]['story']['examples']==[] and not value['assets']
    record['examples']=[{'source':'unexpected.png'}]
    config.write_text(json.dumps({'items':[record]}))
    with pytest.raises(ValueError,match='Unadapted LUT'):
        stories.add_stories(value,tmp_path,config)


def test_unadapted_placeholder_cannot_render_or_create_history(setup,monkeypatch):
    store,preview,app,client,headers=setup
    manifest=store/'builds'/BUILD/'manifest.json'
    value=json.loads(manifest.read_text())
    value['items'][0].update(sample_id=None,previews={},availability='needs_profile',availability_note='照片适配待确认')
    manifest.write_text(json.dumps(value))
    def unexpected(*args,**kwargs):
        pytest.fail('Unadapted LUT reached the renderer')
    monkeypatch.setattr(module,'render',unexpected)
    response=request(client,headers)
    assert response.status_code==409 and '适配' in response.json()['detail']
    assert not preview.exists()
    assert IDS[0] not in {i['id'] for i in client.get('/api/styles').json()['items']}
    assert json.loads(manifest.read_text())==value
