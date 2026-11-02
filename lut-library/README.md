# 照片 LUT 库

> GitHub 版本仅包含元数据、来源索引与管理脚本，不含第三方 LUT 原文件、购买包、照片、预览和派生构建。下文的文件链接与数量描述已有本地素材，克隆后需自行恢复。见 [素材范围](../docs/ASSETS.md)和 [发布与恢复说明](../docs/GITHUB-PUBLISH.md)。

**当前整理入口：[已有 LUT 总目录](INVENTORY.md)。** 2026-10-30 已停止继续领取和下载，将已购素材、首批免费素材及4个后续领取原包统一建立本地索引。完整数量、重复关系、文件入口和其他格式见总目录；本轮没有效果测试。

**照片适用性：[分类结果与逐文件清单](PHOTO-SUITABILITY.md)。** 991 种 CUBE 映射中，50 种有直接使用依据、372 种需要转换或适配、569 种待确认；HaldCLUT 与附属格式单列。适用性结论来自静态资料，后续接入状态见下方。

**当前运行库：[706 种可用映射](CATALOG.md)。** 含 326 种 CUBE、89 种 CLF 和 291 种 HaldCLUT。本次从归档新增 284 种，保留此前 422 种的 ID、文件与元数据。全部已下载来源已登记；290 种创意映射仍待确认照片色彩条件，目前暂时下架，文件与配置保留。详见 [归档收录说明](ARCHIVE-INTAKE.md)及 [逐项收录状态](intake-catalog.json)。历史接入依据见 [Hald 接入说明](HALD-ACTIVATION.md)与 [81 种转换报告](PHOTO-CONVERSION.md)。

**转换方案：[372 种复核结果](CONVERSION-PLAN.md)。** 方案保留当时状态。首批 81 种和本次 8 种已转换并接入；其余输入版本及技术工具的最新状态以收录登记表为准。

原有首批 11 款仍是此运行库的子集；不同网格、版本的完整数值映射分别保留，显示名称加网格区分。新款标签来自作者命名，不作为照片表现的实测结论。

2026-10-29 新整理三套购买素材：74 个 CUBE，按数值映射去重后 72 款，保存在独立的本地购买库。分类、照片候选预览及接入说明见 [购买素材说明](PURCHASED.md)。这些待确认资产尚未并入运行库。

2026-10-30 建立 [LUT 来源与采购清单](SOURCES.md)，并将公开免费素材归档到 [本批收集目录](collected/2026-10-30/README.md)。收集、分类与接入记录分别保存；新增 39 种运行素材仍保持 `not_tested`，没有沿用旧 11 款的效果验证结论。

当前单次调色入口直接读取 [catalog.json](catalog.json)，下一次调用即可取得全部 706 种，无需手工导入。`luts/` 内有 326 个 CUBE、89 个 CLF 和 291 个 Hald PNG；Hald PNG 是查色表，不是照片预览。CLF 保存完整转换链，Hald 保留原始采样网格，两者都不能当成单张 CUBE 导入其他软件。旧工作台的文件导入仍只接收原有网格白名单的 CUBE；已核验的内置目录另支持 16/25/40/64 网格。

## 目录结构

```text
lut-library/
  luts/<分类>/<稳定ID>/
    <稳定ID>.cube       直接使用的原始 LUT
    <稳定ID>.clf        照片转换链（仅派生版本）
    <稳定ID>.png        明确标记的 sRGB HaldCLUT 原表
    metadata.json      名称、风格、来源、输入、许可与原始校验值
  _sources/            作者官方下载原包 / 原始文件
  licenses/            原作者说明与版权声明
  catalog.json         供程序读取的完整索引
  CATALOG.md           可点击的人类可读目录
  PHOTO-SUITABILITY.md 照片适用性依据与归档分类
  PHOTO-CONVERSION.md  81种转换结果、数值门槛与格式说明
  HALD-ACTIVATION.md   291种Hald原生读取、校验与接入说明
  ARCHIVE-INTAKE.md    本次284种接入及全部来源收录说明
  intake-catalog.json  全部来源的启用、待适配、其他输入版本和附属格式状态
  archive-intake-receipt-2026-10-30.json 706种运行库接入回执
  hald-activation-receipt-2026-10-30.json 422种运行库接入回执
  derived/             独立衍生文件、65³对照版本、配方及逐文件验证结果
  photo-conversion-receipt-2026-10-30.json 131种运行库的接入记录及原件追溯
  photo-activation-receipt-2026-10-30.json 50种运行映射、来源及接入校验记录
  source-downloads.json 下载来源与文件校验记录
  SOURCES.md           来源、领取条件、采购线索与本批统计
  sources.json         可维护的来源与采购清单
  INVENTORY.md          已有全部素材的统一统计与文件入口
  inventory/           本地统一索引、重复关系及补充格式；不直接用于运行
  inventory-receipt-2026-10-30.json 本次离线整理与校验摘要
  free-downloads-2026-10-30.json  本批公开下载URL及复用原包
  collection-receipt-2026-10-30.json  本批统计与原包校验摘要
  collected/           本地收集库、原包、来源证据；不直接用于运行
  tools/               下载、入库、索引和检查脚本
```

分类包括电影、梦幻、氛围、夜景、胶片、拍立得、黑白。每款的 ID 保持稳定；要更改中文名称或标签，编辑该款 `metadata.json`，再重建目录。

## 使用

这些是标准图像 / 显示参考输入的创意 LUT。先处理曝光与白平衡，再应用 LUT 并调整强度；Log 素材需先完成匹配的输入转换。具体输入信息以各款元数据及原作者说明为准。红外黑白为颜色风格模拟。

作者的预览与效果说明入口记录在每款的 `source_page` / `preview_page` 中。

## 同图效果预览

历史上已用粉色花海原始照片生成首批 11 款预览，保留完整画幅，统一为 sRGB；无额外曝光、白平衡或饱和度调整。这些历史预览不覆盖后续新增的 39 种 CUBE 或 81 种 CLF。

- [100% LUT 强度总览](previews/pink-grass-2026-10-28/comparison-100.jpg)
- [50% LUT 强度总览](previews/pink-grass-2026-10-28/comparison-50.jpg)
- [逐张查看原尺寸预览](previews/pink-grass-2026-10-28/README.md)

每款提供两档 1080×1920 无损 PNG。处理记录、输入及 LUT 校验值保存在预览目录的 `manifest.json`，实际计算使用 OpenColorIO 四面体插值。预览目录纳入本地备份，不提交普通 Git。

用其他照片重新生成时，在项目根目录运行：

```bash
.venv/bin/python lut-library/tools/make_previews.py /path/to/photo.jpg --output lut-library/previews/my-photo
```

请使用新的输出目录；脚本会保留已有预览。

## 日常维护

本次接入可重复核对（结构、哈希、元数据及生产加载入口；仅合成 RGB 数值，不读取照片）：

```bash
.venv/bin/python lut-library/tools/intake_archived_luts.py verify
.venv/bin/python lut-library/tools/convert_photo_luts.py verify
# 完整重跑数值样本，仅在实现或环境变化需要复核时使用：
.venv/bin/python lut-library/tools/convert_photo_luts.py verify --numerical
```

原分类、转换方案与统一索引是历史快照，当前启用状态以运行目录及接入记录为准。原 11 种备份在 `inventory/2026-10-30/before-photo-activation/`，转换前 50 种备份在 `inventory/2026-10-30/before-photo-conversion/`。Hald 接入前 131 种备份在 `inventory/2026-10-30/before-hald-activation/`；本次接入前 422 种及旧实现备份在 `inventory/2026-10-30/before-archive-intake/`。旧验证器沿回执链核对后续接入，原回执保持不变。

在本文件夹中执行：

```bash
python3 tools/library.py list
python3 tools/library.py verify
python3 tools/library.py reindex
```

`verify` 检查网格、有限数值、输入范围、文件校验值、重复 ID、重复映射及索引一致性；CLF 另检查限定的节点和嵌入表。`reindex` 从每款元数据生成目录。Hald 检查原始位深、144³/256³ 网格、灰度扩展、三线性插值与源文件哈希。派生版本的 `parent.sha256` 记录真正的上游原件；`original_sha256` 是兼容旧运行库的当前文件校验字段，不能将其误作上游原件摘要。

以后添加 LUT：

1. 将原文件放入 `luts/<分类>/<作者-名称>/`，保留原包到 `_sources/`。
2. 参照已有 `metadata.json` 记录名称、文件名、标签、官方来源、输入要求和许可。使用新的稳定 ID，并保留原作者说明。`original_sha256` 应填写该原始文件的 SHA-256。
3. 执行 `reindex`，再执行 `verify`。同一 LUT 的其他输入版本应在元数据中明确标注，不能作为不同风格重复计数。

首批文件可由 `tools/fetch_sources.py` 重新下载，然后用 `tools/import_initial.py` 按已记录的文件名入库；已存在的文件不会被重新下载，入库脚本不会覆盖内容不同的文件。官方下载链接更新时，应核对版本后再更新记录。

## 存储与来源

二进制资源和原包已由本目录 `.gitignore` 排除出普通 Git；索引、脚本及元数据可追踪。备份时复制整个 `lut-library` 文件夹，才能同时保留实际 LUT 和原包。之前 `downloads/` 中的 Aspen 保留，旧文件链接仍可用。

IWLTBAP 文件来自作者官方免费包，原作者 PDF 说明保存在 `licenses/`；免费发布不等于已核实再分发授权。四款 xMosaique 文件属于发布方明确标记的 MIT 衍生集合，完整第三方声明也已保存。

- [IWLTBAP 官方免费 LUT 与预览](https://blog.iwltbap.com/the-10-free-cinematic-luts-by-iwltbap/)
- [xMosaique 官方 LUT、输入说明与许可标记](https://xmosaique.com/luts/)
