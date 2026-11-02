"""Read-only single-pass runtime diagnostics; never installs or calls a model."""
import json
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.single_pass_runtime import ENTRY, PLUGIN, local_settings, runtime_status

settings = local_settings()
report = runtime_status()
report['scope'] = 'local_single_pass'
report['openagent_deployment'] = 'not_published'
report['model_acceptance'] = 'not_executed_by_diagnostics'
if report['installed']:
    try:
        version = subprocess.run([settings['node'], str(ENTRY), '--version'], capture_output=True, text=True, timeout=15)
        report['cli_version'] = version.stdout.strip()[:100] if version.returncode == 0 else 'unavailable'
        report['version_matches'] = version.returncode == 0 and '2026.6.11' in version.stdout
    except (OSError, subprocess.TimeoutExpired):
        report['version_matches'] = False
manifest = json.loads((PLUGIN / 'openclaw.plugin.json').read_text())
report['declared_tools'] = manifest['contracts']['tools']
try:
    response = httpx.get('http://127.0.0.1:4175/api/health', timeout=3)
    response.raise_for_status()
    # Never print the browser's CSRF token.
    health = response.json()
    report['viewer'] = {k: health.get(k) for k in ('runtime', 'version', 'configured', 'rendering')}
except (httpx.HTTPError, ValueError):
    report['viewer'] = 'not_running'
report['next_step'] = '本地运行 prototypes/lut-studio/start.sh；后续按官方流程接入 OpenAgent，再执行远端交付验收。'
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(0 if report['configured'] and report.get('version_matches') else 2)
