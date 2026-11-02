import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import create_app
from backend.app.errors import AppError
from backend.app.preview_gallery import publish_jobs

ROOT = Path(__file__).resolve().parents[2]
IMAGE = ROOT / 'prototypes/lut-studio/assets/amalfi.jpg'


def completed_job(tmp_path):
    job = tmp_path / 'job'
    (job / 'input/files').mkdir(parents=True)
    (job / 'output').mkdir()
    source = job / 'input/files/photo.jpg'
    shutil.copyfile(IMAGE, source)
    shutil.copyfile(IMAGE, job / 'output/photo-01-graded.jpg')
    (job / 'input/invocation.json').write_text(json.dumps({'input':{'user_prompt':'自然柔和','attachments':[str(source)]}}))
    (job / 'output/result.json').write_text(json.dumps({'status':'completed','lut':{'name':'Fixture LUT','strength':.5},
        'photos':[{'index':1,'filename':'photo-01-graded.jpg','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]}))
    return job


def test_viewer_is_readonly_and_waits_without_results(tmp_path):
    with TestClient(create_app(tmp_path / 'viewer')) as client:
        assert client.get('/api/preview').json() == {'status':'waiting','gallery':None}
        assert client.get('/api/health').json()['mode'] == 'style-gallery'
        assert client.get('/api/manual/luts').json() == {'enabled': False, 'items': [], 'count': 0}
        assert client.post('/api/manual/apply', json={}).status_code == 405
        for endpoint in ('/api/jobs','/api/chat','/api/preview'):
            response = client.post(endpoint,json={'style':'black and white'})
            assert response.status_code == 405
        assert not (tmp_path/'viewer').exists()


def test_published_gallery_survives_restart_and_contains_only_allowed_images(tmp_path):
    job = completed_job(tmp_path)
    store = tmp_path/'viewer'
    published = publish_jobs([job], store, names=['海岸小镇'])
    for _ in range(2):
        with TestClient(create_app(store)) as client:
            response = client.get('/api/preview')
            assert str(tmp_path) not in response.text
            gallery = response.json()['gallery']
            assert gallery['id'] == published['id']
            assert gallery['photos'][0]['name'] == '海岸小镇'
            for key in ('original_url','result_url'):
                image = client.get('/'+gallery['photos'][0][key])
                assert image.status_code == 200 and image.content[:3] == b'\xff\xd8\xff'
            assert client.get('/api/previews/'+published['id']).json()['gallery'] == gallery
            prefix = '/api/previews/'+published['id']+'/files/'
            for name in ('gallery.json','result.json','.env','invocation.json','other.jpg'):
                assert client.get(prefix+name).status_code == 404
            assert client.get('/api/previews/'+'a'*32).status_code == 404
            assert client.get('/api/previews/invalid').status_code == 404


def test_failed_publication_does_not_replace_last_valid_gallery(tmp_path):
    job = completed_job(tmp_path)
    store = tmp_path/'viewer'
    published = publish_jobs([job],store)
    (job/'output/photo-01-graded.jpg').write_bytes(b'changed')
    with pytest.raises(AppError,match='校验失败'):
        publish_jobs([job],store)
    with TestClient(create_app(store)) as client:
        assert client.get('/api/preview').json()['gallery']['id'] == published['id']
    assert not any(p.name.startswith('.') for p in (store/'runs').iterdir())


def test_file_symlink_cannot_escape_gallery(tmp_path):
    job = completed_job(tmp_path)
    store = tmp_path/'viewer'
    published = publish_jobs([job],store)
    target = store/'runs'/published['id']/'files/01-graded.jpg'
    target.unlink()
    target.symlink_to(job/'output/photo-01-graded.jpg')
    with TestClient(create_app(store)) as client:
        assert client.get(f'/api/previews/{published["id"]}/files/01-graded.jpg').status_code == 404


def test_history_orders_pages_and_keeps_old_batch_accessible(tmp_path):
    job = completed_job(tmp_path)
    store = tmp_path/'viewer'
    older = publish_jobs([job],store,names=['早些时候的海岸'])
    newer = publish_jobs([job],store,names=['后来的海岸'])
    for record,date in ((older,'2026-10-29T10:00:00+08:00'),(newer,'2026-10-29T04:00:00+00:00')):
        path = store/'runs'/record['id']/'gallery.json'
        value = json.loads(path.read_text());value['created_at']=date
        path.write_text(json.dumps(value))
    for _ in range(2):
        with TestClient(create_app(store)) as client:
            first = client.get('/api/history?limit=1').json()
            assert first['total'] == 2 and first['next_offset'] == 1
            assert first['items'][0]['id'] == newer['id']
            assert first['current_id'] == newer['id']
            assert first['items'][0]['photo_count'] == 1
            assert first['items'][0]['lut_names'] == ['Fixture LUT']
            assert str(tmp_path) not in json.dumps(first)
            cover = client.get('/'+first['items'][0]['cover_url'])
            assert cover.status_code == 200 and cover.content[:3] == b'\xff\xd8\xff'
            second = client.get('/api/history?limit=1&offset=1').json()
            assert second['items'][0]['id'] == older['id'] and second['next_offset'] is None
            old_preview = client.get('/api/previews/'+older['id']).json()['gallery']
            assert old_preview['photos'][0]['name'] == '早些时候的海岸'
            assert client.get('/api/preview').json()['gallery']['id'] == newer['id']


def test_history_skips_incomplete_or_unreadable_records(tmp_path):
    store = tmp_path/'viewer'
    record = publish_jobs([completed_job(tmp_path)],store)
    staging = store/'runs'/('.'+'b'*32)
    staging.mkdir();(staging/'gallery.json').write_text('incomplete')
    broken = store/'runs'/('c'*32)
    broken.mkdir();(broken/'gallery.json').write_text('not json')
    linked = store/'runs'/('d'*32)
    linked.symlink_to(store/'runs'/record['id'],target_is_directory=True)
    with TestClient(create_app(store)) as client:
        data = client.get('/api/history').json()
        assert data['total'] == 1 and data['unavailable_count'] == 1
        assert [item['id'] for item in data['items']] == [record['id']]


def test_history_empty_state_and_page_bounds(tmp_path):
    with TestClient(create_app(tmp_path/'viewer')) as client:
        data = client.get('/api/history').json()
        assert data == {'total':0,'next_offset':None,'current_id':None,'unavailable_count':0,'items':[]}
        for query in ('limit=0','limit=51','offset=-1'):
            assert client.get('/api/history?'+query).status_code == 422
        assert client.post('/api/history',json={}).status_code == 405
