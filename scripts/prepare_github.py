"""Check/export source files without Git history, credentials or local assets.

Run from any directory. Output must be a new directory outside this checkout.
This does not commit, change branches, upload files or rewrite Git history.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
GIT = os.environ.get('GIT_EXECUTABLE', 'git')
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
API_KEY = re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,}|AKIA[A-Z0-9]{16})")
PRIVATE_QUERY = {'xsec_token', 'access_token', 'auth_token', 'api_key', 'signature', 'x-amz-signature'}
ASSET_SUFFIXES = {'.cube', '.clf', '.3dl', '.look', '.xmp', '.zip', '.7z', '.rar', '.dmg', '.pdf', '.jpg', '.jpeg', '.webp', '.mp4', '.mov', '.sqlite', '.sqlite3', '.db', '.pem', '.key'}


def git(*args, input=None, allowed=(0,)):
    result = subprocess.run([GIT, *args], cwd=ROOT, input=input, capture_output=True)
    if result.returncode not in allowed:
        # Git stderr can contain local paths; never output file contents here.
        raise SystemExit('Git command failed: ' + ' '.join(args[:2]))
    return result.stdout


def source_files():
    tracked = git('ls-files', '-z').decode().split('\0')[:-1]
    others = git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')[:-1]
    names = sorted(set(tracked + others))
    ignored = set(git('check-ignore', '--no-index', '-z', '--stdin',
                      input=('\0'.join(names)+'\0').encode(), allowed=(0, 1)).decode().split('\0'))
    return [name for name in names if name not in ignored and (ROOT/name).exists()], sorted(set(tracked) & ignored)


def check(names):
    # Compare configured local secrets without printing or copying their values.
    secrets = []
    env = ROOT / '.env'
    if env.is_file():
        for line in env.read_text().splitlines():
            if '=' not in line or line.lstrip().startswith('#'):
                continue
            key, value = line.split('=', 1)
            value = value.strip().strip('\"\'')
            if any(word in key for word in ('KEY', 'TOKEN', 'SECRET')) and len(value) >= 12:
                secrets.append(value.encode())
    records, errors = [], []
    for name in names:
        path = ROOT/name
        if path.is_symlink() or not path.is_file():
            errors.append((name, 'symlink or non-regular file'))
            continue
        if path.suffix.lower() in ASSET_SUFFIXES or (path.suffix.lower() == '.png' and not name.startswith('docs/assets/')):
            errors.append((name, 'local/third-party binary asset'))
        if path.name.startswith('.env') and path.name != '.env.example':
            errors.append((name, 'environment configuration'))
        raw = path.read_bytes()
        if len(raw) > 10 * 1024 * 1024:
            errors.append((name, 'file exceeds source-export limit of 10 MiB'))
        if any(value in raw for value in secrets) or PRIVATE_KEY.search(raw) or API_KEY.search(raw):
            errors.append((name, 'possible credential; value omitted'))
        if path.suffix.lower() not in ('.png',):
            for url in re.findall(r'https?://[^\s\"\'<>]+', raw.decode('utf-8', errors='replace')):
                try:
                    keys = {key.lower() for key, _ in parse_qsl(urlsplit(url).query)}
                except ValueError:
                    continue
                if keys & PRIVATE_QUERY:
                    errors.append((name, 'signed/authenticated URL; value omitted'))
                    break
        records.append({'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    if errors:
        print(json.dumps({'status': 'blocked', 'findings': errors}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--check', action='store_true', help='Check current working files only; Git history is not exported.')
    choice.add_argument('--output', type=Path, help='New clean directory outside this checkout; never overwritten.')
    args = parser.parse_args()
    names, ignored_tracked = source_files()
    records = check(names)
    result = {'status': 'checked', 'files': len(records), 'bytes': sum(r['bytes'] for r in records),
              'ignored_but_tracked': ignored_tracked, 'includes_git_history': False}
    if args.output:
        target = args.output.expanduser().resolve()
        if target.exists() or target.is_relative_to(ROOT):
            raise SystemExit('Choose a new directory outside the current checkout; existing paths are never overwritten.')
        target.mkdir(parents=True)
        for record in records:
            dest = target/record['path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/record['path'], dest)
            if hashlib.sha256(dest.read_bytes()).hexdigest() != record['sha256']:
                raise SystemExit('Source changed during export; do not publish this incomplete directory.')
        (target/'PUBLISH-MANIFEST.json').write_text(json.dumps({'schema_version': 1,
            'kind': 'source-only-no-history', 'files': records}, ensure_ascii=False, indent=2)+'\n')
        result.update(status='exported', output=str(target))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
