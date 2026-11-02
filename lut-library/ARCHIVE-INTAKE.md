# 已下载归档收录（2026-10-30）

本次登记全部已有下载，并从此前未启用的归档接入 **284 种**：276 种 G’MIC Film-Luts 原始 CUBE、8 种 EditClips 照片转换 CLF。运行库由 422 增至 **706 种**；原 422 种的 ID、文件与元数据保持不变，原包与历史回执保留。

“已收录”不等于全部可用于照片。290 种创意映射仍缺少明确的输入、输出色彩条件，已加入图库占位且禁止应用。没有通过猜测色彩空间强行启用。此次没有制作样片，也没有进行照片效果验收。

## 当前数量

| 状态 | 数量 | 处理方式 |
| --- | ---: | --- |
| 可用于照片 | 706 | 326 CUBE、89 CLF、291 HaldCLUT；图库与单次调色可用 |
| 创意映射待确认 | 290 | 图库占位，显示待适配原因，服务端拒绝应用 |
| 其他输入版本 | 207 | 保留来源记录；当前照片流程不展示为新增风格 |
| 技术转换与基准模板 | 80 | 归档，包括 Hald Identity |
| 重复 Hald 映射 | 1 | 关联已启用映射，保留原件 |
| 附属格式 | 602 | 3DL、CSP、ICC、XMP、ONPreset 等；保留格式及来源状态 |

前五行合计 1,284 条来源记录，即 991 种去重后的 CUBE 数值映射与 293 个 Hald 文件；602 个附属文件另计，不声称它们等同于同名 CUBE。原始 CUBE 文件的多来源和重复关系仍在历史总目录中。

图库包含 996 个照片风格条目（706 + 290）。原有 9 款专属样片及 54 个图片文件全部保留；其余 987 款使用“样片待配置”占位。待适配条目另标记“照片适配待确认”。搜索、彩色/黑白筛选和每批 48 款加载覆盖整个清单。

## 新增接入依据

### G’MIC Film-Luts：276 种

来源为 [Film-Luts 仓库](https://github.com/YahiaAngelo/Film-Luts)。同一作者的 [Film-Simulator](https://github.com/YahiaAngelo/Film-Simulator) 从该仓库下载 LUT，着色器在转入线性光运算前将 LUT 应用于 sRGB 编码值。因此本次按作者应用实现推断其照片管线兼容性，保留原始 CUBE，不改表值、不降采样。

证据代码、下载地址和 SHA-256 保存在 [evidence](inventory/2026-10-30/archive-intake/evidence/downloads.json)。这是基于实现的兼容性推断，不是作者对每个 LUT 的独立色彩认证；项目沿用四面体插值，也不宣称复现来源应用的全部处理。新增内置目录支持 16/25/40/64 网格；普通用户上传的原有网格边界不变。

### EditClips：8 种

来源文件明确声明 Rec.709 / BT.1886。依据 [ITU-R BT.1886](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.1886-0-201103-I!!PDF-E.pdf)，本项目显式采用 **黑电平 LB=0、归一化白电平 LW=1、0–1 全范围** 的工程约定，以 sRGB ↔ Gamma 2.4 的解析转换包裹完整原始 LUT 表，保存为 CLF。

上述黑白电平是项目约定，不能解释为作者提供的显示器标定。原件、来源哈希、转换条件与 `not_tested` 照片效果状态逐项写入元数据。其余 22 个 EditClips 因条件不足继续等待确认。

## 尚待确认的 290 种

| 来源 | 数量 |
| --- | ---: |
| Joseph Carey | 77 |
| RocketStock | 35 |
| FilterGrade | 31 |
| TDCat | 29 |
| Pocket Action | 24 |
| EditClips | 22 |
| 柯达 5219 | 18 |
| VideoEditingLUTs | 12 |
| 林馆长 | 12 |
| ON1 | 10 |
| FILM CRUX | 9 |
| Lutify.me | 5 |
| PHLEARN | 5 |
| IWLTBAP | 1 |

下一步需要这些来源的输入与输出色域、曲线和电平定义，或能证明其对应照片处理方式的官方实现。仅有“Rec.709”“可用于照片”等笼统说明不足以确定实际传递曲线；获得依据后再做相应转换与数值校验。每项原路径、来源包、待补条件和相关标准版本线索均保存在 [intake-catalog.json](intake-catalog.json)。附属格式需要另核对其内部功能是否能表达为当前逐像素映射，当前不自动转换。

## 验证与追溯

- 已核对 991 种 CUBE 的结构及来源映射、293 个 Hald 与 602 个附属文件的来源哈希。
- 276 个新增 CUBE 的 CPU 处理器通过独立四面体参考采样；8 个 CLF 各通过至少 1,827,920 个确定性 RGB 样本及多档强度检查，最大绝对误差约 `3.07e-5`，低于 `1/255` 门槛。有限数值采样不构成整个色域的数学证明，也不是照片审美测试。
- 运行目录结构、全部元数据、所有新增生产处理器加载、原 422 种内容不变及旧接入回执链检查通过。
- 图库/API 测试覆盖无样片的可用款和待适配款；浏览器核验搜索、48→96 分批加载、详情与原有样片。待适配款在渲染前拒绝请求。

接入回执：[archive-intake-receipt-2026-10-30.json](archive-intake-receipt-2026-10-30.json)。逐项数值结果：[validation.json](inventory/2026-10-30/archive-intake/validation.json)。接入前备份：[before-archive-intake](inventory/2026-10-30/before-archive-intake/)。图库的不可变构建与指针保存在项目 `data/style-gallery/`。

在项目根目录复核：

```bash
.venv/bin/python lut-library/tools/intake_archived_luts.py verify
.venv/bin/python lut-library/tools/organize_existing.py verify
.venv/bin/python scripts/publish_intake_gallery.py
```

前两项检查本地文件与历史追溯链；最后一项合并图库占位，登记表未变时复用现有构建。`build` / `activate` 是本次接入的幂等命令，已存在产物时会核对并复用；未来追加其他来源应建立新的接入批次和回执，不能修改历史快照冒充原记录。
