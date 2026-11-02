"""Atomically publish visually accepted real-photo matches, preserving other styles."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pyvips
from backend.app.imaging import inspect, render
from backend.app.single_pass import catalog, load_catalog_processor
from backend.app.style_gallery import digest


def publish(approval):
    approval = Path(approval).resolve()
    selection = json.loads(approval.read_text())
    if not selection['items'] or any(r['decision'] != 'accepted' for r in selection['items']):
        raise ValueError('Only visually accepted matches can be published')
    store = ROOT/'data/style-gallery'
    previous_id = json.loads((store/'current.json').read_text())['id']
    previous_dir = store/'builds'/previous_id
    value = json.loads((previous_dir/'manifest.json').read_text())
    rows = {r['id']:r for r in catalog()}
    gallery = {r['id']:r for r in value['items']}
    samples_path = ROOT/'prototypes/lut-studio/style-samples.json'
    plan_path = ROOT/'prototypes/lut-studio/pilot-styles.json'
    samples = json.loads(samples_path.read_text())
    sample_map = {r['lut_id']:r for r in samples['items']}
    choices = json.loads(plan_path.read_text())
    choice_map = {r['id']:r for r in choices}
    build_id = uuid4().hex
    staging = store/'builds'/('.'+build_id)
    files = staging/'files'
    files.mkdir(parents=True)
    receipts = []
    try:
        for name, sha in value['assets'].items():
            source = previous_dir/'files'/name
            if Path(name).name != name or digest(source) != sha:
                raise ValueError('Previous asset checksum mismatch')
            shutil.copyfile(source,files/name)
        def register(path):
            inspect(path)
            value['assets'][path.name] = digest(path)
        def thumbnail(path):
            target = path.with_name(path.stem+'-thumb.jpg')
            pyvips.Image.thumbnail(str(path),360,height=540,size='down').jpegsave(str(target),Q=86,strip=True)
            register(target)
            return target.name
        for n, selected in enumerate(selection['items'],1):
            folder = (ROOT/selected['rendered_directory']).resolve()
            if not folder.is_relative_to(ROOT): raise ValueError('Invalid batch folder')
            manifest = json.loads((folder/'manifest.json').read_text())
            match = next(r for r in manifest['items'] if r['lut_id']==selected['lut_id'])
            row = rows[match['lut_id']]
            source = (ROOT/match['source']).resolve()
            result = folder/match['result']
            if (not source.is_relative_to(ROOT) or result.parent!=folder or
                digest(source)!=match['source_sha256'] or digest(result)!=match['result_sha256'] or
                row['sha256']!=match['lut_sha256'] or match['recipe']['lut']['strength']!=1.0 or
                manifest['additional_adjustments'] or gallery[row['id']].get('availability','ready')!='ready'):
                raise ValueError('Source, LUT, recipe, or result verification failed')
            scene = 'photo-'+hashlib.sha256(row['id'].encode()).hexdigest()[:16]
            original = files/f'{scene}-original.jpg'
            render(source,original,{},max_edge=960)
            register(original)
            scene_row={'id':scene,'name':match['subject'],'kind':'photograph','source_sha256':match['source_sha256'],
                       'author':match['author'],'source_url':match['source_url'],
                       'original':original.name,'thumbnail':thumbnail(original)}
            value['scenes']=[s for s in value['scenes'] if s['id']!=scene]+[scene_row]
            previews={}
            for strength in (50,100):
                target=files/f'{scene}-{strength}.jpg'
                if strength==100:
                    # Preserve the exact reviewed PNG pixels; JPEG thumbnails are only for cards.
                    target=files/f'{scene}-100.png'
                    shutil.copyfile(result,target)
                else:
                    recipe={'lut':{'id':row['id'],'name':row['name'],'sha256':row['sha256'],'strength':.5}}
                    render(source,target,recipe,max_edge=960,lut_processor=load_catalog_processor(row))
                register(target)
                previews[str(strength)]={'image':target.name,'thumbnail':thumbnail(target)}
            item=gallery[row['id']]
            item.update(sample_id=scene,previews={scene:previews},lut_sha256=row['sha256'],format=row['format'])
            copyname='real-'+match['source_sha256'][:20]+source.suffix
            copytarget=ROOT/samples['asset_directory']/copyname
            if not copytarget.exists():shutil.copyfile(source,copytarget)
            if digest(copytarget)!=match['source_sha256']:raise ValueError('Sample copy mismatch')
            sample_map[row['id']]={'id':scene,'lut_id':row['id'],'name':match['subject'],'kind':'photograph',
                'file':copyname,'sha256':match['source_sha256'],'author':match['author'],'source_url':match['source_url'],
                'source_frame':match.get('source_frame'),'source_note':match.get('source_note',''),
                'configured_at':datetime.now(timezone.utc).isoformat()}
            choice_map[row['id']]={k:item[k] for k in ('id','label','collection','category','tags')}
            receipts.append({**selected,'source_sha256':match['source_sha256'],'lut_sha256':row['sha256'],
                             'result_sha256':match['result_sha256'],'strength':1.0,'sample_id':scene})
            if n%25==0:print(f'Prepared {n}/{len(selection["items"])}',flush=True)
        value['items'].sort(key=lambda r:0 if r.get('sample_id') else 1)
        used={r.get('sample_id') for r in value['items']}
        value['scenes']=[s for s in value['scenes'] if s['id'] in used]
        # Only retain referenced assets in the new build; previous builds remain intact.
        names=set()
        for s in value['scenes']:names.update([s['original'],s['thumbnail']])
        for item in value['items']:
            names.update(e['image'] for e in item.get('story', {}).get('examples', []))
            for strengths in item['previews'].values():
                for pair in strengths.values():names.update(pair.values())
        for name in set(value['assets'])-names:
            (files/name).unlink();del value['assets'][name]
        value.update(id=build_id,previous_build_id=previous_id,created_at=datetime.now(timezone.utc).isoformat(),
            fingerprint=hashlib.sha256((value['fingerprint']+digest(approval)).encode()).hexdigest(),
            last_photo_batch=receipts,photo_batch_approval_sha256=digest(approval))
        value['lut_render_count']=sum(len(strengths) for r in value['items'] for strengths in r['previews'].values())
        value['pipeline_sha256']['scripts/publish_style_batch.py']=digest(Path(__file__))
        (staging/'manifest.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        if json.loads((store/'current.json').read_text())['id']!=previous_id:
            raise ValueError('Gallery changed during publication; retry against new build')
        staging.rename(store/'builds'/build_id)
        samples['items']=list(sample_map.values())
        samples_path.write_text(json.dumps(samples,ensure_ascii=False,indent=2)+'\n')
        plan_path.write_text(json.dumps(list(choice_map.values()),ensure_ascii=False,indent=2)+'\n')
        pointer=store/('.current-'+build_id);pointer.write_text(json.dumps({'id':build_id}))
        os.replace(pointer,store/'current.json')
        receipt={'id':build_id,'previous_id':previous_id,'published':len(receipts),
            'real_photo_luts':sum(s['kind']=='photograph' for s in samples['items']),
            'gallery_count':len(value['items']),'items':receipts}
        (approval.parent/'publication.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:v for k,v in receipt.items() if k!='items'},ensure_ascii=False),flush=True)
    finally:
        if staging.exists():shutil.rmtree(staging)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('approval',type=Path)
    publish(parser.parse_args().approval)
