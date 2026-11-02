"""Publish catalog placeholders while preserving every existing sample image."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def publish(root=ROOT):
    library = root / 'lut-library'
    registry_bytes = (library / 'intake-catalog.json').read_bytes()
    registry = json.loads(registry_bytes)
    runtime = {r['id']: r for r in json.loads((library / 'catalog.json').read_text())['items']}
    store = root / 'data/style-gallery'
    current = json.loads((store / 'current.json').read_text())['id']
    previous = json.loads((store / 'builds' / current / 'manifest.json').read_text())
    signature = hashlib.sha256(registry_bytes).hexdigest()
    if previous.get('source_registry_sha256') == signature:
        return {'id': current, 'count': len(previous['items']), 'unchanged': True}
    existing = {r['id']: r for r in previous['items'] if r.get('sample_id') and r.get('previews')}
    rows = []
    for entry in registry['entries']:
        if not entry['gallery_visible']:
            continue
        uid = entry['runtime_id'] or entry['source_id']
        if uid in existing:
            rows.append({**existing[uid], 'availability': 'ready'})
            continue
        active = runtime.get(uid)
        label = active['name'] if active else entry['name'].replace('_', ' ')
        collection = active['publisher'] if active else entry['publisher']
        for prefix in (collection + ' ', 'RawTherapee '):
            label = label.removeprefix(prefix)
        tags = active.get('tags', []) if active else []
        mono = '黑白' in tags or (active or {}).get('category') == 'black-and-white' or bool(re.search(r'(^|[ _-])(bw|mono|monochrome)([ _-]|$)', label, re.I))
        rows.append({'id': uid, 'label': label, 'collection': collection,
            'category': 'mono' if mono else 'color', 'tags': tags,
            'sample_id': None, 'previews': {}, 'availability': entry['status'],
            'availability_note': entry['reason'], 'lut_sha256': active['technical']['sha256'] if active else None,
            'format': active['technical']['lut_type'] if active else entry['format']})
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate gallery identifiers')
    prior_order = {r['id']: n for n, r in enumerate(previous['items']) if r['id'] in existing}
    rows.sort(key=lambda r: (0, prior_order[r['id']], '') if r['id'] in prior_order else (1, r['collection'], r['label']))
    build_id = uuid4().hex
    staging = store / 'builds' / ('.' + build_id)
    try:
        files = staging / 'files'
        files.mkdir(parents=True)
        for name, digest in previous['assets'].items():
            source = store / 'builds' / current / 'files' / name
            if Path(name).name != name or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise ValueError('Existing preview asset changed: ' + name)
            shutil.copyfile(source, files / name)
        manifest = {**previous, 'schema_version': 3, 'id': build_id, 'mode': 'catalog-with-placeholders',
            'items': rows, 'catalog_count': len(runtime), 'source_registry_sha256': signature,
            'intake_summary': registry['summary'], 'previous_build_id': current}
        (staging / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        staging.rename(store / 'builds' / build_id)
        pointer = store / ('.current-' + build_id)
        pointer.write_text(json.dumps({'id': build_id}))
        os.replace(pointer, store / 'current.json')
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {'id': build_id, 'count': len(rows), 'with_samples': len(existing),
            'placeholders': len(rows) - len(existing), 'runtime_count': len(runtime)}


if __name__ == '__main__':
    print(json.dumps(publish(), ensure_ascii=False, indent=2))
