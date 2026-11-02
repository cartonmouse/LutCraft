# GitHub 发布与本地素材恢复

## 发布范围

仓库保留源码、测试、构建脚本、依赖锁文件、空环境变量模板、LUT 元数据、风格文案和样片绑定，以及项目图标。

忽略 `.env`、本地依赖、运行日志、数据库、会话、用户图片、样片、图库构建、生成结果、第三方 LUT 文件、下载／购买原包和派生构建。详见 [素材与许可说明](ASSETS.md)。

这是源码发布，不是本地 23 GB 工作目录的备份。既有素材仍保留在原工程，不能用 GitHub 代替素材备份。

## 推荐：从干净目录首次推送

原工程已有两个本地提交，其中包含旧照片样片和下载包附带的第三方 PDF。`.gitignore` 和 `git rm --cached` 只能影响后续提交，不能移除旧历史。因此推荐导出当前源码，创建独立的新仓库；原工程、分支和历史不改写。

在原工程根目录运行：

```bash
.venv/bin/python scripts/prepare_github.py --check
.venv/bin/python scripts/prepare_github.py --output ../LUT-Aagent-github
```

目标目录必须不存在。导出会采用当前工作文件（包括未暂存修改），应用忽略规则，检查常见密钥和带鉴权信息的链接，核对复制前后摘要。不会复制 `.git`，也不会提交、设置远程仓库或上传。

导出目录内的 `PUBLISH-MANIFEST.json` 列出文件名、大小及 SHA-256，可用于核对交付内容。检查器是辅助检查，不代替人工审阅，也不扫描之后由你另行加入的文件。

在 GitHub 手动创建一个空仓库，然后在**导出目录**操作：

```bash
cd ../LUT-Aagent-github
git init -b main
git add .
git diff --cached --stat
git diff --cached --check
git status --short
# 检查通过后，由你手动执行：
git commit -m "整理 LutCraft 源码与项目文档"
git remote add origin https://github.com/cartonmouse/LutCraft.git
git push -u origin main
```

项目仓库为 [https://github.com/cartonmouse/LutCraft](https://github.com/cartonmouse/LutCraft)。当前已准备的发布目录已设置 `origin`，无需重复执行 `git remote add`；上述命令保留供重新导出后使用。若使用上述导出方案，不要从原工程推送旧分支，否则旧素材仍随历史上传。GitHub 空仓库不要预先勾选初始化 README，以免产生无关历史冲突。

当前原工程已完善忽略规则，并将新规则命中的索引项解除跟踪；本地文件不删除。其他已有暂存修改保留。整理前的索引与被修改文件备份位于被忽略的 `data/github-preparation/before/`。

## 克隆后的运行边界

需要 Python 3.11+、Node 22.12+ 和 pnpm；精确依赖由锁文件确定。

```bash
bash scripts/setup.sh
bash prototypes/lut-studio/start.sh
```

打开 `http://127.0.0.1:4175/`。未恢复素材时页面可以启动，但图库会等待样片，不能直接展示已有 706 款风格。自然语言调色还需按 [原生 Agent 文档](../integrations/openclaw/single-pass/README.md) 安装 OpenClaw 并配置自己的模型凭据。

若要恢复原工程的完整本地体验，通过自己的备份渠道复制以下内容，不提交 Git：

1. `lut-library/luts/` 中与 `catalog.json` 对应的 CUBE、CLF、Hald PNG。恢复后应核对目录里的 SHA-256，不要用相同文件名替换成别的 LUT。
2. 当前 `data/style-gallery/current.json`，以及其指向的 `data/style-gallery/builds/<id>/` 完整构建。只复制已激活构建即可展示，不需要复制所有历史构建。
3. 若需重新构建样片，恢复 `style-samples.json` 的 `asset_directory` 和 `style-stories.json` 的 `examples[].source` 引用的照片；或配置你拥有使用权限的新照片并重新生成校验值和构建。
4. 若需继续原有个人结果，另行恢复 `data/lut-preview/`。旧工作台的数据库与照片属于另一套状态，按原工程备份恢复，不是图库启动的必需项。
5. `.env` 在新机器单独配置。不要复制运行会话、OpenClaw 身份文件或旧浏览器会话来共享账户。

来源记录保留普通网页链接；小红书临时令牌已移除，网页能否直接打开取决于平台登录及访问条件。

## 源码验证与素材集成测试

以下测试使用合成色表，无需私有照片和第三方 LUT 原文件：

```bash
.venv/bin/python -m pytest backend/tests/test_hald.py backend/tests/test_photo_conversion.py -q
```

`test_single_pass.py`、图库、手动预览及部分旧测试依赖本地真实 LUT 或照片。恢复对应素材后再执行完整集成验证；源码导出未附带这些素材，因此不宣称空仓库的全量测试全部可运行。

本轮仅整理文件与文档，不替你执行 commit、push、历史改写或平台发布。
