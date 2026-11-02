import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import create_app
from test_server import completed_job
from backend.app import manual_lut_preview as manual
from backend.app.errors import AppError
from backend.app.preview_gallery import publish_jobs


def setup(tmp_path):
    store = tmp_path / 'viewer'
    original = publish_jobs([completed_job(tmp_path)], store, names=['海岸样片'])
    app = create_app(store, manual_enabled=True)
    client = TestClient(app)
    options = client.get('/api/manual/luts', params={'source_run_id': original['id'], 'photo_id': 'photo-01'}).json()
    headers = {'X-LUT-Preview-Token': options['token']}
    request = {'source_run_id': original['id'], 'photo_id': 'photo-01', 'lut_id': 'xmosaique-silver-mono', 'strength': .5}
    return store, app, client, options, headers, request


@pytest.mark.parametrize('kind', ['cube', 'clf', 'hald'])
def test_manual_real_render_original_preservation_cache_and_restart(tmp_path, monkeypatch, kind):
    store, app, client, options, headers, request = setup(tmp_path)
    from backend.app.single_pass import catalog
    assert options['count'] == len(catalog())
    assert str(tmp_path) not in json.dumps(options)
    if kind == 'clf':
        request['lut_id'] = next(x['id'] for x in options['items'] if x['name'].startswith('Pocket Action 富士'))
    elif kind == 'hald':
        request['lut_id'] = next(x['id'] for x in options['items'] if x['name'] == 'RawTherapee Agfa APX 100')
    current = (store / 'current.json').read_bytes()
    original = store / 'runs' / request['source_run_id'] / 'files/01-original.jpg'
    source_bytes = original.read_bytes()
    response = client.post('/api/manual/apply', json=request, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert not data['cache_hit'] and len(data['gallery']['photos']) == 1
    assert str(tmp_path) not in response.text
    photo = data['gallery']['photos'][0]
    image = client.get('/' + photo['result_url'])
    assert image.status_code == 200 and image.content.startswith(b'\xff\xd8\xff')
    assert image.content != source_bytes
    assert client.get('/' + photo['original_url']).content == source_bytes
    assert original.read_bytes() == source_bytes and (store / 'current.json').read_bytes() == current
    assert client.get('/api/history').json()['total'] == 2
    # Repeating from the NEW result must still use the preserved original and
    # the same cache, rather than stacking another LUT on the graded pixels.
    monkeypatch.setattr(manual, 'render', lambda *a, **k: pytest.fail('Repeated request re-rendered'))
    request['source_run_id'] = data['run_id']
    repeat = client.post('/api/manual/apply', json=request, headers=headers).json()
    assert repeat['cache_hit'] and repeat['run_id'] == data['run_id']
    with TestClient(create_app(store, manual_enabled=True)) as restarted:
        after = restarted.get('/api/manual/luts', params={'source_run_id': request['source_run_id'], 'photo_id': 'photo-01'}).json()
        assert after['successful_count'] == 1
        selected = next(x for x in after['items'] if x['id'] == request['lut_id'])
        assert selected['tested_strengths'] == [.5]


def test_manual_rejects_cross_origin_paths_invalid_values_and_parallel_work(tmp_path):
    store, app, client, options, headers, request = setup(tmp_path)
    assert client.post('/api/manual/apply', json=request).status_code == 403
    assert client.post('/api/manual/apply', json=request, headers={**headers, 'Origin': 'https://unrelated.example'}).status_code == 403
    for change in ({'strength': 0}, {'strength': 1.01}, {'path': '/private/photo.jpg'}, {'source_run_id': '../private'}):
        assert client.post('/api/manual/apply', json={**request, **change}, headers=headers).status_code == 422
    assert client.post('/api/manual/apply', json={**request, 'photo_id': 'photo-99'}, headers=headers).status_code == 404
    assert client.post('/api/manual/apply', json={**request, 'lut_id': 'missing'}, headers=headers).status_code == 404
    service = app.state.manual_preview
    service.lock.acquire()
    try:
        assert client.post('/api/manual/apply', json=request, headers=headers).status_code == 409
    finally:
        service.lock.release()
    assert len(list((store / 'runs').iterdir())) == 1


def test_failure_is_recorded_and_preserves_existing_gallery(tmp_path, monkeypatch):
    store, app, client, options, headers, request = setup(tmp_path)
    before = (store / 'current.json').read_bytes()
    def fail(*a, **k):
        raise AppError('lut_changed', 'LUT 文件校验失败，已停止调色。')
    monkeypatch.setattr(manual, 'load_catalog_processor', fail)
    response = client.post('/api/manual/apply', json=request, headers=headers)
    assert response.status_code == 400 and '校验失败' in response.json()['detail']
    after = client.get('/api/manual/luts', params={'source_run_id': request['source_run_id'], 'photo_id': 'photo-01'}).json()
    assert next(x for x in after['items'] if x['id'] == request['lut_id'])['last_status'] == 'failed'
    assert (store / 'current.json').read_bytes() == before
    assert not any(p.name.startswith('.') for p in (store / 'runs').iterdir())


def test_feature_can_be_disabled_and_original_symlink_is_rejected(tmp_path):
    store, app, client, options, headers, request = setup(tmp_path)
    with TestClient(create_app(store, manual_enabled=False)) as disabled:
        assert disabled.get('/api/health').json()['mode'] == 'style-gallery'
        assert not disabled.get('/api/manual/luts').json()['enabled']
        assert disabled.post('/api/manual/apply', json=request, headers=headers).status_code == 405
    original = store / 'runs' / request['source_run_id'] / 'files/01-original.jpg'
    outside = tmp_path / 'outside.jpg'
    outside.write_bytes(original.read_bytes())
    original.unlink(); original.symlink_to(outside)
    assert client.post('/api/manual/apply', json=request, headers=headers).status_code == 404
