"""Render a small, reproducible LUT gallery through the existing photo pipeline."""
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
from backend.app.style_gallery import DEFAULT_STYLE_STORE, digest
from scripts.style_story_assets import add_stories, STORIES

SAMPLES = ROOT / 'prototypes/lut-studio/style-samples.json'
PLAN = ROOT / 'prototypes/lut-studio/pilot-styles.json'


def build(samples=SAMPLES, plan=PLAN, store=DEFAULT_STYLE_STORE):
    source_manifest = json.loads(Path(samples).read_text())
    choices = json.loads(Path(plan).read_text())
    all_rows = {r['id']: r for r in catalog()}
    records = source_manifest['items']
    by_lut = {r['lut_id']: r for r in records}
    if len(by_lut) != len(records) or len({r['id'] for r in records}) != len(records):
        raise ValueError('Each LUT must have one distinct sample ID')
    if not by_lut or set(by_lut) - {r['id'] for r in choices}:
        raise ValueError('Sample LUT is missing from the pilot plan')
    choices = [r for r in choices if r['id'] in by_lut]
    rows = [all_rows[r['id']] for r in choices]
    source_root = (ROOT/source_manifest['asset_directory']).resolve()
    if not source_root.is_relative_to(ROOT):
        raise ValueError('Samples must be stored in the project')
    sources = {}
    for choice in choices:
        record = by_lut[choice['id']]
        path = (source_root/record['file']).resolve()
        if path.parent != source_root or digest(path) != record['sha256']:
            raise ValueError('Selected sample checksum/path mismatch: '+record['id'])
        sources[record['id']] = (path, record['sha256'])
    # Different LUTs may share an input photo; each retains its own sample ID
    # and independently rendered previews, with the source checksum recorded.
    recipe_signature = {str(p.relative_to(ROOT)): digest(p) for p in [
        ROOT/'backend/app/imaging.py', ROOT/'backend/app/luts.py', ROOT/'backend/app/clf.py',
        ROOT/'backend/app/hald.py', ROOT/'scripts/build_style_gallery.py', ROOT/'scripts/style_story_assets.py']}
    fingerprint = hashlib.sha256(json.dumps({'sources': source_manifest, 'plan': choices,
        'stories': digest(STORIES) if STORIES.exists() else None,
        'luts': [r['sha256'] for r in rows], 'pipeline': recipe_signature, 'strengths': [.5,1], 'edge': 960}, sort_keys=True).encode()).hexdigest()
    store = Path(store)
    current = store/'current.json'
    if current.exists():
        prior = json.loads((store/'builds'/json.loads(current.read_text())['id']/'manifest.json').read_text())
        folder = store/'builds'/prior['id']/'files'
        if prior['fingerprint'] == fingerprint and all((folder/f).is_file() and digest(folder/f)==h for f,h in prior['assets'].items()):
            print('Existing gallery verified; no rerender required.', flush=True)
            return prior
    build_id = uuid4().hex
    staging = store/'builds'/('.'+build_id)
    files = staging/'files'
    files.mkdir(parents=True)
    value = {'schema_version':2, 'mode':'dedicated-samples', 'id':build_id, 'fingerprint':fingerprint, 'created_at':datetime.now(timezone.utc).isoformat(),
        'catalog_count':len(all_rows), 'strengths':[50,100], 'scenes':[], 'items':[], 'assets':{},
        'pipeline_sha256':recipe_signature, 'preview_max_edge':960, 'lut_render_count':0}
    def register(path):
        inspect(path)
        value['assets'][path.name] = digest(path)
    def thumbnail(path):
        target = path.with_name(path.stem+'-thumb.jpg')
        pyvips.Image.thumbnail(str(path), 360, height=540, size='down').jpegsave(str(target), Q=86, strip=True)
        register(target)
        return target.name
    try:
        for scene, (source, sha) in sources.items():
            target = files/f'{scene}-original.jpg'
            render(source, target, {}, max_edge=960)
            register(target)
            record = next(r for r in records if r['id'] == scene)
            value['scenes'].append({'id':scene,'name':record['name'],'kind':record['kind'],
                'source_sha256':sha, 'original':target.name, 'thumbnail':thumbnail(target)})
        for choice, row in zip(choices, rows):
            cpu = load_catalog_processor(row)
            scene = by_lut[choice['id']]['id']
            source, sha = sources[scene]
            item = {**choice, 'sample_id':scene, 'lut_sha256':row['sha256'], 'format':row['format'], 'previews':{scene:{}}}
            for strength in (50,100):
                target = files/f'{scene}-{row["id"]}-{strength}.jpg'
                render(source, target, {'lut':{'id':row['id'],'name':row['name'],'sha256':row['sha256'],'strength':strength/100}}, max_edge=960, lut_processor=cpu)
                register(target)
                item['previews'][scene][str(strength)] = {'image':target.name,'thumbnail':thumbnail(target)}
                value['lut_render_count'] += 1
            value['items'].append(item)
            print(f'{len(value["items"])}/{len(rows)} {choice["label"]}', flush=True)
        add_stories(value, files)
        assert all(digest(path)==sha for path,sha in sources.values())
        (staging/'manifest.json').write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
        staging.rename(store/'builds'/build_id)
        pointer = store/('.current-'+build_id)
        pointer.write_text(json.dumps({'id':build_id}))
        os.replace(pointer,current)
        print(f'Published {len(rows)} styles / {value["lut_render_count"]} LUT previews; {len(value["assets"])} verified image files.', flush=True)
        return value
    finally:
        if staging.exists(): shutil.rmtree(staging)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--samples',type=Path,default=SAMPLES)
    parser.add_argument('--plan',type=Path,default=PLAN)
    parser.add_argument('--store',type=Path,default=DEFAULT_STYLE_STORE)
    args = parser.parse_args()
    build(args.samples,args.plan,args.store)
