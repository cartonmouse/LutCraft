"""Register every downloaded source; activate only explicitly supported photo routes.

No photo I/O or downloads. Original files and historical receipts remain intact.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path.insert(0, str(PROJECT))
from backend.app.luts import inspect_cube as inspect_runtime_cube
from backend.app.single_pass import catalog, load_catalog_processor
from library import inspect_transform, rebuild, scan
from photo_conversion_math import load_table, source_agreement, validate, write_clf

WORK = ROOT / 'inventory/2026-10-30/archive-intake'
BACKUP = ROOT / 'inventory/2026-10-30/before-archive-intake'
CLASSIFICATION = ROOT / 'inventory/2026-10-30/photo-suitability/catalog.json'
REPORT = WORK / 'validation.json'
RECEIPT = ROOT / 'archive-intake-receipt-2026-10-30.json'
REGISTRY = ROOT / 'intake-catalog.json'
VERSION = 'archive-photo-intake-v1'
PUBLISHERS = {
    'film-luts': "G’MIC Film-Luts", 'editclips': 'EditClips', 'on1-free': 'ON1',
    'joseph-carey': 'Joseph Carey', 'rocketstock': 'RocketStock', 'film-crux-free': 'FILM CRUX',
    'iwltbap-free': 'IWLTBAP', 'iwltbap-legacy': 'IWLTBAP', 'filtergrade-free': 'FilterGrade',
    'lutify-free': 'Lutify.me', 'phlearn-free': 'PHLEARN', 'tdcat': 'TDCat',
    'videoeditingluts': 'VideoEditingLUTs', 'purchased-pocket': 'Pocket Action',
    'purchased-kodak': '柯达 5219', 'purchased-ling': '林馆长', 'xmosaique': 'xMosaique',
    'rawtherapee': 'RawTherapee',
}
STATUS_NOTES = {
    'ready': '已接入照片调色，样片待配置。',
    'needs_profile': '已收录；照片输入、输出条件待确认。',
    'needs_conversion': '已收录；照片色彩适配待完成。',
    'alternate_input': '同款的其他输入版本，保留来源记录。',
    'technical': '技术转换或基准模板，保留归档。',
    'duplicate': '与已收录映射相同，保留来源记录。',
}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def archived_source(row):
    path = (ROOT / row['path']).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file() or sha(path) != row['original_sha256']:
        raise ValueError('Archived source changed: ' + row['id'])
    return path


def photo_route(row, plan):
    # Never infer a profile from LUT numbers or merely from a filename.
    if row['category'] == 'uncertain' and any(s['origin']['source_id'] == 'film-luts' for s in row['source_assessments']):
        return 'film_srgb'
    if plan.get(row['id'], {}).get('route_id') == 'bt1886':
        return 'bt1886_black0'
    return None


def verify_evidence():
    records = {r['file']: r for r in read(WORK / 'evidence/downloads.json') if 'sha256' in r}
    for name in ('film-network.kt', 'film-shader.kt', 'film-repository.kt'):
        if sha(WORK / 'evidence' / name) != records[name]['sha256']:
            raise ValueError('Source implementation evidence changed: ' + name)
    return {name: records[name] for name in ('film-network.kt', 'film-shader.kt', 'film-repository.kt')}


def build():
    if REPORT.exists():
        report = read(REPORT)
        for item in report['new_runtime']:
            if sha(ROOT / item['prepared_path']) != item['technical']['sha256']:
                raise ValueError('Prepared transform changed')
        return report
    evidence = verify_evidence()
    classified = read(CLASSIFICATION)
    old = read(BACKUP / 'catalog.json')['items']
    plan = {r['mapping_id']: r for r in read(ROOT / 'inventory/2026-10-30/conversion-plan/catalog.json')['items']}
    active = {}
    for row in old:
        mapping = row.get('parent', {}).get('mapping_id') or row.get('photo_suitability', {}).get('mapping_id')
        if mapping:
            active[mapping] = row
    prepared, checks, entries = [], [], []
    for index, row in enumerate(classified['cube_items'], 1):
        path = archived_source(row)
        inspect_runtime_cube(path.read_bytes(), bundled=True)
        technical = inspect_transform(path)
        if technical['mapping_sha256'] != row['mapping_sha256']:
            raise ValueError('Source mapping changed: ' + row['id'])
        source = row['source_assessments'][0]['origin']
        publisher = PUBLISHERS.get(source['source_id'], source['source_id'])
        route = photo_route(row, plan) if row['id'] not in active else None
        if route:
            uid = f"{source['source_id']}-photo-{row['mapping_sha256'][:16]}"
            folder = WORK / 'prepared' / uid
            folder.mkdir(parents=True, exist_ok=True)
            table = load_table(path, row['grid_size'])
            agreement = source_agreement(table, row['grid_size'], path)
            target = folder / (uid + ('.clf' if route == 'bt1886_black0' else '.cube'))
            validation = {'passed': True, 'source_interpolation': agreement}
            if route == 'bt1886_black0':
                write_clf(path, 'gamma24', target)
                validation = validate(table, row['grid_size'], 'gamma24', target)
                if not validation['passed']:
                    raise ValueError('Photo conversion failed numerical acceptance: ' + row['id'])
                basis = '源文件声明 Rec.709/BT.1886；本项目显式采用 LB=0、归一化 LW=1、0–1 全范围的工程约定，sRGB ↔ Gamma 2.4 包裹原表。不是作者黑白电平的认证。'
            else:
                shutil.copyfile(path, target)
                basis = '依据同一作者 Film-Simulator 的下载入口及着色器实现，LUT 在 sRGB 编码值上应用；这是基于作者实现的兼容性推断。本项目沿用四面体插值，不宣称复现其完整应用。'
            technical = inspect_transform(target)
            mono = bool(np.max(np.ptp(table, axis=1)) < 1e-5)
            runtime_path = Path('luts/archive-photo') / uid / target.name
            meta = {
                'schema_version': 1, 'id': uid, 'name': publisher + ' ' + row['name'],
                'publisher': publisher, 'filename': target.name, 'category': 'archive-photo',
                'style_zh': row['name'] + '（来源命名；照片效果待查看）',
                'tags': ['黑白' if mono else '彩色'], 'aliases': row.get('aliases', [row['name']])[:24],
                'source_page': source.get('source_page') or 'INVENTORY.md', 'source_origin': source,
                'license': {'id': 'LicenseRef-' + source['source_id'], 'status': source.get('license_note', '沿用来源记录'), 'documents': [], 'redistribution_verified': False},
                'input_profile': 'sRGB 照片；' + ('BT.1886 黑电平为零约定的转换版' if route == 'bt1886_black0' else '按作者应用的 sRGB 实现接入'),
                'input_space': 'srgb', 'output_space': 'srgb', 'enabled': True,
                'derived': route == 'bt1886_black0', 'file_modified': route == 'bt1886_black0',
                'original_sha256': technical['sha256'],
                'parent': {'mapping_id': row['id'], 'path': row['path'], 'sha256': row['original_sha256'], 'mapping_sha256': row['mapping_sha256']},
                'photo_suitability': {'category': route, 'basis': basis, 'parent_mapping_id': row['id']},
                'compatibility_basis': basis, 'effect_test_status': 'not_tested', 'historical_preview_refs': [],
                'intake': {'version': VERSION, 'report_path': REPORT.relative_to(ROOT).as_posix(), 'numerical_status': 'passed', 'route': route},
                'added_date': '2026-10-30', 'batch': '归档 LUT 照片接入；样片待配置',
            }
            result = {**meta, 'path': runtime_path.as_posix(), 'metadata_path': (runtime_path.parent / 'metadata.json').as_posix(), 'technical': technical}
            active[row['id']] = result
            prepared.append({**result, 'prepared_path': target.relative_to(ROOT).as_posix()})
            checks.append({'mapping_id': row['id'], 'runtime_id': uid, 'route': route, 'validation': validation})
            print(f"Prepared {len(prepared)}: {row['name']}", flush=True)
        linked = active.get(row['id'])
        decision = plan.get(row['id'], {}).get('decision')
        if linked:
            status = 'ready'
        elif decision in ('prefer_standard', 'insufficient') or plan.get(row['id'], {}).get('route_id') == 'working_space':
            status = 'alternate_input'
        elif decision == 'utility_archive' or row.get('asset_role') == 'technical_transform':
            status = 'technical'
        elif row['category'] == 'conversion_required':
            status = 'needs_conversion'
        else:
            status = 'needs_profile'
        if 'DJI_Phantom4_DLOG2sRGB' in row['name'] or 'Cinema Base Rec709' in row['name']:
            status = 'technical'
        entries.append({'source_id': row['id'], 'name': row['name'], 'publisher': publisher,
            'format': 'CUBE', 'path': row['path'], 'sha256': row['original_sha256'],
            'status': status, 'runtime_id': linked['id'] if linked else None,
            'grid_size': row['grid_size'], 'engine_validated': True,
            'sources': [s['origin'] for s in row['source_assessments']],
            'reason': STATUS_NOTES[status], 'required_actions': [] if linked else row['required_actions'],
            'related_standard_candidates': plan.get(row['id'], {}).get('related_standard_candidates', []),
            'gallery_visible': status in ('ready', 'needs_profile', 'needs_conversion')})
        if index % 100 == 0:
            print(f'Inspected CUBE {index}/{len(classified["cube_items"])}', flush=True)
    hald_report = read(ROOT / 'derived/2026-10-30-hald-native/validation.json')
    hald = {r['source_id']: r for r in hald_report['items']}
    for row in classified['hald_items']:
        archived_source(row)
        link = hald.get(row['id'])
        status = ('ready' if link['id'] == link['runtime_id'] else 'duplicate') if link else 'technical'
        entries.append({'source_id': row['id'], 'name': row['name'], 'publisher': 'RawTherapee',
            'format': 'HaldCLUT', 'path': row['path'], 'sha256': row['original_sha256'],
            'status': status, 'runtime_id': link['runtime_id'] if link else None,
            'sources': row['sources'], 'reason': STATUS_NOTES[status], 'gallery_visible': status == 'ready'})
    auxiliary = []
    for row in classified['auxiliary_items']:
        archived_source(row)
        auxiliary.append({**row, 'status': 'auxiliary', 'enabled': False})
    registry = {'schema_version': 1, 'date': '2026-10-30', 'version': VERSION,
        'entries': entries, 'auxiliary': auxiliary,
        'summary': {'source_records': len(entries), 'auxiliary_records': len(auxiliary),
                    'statuses': dict(Counter(r['status'] for r in entries)),
                    'runtime_count': len(old) + len(prepared), 'new_runtime': len(prepared),
                    'gallery_count': sum(r['gallery_visible'] for r in entries)},
        'classification_sha256': sha(CLASSIFICATION)}
    put(WORK / 'intake-catalog.json', registry)
    report = {'version': VERSION, 'source_catalog_sha256': sha(CLASSIFICATION),
              'registry_sha256': sha(WORK / 'intake-catalog.json'), 'source_evidence': evidence,
              'new_runtime': prepared, 'checks': checks, 'photo_effect_tests': 0,
              'bt1886_convention': {'black': 0, 'normalized_white': 1, 'domain': [0, 1], 'gamma': 2.4, 'author_certified': False},
              'summary': registry['summary']}
    put(REPORT, report)
    return report


def verify_successor(previous):
    receipt = read(RECEIPT)
    if sha(ROOT / 'hald-activation-receipt-2026-10-30.json') != receipt['previous_receipt_sha256']:
        raise ValueError('Previous receipt changed')
    for rel, expected in previous['implementation_sha256'].items():
        if sha(BACKUP / 'implementation' / rel) != expected:
            raise ValueError('Historical implementation changed: ' + rel)
    for rel, expected in receipt['implementation_sha256'].items():
        if sha(PROJECT / rel) != expected:
            raise ValueError('Intake implementation changed: ' + rel)


def historical_catalog():
    return BACKUP / 'catalog.json' if RECEIPT.exists() else ROOT / 'catalog.json'


def verify(actual=None):
    receipt, report, registry = read(RECEIPT), read(REPORT), read(REGISTRY)
    verify_successor(read(ROOT / 'hald-activation-receipt-2026-10-30.json'))
    if sha(REPORT) != receipt['report_sha256'] or sha(REGISTRY) != receipt['registry_sha256'] or sha(ROOT / 'catalog.json') != receipt['catalog_sha256']:
        raise ValueError('Intake receipt mismatch')
    actual = scan() if actual is None else actual
    saved = read(ROOT / 'catalog.json')
    if saved['items'] != actual or len(actual) != registry['summary']['runtime_count']:
        raise ValueError('Runtime catalog mismatch')
    by_id = {r['id']: r for r in actual}
    for row in read(BACKUP / 'catalog.json')['items']:
        if by_id.get(row['id']) != row:
            raise ValueError('Prior runtime entry changed: ' + row['id'])
    for rel, expected in read(BACKUP / 'baseline.json')['metadata_sha256'].items():
        if sha(ROOT / rel) != expected:
            raise ValueError('Prior metadata changed: ' + rel)
    for row in registry['entries'] + registry['auxiliary']:
        path = ROOT / row['path']
        if sha(path) != row.get('sha256', row.get('original_sha256')):
            raise ValueError('Archived bytes changed: ' + row['path'])
    for row in report['new_runtime']:
        expected = {k: v for k, v in row.items() if k != 'prepared_path'}
        if by_id[row['id']] != expected:
            raise ValueError('Activated entry differs from preparation')
    if {r['id'] for r in catalog()} != set(by_id):
        raise ValueError('Production reader differs')
    for row in catalog():
        if row['id'] in {r['id'] for r in report['new_runtime']}:
            values = np.array([[0, 0, 0], [1, 1, 1], [.03, .2, .9]], dtype=np.float32)
            load_catalog_processor(row).applyRGB(values)
            if not np.isfinite(values).all():
                raise ValueError('Invalid production output')
    return {'passed': True, **registry['summary'], 'photo_effect_tests': 0}


def activate():
    if RECEIPT.exists():
        return verify()
    report = build()
    baseline = read(BACKUP / 'baseline.json')
    if sha(ROOT / 'catalog.json') != baseline['files_sha256']['catalog.json']:
        raise ValueError('Runtime changed since preflight')
    old = read(BACKUP / 'catalog.json')['items']
    new = [{k: v for k, v in r.items() if k != 'prepared_path'} for r in report['new_runtime']]
    items = sorted(old + new, key=lambda r: r['id'])
    created = []
    try:
        for row in report['new_runtime']:
            folder = (ROOT / row['path']).parent
            folder.mkdir(parents=True, exist_ok=False)
            created.append(folder)
            shutil.copyfile(ROOT / row['prepared_path'], ROOT / row['path'])
            meta = {k: v for k, v in row.items() if k not in ('prepared_path', 'path', 'metadata_path', 'technical')}
            put(ROOT / row['metadata_path'], meta)
        if scan() != items:
            raise ValueError('Staged runtime mismatch')
        rebuild(items)
        shutil.copyfile(WORK / 'intake-catalog.json', REGISTRY)
        implementation = set(baseline['implementation_sha256']) | {
            'backend/app/luts.py', 'backend/app/single_pass.py', 'lut-library/tools/intake_archived_luts.py'}
        put(RECEIPT, {'date': '2026-10-30', 'version': VERSION, **report['summary'],
            'previous_receipt_sha256': baseline['previous_receipt_sha256'],
            'previous_catalog_sha256': baseline['files_sha256']['catalog.json'],
            'backup_path': BACKUP.relative_to(ROOT).as_posix(), 'catalog_sha256': sha(ROOT / 'catalog.json'),
            'registry_sha256': sha(REGISTRY), 'report_sha256': sha(REPORT),
            'implementation_sha256': {p: sha(PROJECT / p) for p in sorted(implementation)},
            'photo_effect_tests': 0})
        return verify(items)
    except Exception:
        for folder in created:
            shutil.rmtree(folder)
        for name in ('catalog.json', 'CATALOG.md'):
            shutil.copyfile(BACKUP / name, ROOT / name)
        REGISTRY.unlink(missing_ok=True)
        RECEIPT.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'activate', 'verify'))
    args = parser.parse_args()
    result = {'build': build, 'activate': activate, 'verify': verify}[args.command]()
    print(json.dumps(result.get('summary', result), ensure_ascii=False, indent=2))
