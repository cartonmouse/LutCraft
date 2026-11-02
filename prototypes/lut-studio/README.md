# LutCraft · 风格图库

2026-11-02：无主样片的 290 款暂时下架；图库、搜索和详情切换仅显示 706 款已配图风格。完整构建、LUT 文件和详情配置保留。后续配置有效主样片及 100% 效果缩略图并发布后，会自动恢复展示。

2026-10-31：996 个条目均已配置详情介绍；706 款可用 LUT 均有主样片，并额外配置 3 张真实照片效果图（合计 2,118 张，固定应用对应 LUT 的 100% 强度）。290 款待适配条目只展示收录介绍，不生成效果图。详情配置由 `style-stories.json` 维护，审核记录位于 `data/gallery-research/2026-10-31-full-stories/`。

修改详情后运行 `.venv/bin/python scripts/publish_style_stories.py --prepare`，检查生成的构建，再用 `--activate <构建 ID>` 切换；重建流程会读取现有配置。`configure_style_stories.py` 是初次批量编写工具，重新执行会覆盖后续人工修订，日常修改应直接编辑配置。

以下为最初归档收录阶段的记录：

2026-10-30：图库已扩展为 **996 个风格条目：706 款可用、290 款待适配**。原有 9 款各有一张专属样片，保留原图、50% / 100% 效果及对应缩略图，共 54 个图片文件；其余 987 款暂用占位卡片。按用户安排，本次先完成归档收录，后续再配置样片。来源、接入依据及待处理清单见 [归档收录说明](../../lut-library/ARCHIVE-INTAKE.md)。

```bash
# 已有样片构建存在时，直接合并全部收录条目；不会生成新样片：
.venv/bin/python scripts/publish_intake_gallery.py
bash prototypes/lut-studio/start.sh
```

打开 [风格图库](http://127.0.0.1:4175/)。

- 按名称、品牌或关键词搜索，筛选彩色 / 黑白。首批加载 48 款，点击“加载更多”继续浏览；列表上方仅显示筛选后的风格数量。
- 原有样片按 `style-samples.json` 逐款绑定。卡片无强度角标，有样片的详情可切换 50% / 100% 并查看原图对比；左右按钮或方向键切换风格，Esc 关闭。
- 占位卡片不伪造效果图。可用款即使没有样片也可用于自己的照片；待适配款显示原因，隐藏应用入口，服务端也拒绝应用。
- 点击“用于自己的照片”，选择 JPEG / PNG 后再点击“应用并保存”。照片仅送往本机服务，单张最多 10 MB / 2400 万像素。沿用已有 sRGB 照片管线，每次从原图处理；输出长边最多 2560 像素，保留原图与 PNG 透明通道。
- 处理结果可下载，并保存到“我的结果”和历史记录。出错显示原因；不会发布半成品或覆盖上一次成功结果。
- 桌面三列、平板两列、手机单列；图片保留完整构图和原有水印。

预览与用户照片处理均不调用模型。自动检查证明文件可读取、LUT 被应用、来源与输出可追溯，不代表审美验收。

## 预览制作与存储

专属样片配置在 `style-samples.json`。需要更新样片时，先执行 `.venv/bin/python scripts/build_style_gallery.py`，再执行 `.venv/bin/python scripts/publish_intake_gallery.py` 合并全量目录。前者核对样片和 LUT 的 SHA-256，调用现有 `imaging.render` / `load_catalog_processor` 制作原图、效果图及缩略图；后者核对并复制已有成品，为没有样片的收录条目添加占位。两者均在完整构建成功后原子更新指针，旧构建保留。归档登记表不变时重复发布直接复用当前构建。

- `data/style-gallery/current.json`：当前图库指针。
- `data/style-gallery/builds/<id>/manifest.json`：样片、LUT、代码摘要、强度和所有成品摘要。
- `data/style-gallery/builds/<id>/files/`：浏览器可见的预览成品。按不可变构建 ID 缓存；首屏以外图片懒加载。
- `data/lut-preview/runs/<id>/`：用户点击应用后的原图、结果、`gallery.json` 和 `style-application.json`。
- 上传中间文件在请求结束后清理；新完成结果更新最近结果指针，既有批次保持可访问。

现有样片自带各自的光线与原始色调。页面展示 LUT 对这些输入的作用，不把样片描述为未经调色的校准图。本次归档收录没有制作、编辑或重新渲染样片。

## 接口与边界

服务仅监听 `127.0.0.1`，使用单 worker。旧的临时“手动试用 LUT”仍默认关闭，记录与实现保留。图库只允许应用当前清单中 `availability=ready` 且 LUT 摘要匹配的风格。

- `GET /api/styles`：当前风格清单、可用状态、样片与成品 URL，以及本页临时令牌。占位条目的 `sample` 为 `null`、`previews` 为空。
- `GET /api/styles/{build_id}/files/{filename}`：只提供该清单登记的图片，不接受任意文件路径。
- `POST /api/styles/apply?build_id=…&lut_id=…&strength=0.5|1`：原始 JPEG / PNG 字节；需要 `x-lut-preview-token` 和同源 Origin，`x-photo-name` 是仅用于展示的 URL 编码文件名。流式限制大小、校验实际图片格式与像素数、核对 LUT 摘要，一次只执行一个渲染。
- `GET /api/health`：默认模式 `style-gallery`，`manual_enabled: false`。
- 原 `/api/jobs`、`/api/chat`、`/api/manual/apply` 默认仍不接受写入。

## 既有结果与 Codex 交接

[我的结果](http://127.0.0.1:4175/results) 保留原有只读结果页面、原图切换、大图与历史批次；`/?run=<id>` 和 `/results?run=<id>` 均可打开指定批次。`GET /api/preview`、`/api/history`、`/api/previews/{id}` 及对应图片接口保留。

Codex / OpenClaw 的单次调色流程仍可独立工作，`run_openclaw(job_dir)` 成功后自动交接；也可显式合并已完成任务：

```bash
.venv/bin/python scripts/show_lut_results.py \
  --job data/results/<批次>/job-01 \
  --job data/results/<批次>/job-02 \
  --name 第一张 --name 第二张
```

原“手动试用 LUT”仅在显式设置 `LUT_MANUAL_PREVIEW=1` 后恢复，用于旧结果页面的开发检查；当前不启用。实现位于 `backend/app/manual_lut_preview.py`，记录位于 `data/lut-preview/manual-tests.json`。

本轮仅本地实现，没有发布网站或上传 Agent。

## 验证

```bash
.venv/bin/python -m pytest prototypes/lut-studio/test_gallery.py prototypes/lut-studio/test_server.py prototypes/lut-studio/test_manual.py -q
source scripts/env.sh
node --check prototypes/lut-studio/gallery.js
```

真实上传的浏览器验收在隔离结果目录 `data/qa/style-gallery-2026-10-30/results/` 进行，不将测试照片加入用户历史。预览文件检查记录在同级 `render-validation.json`。
