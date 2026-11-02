"""Compare LUT paths in separate processes with the same synthetic photo fixture."""
import io
import json
import platform
import resource
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from fastapi.testclient import TestClient
from PIL import Image
from app.config import Settings
from app.main import create_app
from app import luts
from benchmark import wait
from make_demo_luts import cube


def worker(size, fixture):
    report = {'mode': size, 'input_bytes_each': fixture.stat().st_size}
    with tempfile.TemporaryDirectory() as d, TestClient(create_app(Settings(Path(d), 'benchmark-lut'))) as c:
        p = c.post('/api/projects', json={'name': 'LUT benchmark'}).json()
        start = time.perf_counter()
        r = c.post(f"/api/projects/{p['id']}/assets", files=[('files', (f'{i}.jpg', fixture.read_bytes(), 'image/jpeg')) for i in range(10)])
        assert all(f['status'] == 'succeeded' for f in r.json()['files'])
        p = r.json()['project']
        report['upload_10_s'] = round(time.perf_counter() - start, 3)
        action = None
        if size != 'none':
            data = cube(int(size))
            start = time.perf_counter()
            r = c.post('/api/luts', data={'color_space': 'srgb'}, files={'file': ('warm.cube', data)})
            assert r.status_code == 200, r.text
            report['lut_validate_store_compile_s'] = round(time.perf_counter() - start, 3)
            action = {'op': 'select', 'id': r.json()['id'], 'strength': .6}
            luts.processor.cache_clear()
            luts.ocio.ClearAllCaches()
        for kind in ['cold', 'cached']:
            p = c.get('/api/projects/' + p['id']).json()
            start = time.perf_counter()
            r = c.post(f"/api/projects/{p['id']}/previews", json={
                'context_revision': p['revision'], 'target_asset_ids': p['selected'],
                'preset_id': 'warm', 'lut_action': action})
            assert r.status_code == 200, r.text
            oid = r.json()['operation_id']
            wait(c, oid, ('ready',))
            report[f'{kind}_preview_s'] = round(time.perf_counter() - start, 3)
        start = time.perf_counter()
        c.post('/api/operations/' + oid + '/apply').raise_for_status()
        op = wait(c, oid, ('succeeded', 'partial_failed'))
        assert op['status'] == 'succeeded', op
        report['batch_10_s'] = round(time.perf_counter() - start, 3)
        start = time.perf_counter()
        data = c.get('/api/operations/' + oid + '/download.zip').content
        assert len(zipfile.ZipFile(io.BytesIO(data)).namelist()) == 11
        report['zip_s'] = round(time.perf_counter() - start, 3)
        divisor = 1024 * 1024 if sys.platform == 'darwin' else 1024
        report['process_peak_rss_mib'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor, 1)
    print(json.dumps(report))


def main():
    if len(sys.argv) > 1:
        return worker(sys.argv[1], Path(sys.argv[2]))
    report = {'machine': platform.machine(), 'python': platform.python_version(),
              'fixture': 'Same 2400x1600 synthetic JPEG, 10 copies; LUT strength 60%; separate processes; no model/network latency',
              'engine': luts.engine_status(), 'measurements': []}
    with tempfile.TemporaryDirectory() as d:
        fixture = Path(d) / 'noise.jpg'
        Image.effect_noise((2400, 1600), 35).convert('RGB').save(fixture, 'JPEG', quality=88)
        for size in ('none', '33', '65'):
            result = subprocess.run([sys.executable, __file__, size, str(fixture)], capture_output=True, text=True, check=True)
            report['measurements'].append(json.loads(result.stdout))
    output = ROOT / 'data/benchmark-luts.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(output.read_text())


if __name__ == '__main__':
    main()
