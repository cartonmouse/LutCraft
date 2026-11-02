import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.schemas import Recipe
from app import luts
from test_app import client, create, photo, wait


def cube(size=17, swap=False):
    # .cube indexes red fastest; swapping red/blue makes ordering errors visible.
    rows = [f'TITLE "{"Swap" if swap else "Identity"}"', f'LUT_3D_SIZE {size}', 'DOMAIN_MIN 0 0 0', 'DOMAIN_MAX 1 1 1']
    for b in range(size):
        for g in range(size):
            for r in range(size):
                values = (b, g, r) if swap else (r, g, b)
                rows.append(' '.join(f'{v / (size - 1):.7f}' for v in values))
    return ('\n'.join(rows) + '\n').encode()


@pytest.mark.parametrize('size', [16, 25, 40, 64])
def test_bundled_archive_grids_preserve_channel_order_and_upload_boundary(tmp_path, size):
    raw=cube(size,swap=True)
    assert luts.inspect_cube(raw,bundled=True)['grid_size']==size
    with pytest.raises(luts.AppError):
        luts.inspect_cube(raw)
    path=tmp_path/'bundled.cube'
    path.write_bytes(raw)
    cpu=luts.processor(str(path),hashlib.sha256(raw).hexdigest(),luts.ocio.__version__)
    pixels=np.array([[.1,.2,.8],[0,1,.25],[1,0,0]],dtype=np.float32)
    expected=pixels[:,::-1].copy()
    cpu.applyRGB(pixels)
    np.testing.assert_allclose(pixels,expected,atol=2e-6)


def upload(c, data=None):
    r = c.post('/api/luts', data={'color_space': 'srgb'}, files={'file': ('test.cube', data or cube(), 'text/plain')})
    assert r.status_code == 200, r.text
    return r.json()


def state(c, p):
    return c.get('/api/projects/' + p['id']).json()


def preview(c, p, **extra):
    p = state(c, p)
    r = c.post(f"/api/projects/{p['id']}/previews", json={
        'context_revision': p['revision'], 'target_asset_ids': p['selected'], **extra})
    assert r.status_code == 200, r.text
    op = wait(c, r.json()['operation_id'])
    assert op['status'] == 'ready', op
    return op


def apply(c, op):
    r = c.post('/api/operations/' + op['id'] + '/apply')
    assert r.status_code == 200, r.text
    return wait(c, op['id'], ('succeeded', 'partial_failed', 'failed'))


def image(c, url):
    return np.asarray(Image.open(io.BytesIO(c.get(url).content)))


@pytest.mark.parametrize('size', [13, 17, 32, 33, 65])
def test_import_grid_dedup_and_restart(client, size):
    c = client
    data = cube(size)
    lut = upload(c, data)
    assert lut['import_status'] == 'imported'
    assert lut['grid_size'] == size
    assert lut['sha256'] == hashlib.sha256(data).hexdigest()
    duplicate = upload(c, data)
    assert duplicate['id'] == lut['id'] and duplicate['import_status'] == 'existing'
    assert len(c.get('/api/luts').json()) == 1
    assert 'file_ref' not in lut and 'owner' not in lut
    p = create(c, 1)
    op = preview(c, p, lut_action={'op': 'select', 'id': lut['id'], 'strength': 1})
    assert np.abs(image(c, op['preview_url']).astype(int) - image(c, p['assets'][0]['original_url']).astype(int)).max() <= 1


def test_local_catalog_import_and_render(client):
    """Exercise one bundled CUBE per uploadable grid through the legacy importer.

    CLF/Hald transforms use the catalog loader, not the CUBE upload endpoint.
    Full catalog integrity and source coverage belong to the offline verifier.
    """
    from app.config import ROOT
    root = ROOT / 'lut-library'
    catalog = root / 'catalog.json'
    if not catalog.exists():
        pytest.skip('Local LUT catalog not installed')
    entries = json.loads(catalog.read_text())['items']
    uploadable = {entry['technical']['grid_size']: entry for entry in entries
                  if Path(entry['path']).suffix == '.cube' and entry['technical']['grid_size'] in (13,17,32,33,65)}
    entries = list(uploadable.values())
    if not all((root / entry['path']).is_file() for entry in entries):
        pytest.skip('Local LUT binaries not installed')
    c = client
    p = create(c, 1)
    for entry in entries:
        data = (root / entry['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry['original_sha256']
        imported = c.post('/api/luts', data={'color_space': 'srgb'}, files={'file': (entry['filename'], data)}).json()
        assert imported['import_status'] == 'imported', imported
        assert imported['grid_size'] == entry['technical']['grid_size']
        op = preview(c, p, lut_action={'op': 'select', 'id': imported['id'], 'strength': .5})
        assert image(c, op['preview_url']).shape == image(c, p['assets'][0]['original_url']).shape
        again = c.post('/api/luts', data={'color_space': 'srgb'}, files={'file': ('renamed.cube', data)}).json()
        assert again['import_status'] == 'existing' and again['id'] == imported['id']
    assert len(c.get('/api/luts').json()) == len(entries)


@pytest.mark.parametrize('data', [b'not a cube', b'LUT_1D_SIZE 17\n0 0 0', b'LUT_3D_SIZE 2\n',
    b'LUT_3D_SIZE 17\n0 0 0', b'LUT_3D_SIZE 17\nNaN 0 0', b'LUT_3D_SIZE 17\ninf 0 0',
    b'LUT_3D_SIZE 17\nDOMAIN_MAX 2 2 2', b'TITLE "unterminated', b'LUT_3D_SIZE 17\nSOURCE_FILE /etc/passwd', b'x' * (10 * 1024 * 1024 + 1)])
def test_bad_cube_no_half_asset(client, data):
    c = client
    r = c.post('/api/luts', data={'color_space': 'srgb'}, files={'file': ('bad.cube', data)})
    assert r.status_code == 400, r.text
    assert c.get('/api/luts').json() == []
    assert not list(c.app.state.service.settings.data.glob('luts/*/source.cube'))


def test_cube_space_and_action_validation(client):
    c = client
    assert c.post('/api/luts', data={'color_space': 'log'}, files={'file': ('a.cube', cube())}).status_code == 400
    p = create(c, 1)
    for action in [{'op': 'select'}, {'op': 'clear', 'strength': .2}, {'op': 'strength'}, {'op': 'strength', 'strength': 1.1}]:
        r = c.post(f"/api/projects/{p['id']}/previews", json={'context_revision': p['revision'], 'target_asset_ids': p['selected'], 'lut_action': action})
        assert r.status_code == 422
    with pytest.raises(ValidationError):
        Recipe.model_validate({'schema_version': 3})


def test_identity_strength_oracle_alpha_and_original(client):
    c = client
    p = c.post('/api/projects', json={'name': 'Color oracle'}).json()
    pixels = np.array([[[20, 80, 220, 0], [210, 70, 30, 77], [64, 128, 192, 255]]], dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format='PNG')
    p = c.post(f"/api/projects/{p['id']}/assets", files={'files': ('rgba.png', buf.getvalue(), 'image/png')}).json()['project']
    aid = p['selected'][0]
    digest = hashlib.sha256(c.get(f'/api/assets/{aid}/files/original').content).hexdigest()
    identity = upload(c)
    op = preview(c, p, lut_action={'op': 'select', 'id': identity['id'], 'strength': 1})
    assert np.abs(image(c, op['preview_url']).astype(int) - pixels).max() <= 1
    swapped = upload(c, cube(swap=True))
    basics = [{'field': 'exposure_ev', 'op': 'set', 'value': .2}]
    op = preview(c, p, adjustments=basics, lut_action={'op': 'clear'})
    base = image(c, op['preview_url'])
    for strength in [0, .5, 1]:
        op = preview(c, p, lut_action={'op': 'select', 'id': swapped['id'], 'strength': strength})
        actual = image(c, op['preview_url'])
        expected = np.rint((1-strength)*base[:, :, :3].astype(float) + strength*base[:, :, [2, 1, 0]].astype(float))
        assert np.abs(actual[:, :, :3].astype(float) - expected).max() <= 1
        assert np.array_equal(actual[:, :, 3], pixels[:, :, 3])
        if strength == 0:
            assert np.array_equal(actual, base)
    op = apply(c, op)
    assert op['status'] == 'succeeded'
    assert np.array_equal(image(c, op['items'][0]['result_url']), actual)
    assert hashlib.sha256(c.get(f'/api/assets/{aid}/files/original').content).hexdigest() == digest
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(c.get(op['download_url']).content)).read('manifest.json'))
    ref = manifest['items'][0]['recipe']['lut']
    assert ref['name'] == 'Swap' and ref['sha256'] == swapped['sha256'] and ref['strength'] == 1
    assert 'file_ref' not in json.dumps(manifest)


def test_preserve_per_photo_basics_and_reset_scope(client):
    c = client
    p = create(c, 3)
    s = c.app.state.service
    with s.db.connect(write=True) as db:
        for index, a in enumerate(p['assets']):
            recipe = Recipe(exposure_ev=index / 2, warmth=index / 5).model_dump()
            db.execute('UPDATE assets SET recipe_json=? WHERE id=?', (json.dumps(recipe), a['id']))
    lut = upload(c, cube(swap=True))
    op = preview(c, p, lut_action={'op': 'select', 'id': lut['id'], 'strength': .4})
    assert [i['recipe']['exposure_ev'] for i in op['items']] == [0, .5, 1]
    assert apply(c, op)['status'] == 'succeeded'
    p = state(c, p)
    p = c.put(f"/api/projects/{p['id']}/preferences", json={'context_revision': p['revision'], 'value': '保留暖色偏好'}).json()
    messages = p['messages']
    r = c.post(f"/api/projects/{p['id']}/reset-preview", json={'context_revision': p['revision'], 'target_asset_ids': [p['selected'][1]]})
    op = wait(c, r.json()['operation_id'])
    assert op['items'][0]['recipe'] == Recipe().model_dump()
    assert apply(c, op)['status'] == 'succeeded'
    assert apply(c, op)['status'] == 'succeeded'
    after = state(c, p)
    assert [a['revision'] for a in after['assets']] == [1, 2, 1]
    assert after['assets'][0]['recipe']['lut']['strength'] == .4
    assert after['assets'][1]['recipe']['lut'] is None
    assert after['preferences'] == p['preferences'] and after['messages'][:len(messages)] == messages


def test_reset_previews_viewed_photo_and_restores_color_only_after_apply(client):
    c = client
    p = create(c, 4)
    original_pixels = {a['id']: image(c, a['original_url']) for a in p['assets']}
    assert apply(c, preview(c, p, preset_id='mono'))['status'] == 'succeeded'
    p = state(c, p)
    fourth = p['assets'][3]['id']
    p = c.patch(f"/api/projects/{p['id']}/workspace", json={
        'context_revision': p['revision'], 'selected_asset_ids': p['selected'],
        'viewed_asset_id': fourth,
    }).json()
    response = c.post(f"/api/projects/{p['id']}/reset-preview", json={
        'context_revision': p['revision'], 'target_asset_ids': p['selected'],
    })
    assert response.status_code == 200, response.text
    op = wait(c, response.json()['operation_id'])
    assert op['status'] == 'ready'
    assert op['preview_asset_id'] == fourth
    assert np.array_equal(image(c, op['preview_url']), original_pixels[fourth])
    assert all(i['recipe'] == Recipe().model_dump() for i in op['items'])
    # Previewing must not silently replace the user's applied black-and-white images.
    pending = state(c, p)
    assert all(a['recipe']['saturation'] == 0 for a in pending['assets'])
    grey = image(c, pending['assets'][3]['result_url'])
    assert np.array_equal(grey[:, :, 0], grey[:, :, 1])
    assert apply(c, op)['status'] == 'succeeded'
    for asset in state(c, p)['assets']:
        assert asset['recipe'] == Recipe().model_dump()
        assert np.array_equal(image(c, asset['result_url']), original_pixels[asset['id']])
        assert np.array_equal(image(c, asset['original_url']), original_pixels[asset['id']])


def test_preview_falls_back_to_selected_photo_when_viewed_photo_is_outside_scope(client):
    c = client
    p = create(c, 3)
    response = c.post(f"/api/projects/{p['id']}/reset-preview", json={
        'context_revision': p['revision'], 'target_asset_ids': p['selected'][1:],
    })
    assert response.status_code == 200, response.text
    op = wait(c, response.json()['operation_id'])
    assert op['status'] == 'ready'
    assert op['preview_asset_id'] == p['assets'][1]['id']
    assert {i['asset_id'] for i in op['items']} == set(p['selected'][1:])


def test_resized_rgba_lut_preserves_alpha(client):
    c = client
    p = c.post('/api/projects', json={'name': 'RGBA resize'}).json()
    data = photo((50, 90, 150, 77), mode='RGBA', size=(2700, 1800))
    p = c.post(f"/api/projects/{p['id']}/assets", files={'files': ('large.png', data, 'image/png')}).json()['project']
    baseline = image(c, p['assets'][0]['original_url'])
    lut = upload(c, cube(swap=True))
    op = preview(c, p, lut_action={'op': 'select', 'id': lut['id'], 'strength': .5})
    actual = image(c, op['preview_url'])
    assert actual.shape[1] == 1280 and np.array_equal(actual[:, :, 3], baseline[:, :, 3])
    op = apply(c, op)
    assert op['status'] == 'succeeded'
    result = image(c, op['items'][0]['result_url'])
    assert result.shape[1] == 2560 and np.all(result[:, :, 3] == 77)


def save(c, p, name='My style', revision=None):
    p = state(c, p)
    a = p['assets'][0]
    return c.post('/api/personal-presets', json={'name': name, 'project_id': p['id'], 'asset_id': a['id'], 'asset_revision': a['revision'] if revision is None else revision})


def test_preset_snapshot_rename_delete_and_cross_project(client):
    c = client
    p = create(c, 1)
    lut = upload(c, cube(swap=True))
    op = preview(c, p, preset_id='warm', lut_action={'op': 'select', 'id': lut['id'], 'strength': .65})
    assert save(c, p).status_code == 409
    assert apply(c, op)['status'] == 'succeeded'
    assert save(c, p, revision=0).status_code == 409
    r = save(c, p, '  My style  ')
    assert r.status_code == 200, r.text
    preset = r.json()
    assert preset['name'] == 'My style' and preset['recipe']['lut']['strength'] == .65
    assert save(c, p).status_code == 409
    assert save(c, p, '   ').status_code == 422
    p2 = create(c, 2)
    op = preview(c, p2, personal_preset_id=preset['id'])
    assert all(i['recipe'] == preset['recipe'] for i in op['items'])
    assert c.patch('/api/personal-presets/' + preset['id'], json={'name': 'Renamed', 'revision': 1}).status_code == 409
    renamed = c.patch('/api/personal-presets/' + preset['id'], json={'name': 'Renamed', 'revision': 0})
    assert renamed.status_code == 200
    assert c.delete('/api/personal-presets/' + preset['id']).status_code == 200
    assert c.get('/api/personal-presets').json() == []
    assert apply(c, op)['status'] == 'succeeded'
    p2 = state(c, p2)
    assert p2['preferences'] == {}
    assert all(a['recipe'] == preset['recipe'] for a in p2['assets'])
    assert c.get(op['preview_url']).status_code == 200
    # A deleted preset cannot become a new recipe source; existing snapshots remain valid.
    r = c.post(f"/api/projects/{p2['id']}/previews", json={'context_revision': p2['revision'], 'target_asset_ids': p2['selected'], 'personal_preset_id': preset['id']})
    assert r.status_code == 404


def test_libraries_owner_isolation(client):
    c = client
    p = create(c, 1)
    lut = upload(c)
    preset = save(c, p).json()
    cookie = c.cookies.get('lut_session')
    c.cookies.clear()
    other = create(c, 1)
    assert c.get('/api/luts').json() == []
    assert c.get('/api/personal-presets').json() == []
    for extra in [{'lut_action': {'op': 'select', 'id': lut['id']}}, {'personal_preset_id': preset['id']}]:
        r = c.post(f"/api/projects/{other['id']}/previews", json={'context_revision': other['revision'], 'target_asset_ids': other['selected'], **extra})
        assert r.status_code == 404
    assert c.delete('/api/personal-presets/' + preset['id']).status_code == 404
    assert c.patch('/api/personal-presets/' + preset['id'], json={'name': 'X', 'revision': 0}).status_code == 404
    c.cookies.clear()
    c.cookies.set('lut_session', cookie)
    assert len(c.get('/api/luts').json()) == 1


def test_missing_corrupt_lut_and_engine_no_silent_fallback(client, monkeypatch):
    c = client
    p = create(c, 1)
    lut = upload(c)
    op = apply(c, preview(c, p, lut_action={'op': 'select', 'id': lut['id'], 'strength': 1}))
    assert op['status'] == 'succeeded'
    file = c.app.state.service.path(f"luts/{lut['id']}/source.cube")
    contents = file.read_bytes()
    for corrupt in [True, False]:
        if corrupt:
            file.write_bytes(b'changed')
        else:
            file.unlink()
        p = state(c, p)
        r = c.post(f"/api/projects/{p['id']}/previews", json={'context_revision': p['revision'], 'target_asset_ids': p['selected']})
        assert r.status_code == 409
        assert c.get(op['download_url']).status_code == 200
    file.write_bytes(contents)
    monkeypatch.setattr(luts, 'ocio', None)
    assert not c.get('/api/health').json()['lut_engine']['available']
    p = state(c, p)
    r = c.post(f"/api/projects/{p['id']}/previews", json={'context_revision': p['revision'], 'target_asset_ids': p['selected']})
    assert r.status_code == 503
    cleared = preview(c, p, lut_action={'op': 'clear'})
    assert apply(c, cleared)['status'] == 'succeeded'


def test_lut_partial_retry_retains_snapshot(client, monkeypatch):
    c = client
    p = create(c, 3)
    lut = upload(c, cube(swap=True))
    op = preview(c, p, lut_action={'op': 'select', 'id': lut['id'], 'strength': .37})
    import app.service as module
    real = module.imaging.render
    def fail(source, target, *args):
        if p['assets'][1]['id'] in str(target):
            raise RuntimeError('injected second-photo failure')
        return real(source, target, *args)
    monkeypatch.setattr(module.imaging, 'render', fail)
    assert apply(c, op)['status'] == 'partial_failed'
    monkeypatch.setattr(module.imaging, 'render', real)
    r = c.post('/api/operations/' + op['id'] + '/retry')
    retry = wait(c, r.json()['operation_id'])
    assert len(retry['items']) == 1
    assert retry['items'][0]['recipe'] == op['items'][1]['recipe']
    assert apply(c, retry)['status'] == 'succeeded'


def test_v1_migration_backup_and_lut_persistence(tmp_path):
    settings = Settings(tmp_path, 'migration-secret')
    with TestClient(create_app(settings)) as c:
        p = create(c, 1)
        finished = apply(c, preview(c, p, preset_id='warm'))
        pending = preview(c, p, preset_id='mono')
        cookie = c.cookies.get('lut_session')
    path = tmp_path / 'lut.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE personal_presets')
        db.execute('DROP TABLE luts')
        db.execute('PRAGMA user_version=0')
        for table in ['assets', 'operation_items']:
            for rowid, encoded in db.execute(f'SELECT rowid,recipe_json FROM {table}').fetchall():
                recipe = json.loads(encoded)
                recipe['schema_version'] = 1
                recipe.pop('lut')
                db.execute(f'UPDATE {table} SET recipe_json=? WHERE rowid=?', (json.dumps(recipe), rowid))
    with TestClient(create_app(settings)) as c:
        c.cookies.set('lut_session', cookie)
        after = state(c, p)
        assert after['assets'][0]['recipe']['schema_version'] == 2
        assert after['assets'][0]['recipe']['lut'] is None
        assert c.get(f"/api/operations/{pending['id']}").json()['status'] == 'stale'
        assert c.get(finished['download_url']).status_code == 200
        backups = list((tmp_path / 'backups').glob('before-v2-*.sqlite3'))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute('PRAGMA user_version').fetchone()[0] == 0
            assert json.loads(backup.execute('SELECT recipe_json FROM assets').fetchone()[0])['schema_version'] == 1
        lut = upload(c)
        preset = save(c, p).json()
    with TestClient(create_app(settings)) as c:
        c.cookies.set('lut_session', cookie)
        assert c.get('/api/luts').json()[0]['id'] == lut['id']
        assert c.get('/api/personal-presets').json()[0]['id'] == preset['id']
        assert len(list((tmp_path / 'backups').glob('before-v2-*.sqlite3'))) == 1
