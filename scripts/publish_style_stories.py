"""Add detail stories to the current gallery without rerendering its cards."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.style_gallery import digest
from scripts.style_story_assets import add_stories


def activate(build_id):
    store = ROOT / 'data/style-gallery'
    if len(build_id) != 32 or any(c not in '0123456789abcdef' for c in build_id):
        raise ValueError('Invalid build ID')
    folder = store / 'builds' / build_id
    value = json.loads((folder / 'manifest.json').read_text())
    if json.loads((store / 'current.json').read_text())['id'] != value['previous_build_id']:
        raise ValueError('Active gallery changed after preparation')
    if digest(ROOT / 'prototypes/lut-studio/style-stories.json') != value['story_config_sha256']:
        raise ValueError('Story configuration changed after preparation')
    for name, sha in value['assets'].items():
        if Path(name).name != name or digest(folder / 'files' / name) != sha:
            raise ValueError('Prepared asset mismatch')
    pointer = store / ('.current-' + build_id)
    pointer.write_text(json.dumps({'id': build_id}))
    os.replace(pointer, store / 'current.json')
    print(json.dumps({'activated': build_id, 'stories': sum('story' in i for i in value['items'])}))


def publish(prepare=False, base=None):
    store = ROOT / 'data/style-gallery'
    previous_id = json.loads((store / 'current.json').read_text())['id']
    if base and (len(base) != 32 or any(c not in '0123456789abcdef' for c in base)):
        raise ValueError('Invalid base ID')
    prior = store / 'builds' / (base or previous_id)
    value = json.loads((prior / 'manifest.json').read_text())
    build_id = uuid4().hex
    staging = store / 'builds' / ('.' + build_id)
    files = staging / 'files'
    files.mkdir(parents=True)
    try:
        for name, sha in value['assets'].items():
            source = prior / 'files' / name
            if Path(name).name != name or digest(source) != sha:
                raise ValueError('Existing gallery asset mismatch')
            shutil.copyfile(source, files / name)
        add_stories(value, files)
        value.update(id=build_id, previous_build_id=previous_id,
                     created_at=datetime.now(timezone.utc).isoformat())
        value['fingerprint'] = digest(ROOT / 'prototypes/lut-studio/style-stories.json') + ':' + build_id
        (staging / 'manifest.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        if json.loads((store / 'current.json').read_text())['id'] != previous_id:
            raise ValueError('Gallery changed while publishing stories')
        staging.rename(store / 'builds' / build_id)
        if not prepare:
            activate(build_id)
        print(json.dumps({'id': build_id, 'stories': sum('story' in i for i in value['items'])}))
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--base')
    parser.add_argument('--activate')
    args = parser.parse_args()
    activate(args.activate) if args.activate else publish(args.prepare, args.base)
