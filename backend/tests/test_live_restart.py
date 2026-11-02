"""Crash/restart a disposable server, never the user's running workspace."""
import io
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image
from test_luts import cube


@pytest.mark.parametrize('with_lut', [False, True])
def test_real_process_interruption_retains_successes(tmp_path, with_lut):
    root = Path(__file__).resolve().parents[2]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'DATA_DIR': str(tmp_path), 'SESSION_SECRET': 'isolated-restart-test'}
    command = [sys.executable, '-m', 'uvicorn', 'app.main:app', '--app-dir', str(root/'backend'), '--host', '127.0.0.1', '--port', str(port)]
    process = None
    client = httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=30)

    def start():
        proc = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if client.get('/api/health').status_code == 200:
                    return proc
            except httpx.TransportError:
                pass
            if proc.poll() is not None:
                raise RuntimeError('Disposable test server failed to start')
            time.sleep(.05)
        proc.kill(); proc.wait()
        raise TimeoutError('Disposable test server did not start')

    try:
        process = start()
        stream = io.BytesIO()
        Image.effect_noise((2400,1600),35).convert('RGB').save(stream, 'JPEG', quality=88)
        p = client.post('/api/projects', json={'name':'crash test'}).json()
        p = client.post('/api/projects/'+p['id']+'/assets',files=[('files',(f'{i}.jpg',stream.getvalue(),'image/jpeg')) for i in range(10)]).json()['project']
        lut_action = None
        if with_lut:
            lut = client.post('/api/luts', data={'color_space': 'srgb'}, files={'file': ('identity.cube', cube())}).json()
            lut_action = {'op': 'select', 'id': lut['id'], 'strength': .6}
        oid = client.post('/api/projects/'+p['id']+'/previews',json={'context_revision':p['revision'],'target_asset_ids':p['selected'],'preset_id':'warm', 'lut_action': lut_action}).json()['operation_id']
        for _ in range(100):
            op=client.get('/api/operations/'+oid).json()
            if op['status']=='ready':break
            time.sleep(.02)
        assert op['status']=='ready'
        client.post('/api/operations/'+oid+'/apply').raise_for_status()
        successes=0
        for _ in range(200):
            op=client.get('/api/operations/'+oid).json()
            successes=sum(i['status']=='succeeded' for i in op['items'])
            if 0<successes<10:break
            time.sleep(.01)
        assert 0<successes<10
        process.kill();process.wait(timeout=5)
        process=start()
        op=client.get('/api/operations/'+oid).json()
        assert op['status']=='interrupted'
        restored=sum(i['status']=='succeeded' for i in op['items'])
        assert successes<=restored<10
        assert all(i['status'] in ('succeeded','interrupted') for i in op['items'])
        retry = client.post('/api/operations/'+oid+'/retry')
        assert retry.status_code==200
        retry_id = retry.json()['operation_id']
        for _ in range(100):
            new = client.get('/api/operations/' + retry_id).json()
            if new['status'] == 'ready': break
            time.sleep(.02)
        assert new['status'] == 'ready'
        assert len(new['items']) == 10 - restored
        if with_lut:
            assert all(i['recipe']['lut']['id'] == lut['id'] and i['recipe']['lut']['strength'] == .6 for i in new['items'])
    finally:
        client.close()
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
