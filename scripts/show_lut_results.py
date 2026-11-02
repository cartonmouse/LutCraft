"""Make completed Codex/OpenClaw jobs visible in the local preview gallery."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.preview_gallery import publish_jobs

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--job", action="append", required=True, help="Completed job directory; repeat for multiple jobs")
parser.add_argument("--name", action="append", help="Photo display name; repeat in photo order")
args = parser.parse_args()
print(json.dumps(publish_jobs(args.job, names=args.name), ensure_ascii=False))
