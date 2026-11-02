import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.errors import AppError
from app.single_pass import apply_lut, describe_request, read_input


def invocation(tmp_path, images=1):
    folder = tmp_path/'in'
    folder.mkdir()
    paths = []
    for i in range(images):
        path = folder/f'{i}.png'
        pixels = np.zeros((30,40,4),dtype=np.uint8)
        pixels[:,:,:] = [180,75,30,123]
        Image.fromarray(pixels).save(path)
        paths.append(path)
    file = folder/'invocation.json'
    file.write_text(json.dumps({'schema_version':'oasn.invocation.v1','input':{
        'user_prompt':'柔和黑白','args':[],'attachments':[str(p) for p in paths]}},ensure_ascii=False))
    return file, paths


def test_formal_contract_real_pixels_alpha_originals_and_idempotency(tmp_path):
    file, images = invocation(tmp_path,2)
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in images]
    summary = describe_request(file)
    assert len(summary['photos']) == 2
    assert summary['photos'][0]['width'] == 40
    assert 'xmosaique-silver-mono' in {i['id'] for i in summary['luts']}
    out = tmp_path/'out'
    result = apply_lut(file,out,'xmosaique-silver-mono',1,'黑白')
    pixels = np.asarray(Image.open(out/result['photos'][0]['filename']))
    assert np.max(np.abs(pixels[:,:,0].astype(int)-pixels[:,:,1])) <= 2
    assert np.all(pixels[:,:,3] == 123)
    assert hashes == [hashlib.sha256(p.read_bytes()).hexdigest() for p in images]
    assert apply_lut(file,out,'xmosaique-silver-mono',1,'黑白') == result
    with pytest.raises(AppError,match='本次已生成结果'):
        apply_lut(file,out,'iwltbap-sedona',.5,'换风格')


@pytest.mark.parametrize('strength',[0,1.1,float('nan'),float('inf')])
def test_invalid_strength_cannot_write(tmp_path,strength):
    file,_=invocation(tmp_path)
    with pytest.raises(AppError):
        apply_lut(file,tmp_path/'out','iwltbap-sedona',strength,'说明')
    assert not (tmp_path/'out').exists()


def test_unknown_lut_and_foreign_attachment_rejected(tmp_path):
    file,images=invocation(tmp_path)
    with pytest.raises(AppError,match='不在当前可用库'):
        apply_lut(file,tmp_path/'out','invented',.5,'说明')
    payload=json.loads(file.read_text())
    payload['input']['attachments']=[str(tmp_path/'private.txt')]
    (tmp_path/'private.txt').write_text('not a photo')
    file.write_text(json.dumps(payload))
    with pytest.raises(AppError,match='本次调用'):
        read_input(file)
