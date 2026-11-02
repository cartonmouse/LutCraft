"""Build an allowlisted local Program directory; never uploads or publishes."""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(target):
    target = Path(target).resolve()
    if target.exists():
        raise SystemExit('目标目录已存在，请选择新的空目录；不会覆盖已有 Program。')
    target.mkdir(parents=True)
    plugin = ROOT / 'integrations/openclaw/single-pass'
    shutil.copyfile(plugin / 'AGENTS.md', target / 'AGENTS.md')
    dest = target / '.openclaw/extensions/lut-single-pass'
    dest.mkdir(parents=True)
    for name in ('index.js', 'package.json', 'openclaw.plugin.json'):
        shutil.copyfile(plugin / name, dest / name)
    code = target / 'backend/app'
    code.mkdir(parents=True)
    # Source-only allowlist: no .env, database, photos, credentials, sessions,
    # node_modules or local OpenClaw configuration can enter this directory.
    for file in (ROOT / 'backend/app').glob('*.py'):
        shutil.copyfile(file, code / file.name)
    shutil.copyfile(ROOT / 'backend/requirements.lock', target / 'requirements.lock')
    library = target / 'lut-library'
    library.mkdir()
    shutil.copyfile(ROOT / 'lut-library/catalog.json', library / 'catalog.json')
    catalog = json.loads((library / 'catalog.json').read_text())
    for row in catalog['items']:
        for relative in [row['path'], row['metadata_path'], *row.get('license',{}).get('documents',[])]:
            file = (ROOT / 'lut-library' / relative).resolve()
            if not file.is_relative_to((ROOT / 'lut-library').resolve()):
                raise SystemExit('LUT 清单包含越界路径。')
            dest = library / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, dest)
    (target / 'PROGRAM.md').write_text('''# LUT 单次调色 Program

本目录由本地工程生成，不包含运行状态或密钥；当前只准备，不上传或上线。

将来通过官方 Build with local Agent 流程将本目录内容同步到 /oasn。
在目标运行环境创建 /oasn/.venv，并安装 requirements.lock。
由平台保留自身模型配置；为 main 启用 lut-single-pass 插件及
lut_inspect_request、lut_apply 两个工具。不要用本地 OpenClaw 配置覆盖平台配置。

正式输入：/oasn/in/invocation.json；只读取 input.user_prompt 和 input.attachments。
输出：/oasn/out/<调用摘要>/result.json 和实际图片。最终由 main 返回图片附件或可下载链接。
多用户任务、附件交付和平台模型仍须在目标版本中验收；本地测试不等于平台已上线。
LUT 原作者说明随包保留；此本地准备动作不代表重新授权分发 LUT 素材。
''')
    print(json.dumps({'status':'prepared_local_only','directory':str(target),'lut_count':len(catalog['items'])},ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    prepare(parser.parse_args().output)
