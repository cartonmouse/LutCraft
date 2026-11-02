# 已有 LUT 的照片适用性分类

分类日期：2026-10-30。范围为本地已有资产；依据文件头、随包说明、已保存的来源页面及项目代码进行静态分类。分类阶段没有新增 LUT 下载、照片效果测试、LUT 转换或运行库接入；后续接入单独记录如下。

**后续接入状态：** 50 种原始 CUBE、81 种 CLF 照片转换版已接入；随后通过原生格式支持接入 291 种 sRGB HaldCLUT，运行库共 422 种。见 [当前目录](CATALOG.md)、[转换报告](PHOTO-CONVERSION.md)及 [Hald 接入说明](HALD-ACTIVATION.md)。下文保留分类时的结论和格式限制，Hald 的格式障碍现已解决；Identity 模板仍归档。

**后续转换复核：** 原“需要转换”的 372 种已逐项建立 [照片流程转换方案](CONVERSION-PLAN.md)，其中 81 种的转换链定义较明确，其他项分别补条件、优先标准版或继续归档；未执行转换。

## 分类结果

以当前项目的 **sRGB 编码值输入 → LUT → sRGB 编码值输出** 为判断基准。991 种 CUBE 数值映射全部分类，逐一核对了 1393 个原始来源文件的 SHA-256 和文件头。

| 分类 | CUBE 映射数 | 含义 | 完整文件清单 |
|---|---:|---|---|
| 可直接用（依据声明） | 50 | 明确支持 sRGB，且文件符合当前导入器要求；创意 LUT 未声明改变输出空间时，按同一显示域输出理解 | [50 种文件](inventory/2026-10-30/photo-suitability/direct.md) |
| 需要转换／适配 | 372 | 已知依赖其他色彩空间、相机曲线或格式适配；部分转换参数仍待补齐 | [372 种文件](inventory/2026-10-30/photo-suitability/conversion_required.md) |
| 还不确定 | 569 | 输入、输出定义不足，或声明冲突，暂不能确定使用路线 | [569 种文件](inventory/2026-10-30/photo-suitability/uncertain.md) |

**“直接用”是文档依据下的技术判断，不是效果验收；“还不确定”不代表不能用于照片。** 数值映射数也不等于视觉风格数：同一风格可能有多个输入版本、网格或修订版，技术转换表也包含在映射总数中。

另有 **293 个 HaldCLUT**，README 声明默认 sRGB，但项目不直接接收此格式，归入“需要格式转换”。其中 **292 个风格文件、1 个 Identity 基准模板**，模板不计作风格。见 [HaldCLUT 清单](inventory/2026-10-30/photo-suitability/hald.md)。未将 HaldCLUT 与 CUBE 做跨格式等效合并。

## 按来源查看

| 来源 | 可直接用 | 需要转换 | 还不确定 | 来源内 CUBE 映射数 |
|---|---:|---:|---:|---:|
| Pocket Action LUT预设 | 0 | 4 | 24 | 28 |
| 林馆长 iPhone 专用 LUT 合集2 | 0 | 0 | 12 | 12 |
| 柯达 5219 | 0 | 14 | 18 | 32 |
| ON1 Free LUTs | 10 | 77 | 10 | 97 |
| Lutify.me 免费 LUT 包 | 0 | 140 | 5 | 145 |
| Joseph Carey — Rec.709 77 款 | 0 | 0 | 77 | 77 |
| xMosaique — 18 款 | 18 | 0 | 0 | 18 |
| YahiaAngelo / Film-Luts | 11 | 0 | 276 | 287 |
| IWLTBAP 官方免费包 | 22 | 129 | 4 | 155 |
| TDCat 免费 LUT 合集 | 0 | 0 | 29 | 29 |
| EditClips 创意 LUT | 0 | 8 | 22 | 30 |
| VideoEditingLUTs 单款公开下载 | 0 | 0 | 12 | 12 |
| RocketStock / Shutterstock 35 款 | 0 | 0 | 35 | 35 |
| FilterGrade 五个官方免费包 | 0 | 0 | 31 | 31 |
| FILM CRUX — Grecian Ideal 免费 LUT | 0 | 0 | 9 | 9 |
| PHLEARN 免费 LUT Sample Pack | 0 | 0 | 5 | 5 |

来源之间会共享同一数值映射，表中各来源不能直接相加。Film-Luts 的 11 种“可直接用”映射与 xMosaique 重合，依据来自后者的明确 sRGB 声明，没有额外计入全库的 50 种。重复文件中若某来源没有说明，但另一来源对同一完整数值映射给出明确依据，可以沿用该适用路线；有矛盾的明确声明则保留为待确认。

50 种直接使用映射来自：**xMosaique 18 种、ON1 Color & Mood 10 种、IWLTBAP 22 种**。IWLTBAP 包括 19 种 Standard/STD 映射及 K25、K64、K99；K99 保留作者的实验版本标记。重复名称的不同数值版本分别保留，清单用映射 ID 区分。

## 需要转换的具体原因

- **ON1 77 种、Pocket Action 2 种：Adobe RGB (1998)。** 文件头注明 Export LUT 的色彩配置。后续应核实对应 ICC，并建立 sRGB → Adobe RGB → LUT → sRGB；这不是简单改文件名或移除注释。
- **Pocket Action 另外 2 种：Rec.709 Gamma 2.4；EditClips 8 种：Rec.709 / BT.1886。** 需要确认曲线、黑白电平等参数，再建立与 sRGB 的前后转换。
- **Lutify 140 种、IWLTBAP 129 种、已购柯达 5219 的 Log 版 14 种：特殊输入或输出。** Log、ACEScct、DWG、RWG 等版本不能直接接受项目现有 sRGB 编码值。先明确完整曲线、色域及输出定义；有同款普通图像版本时优先复核它。将 sRGB 编码到另一空间并不能恢复已渲染照片丢失的动态范围。
- **HaldCLUT 293 个：格式适配。** 需要正确读取 Hald 的轴顺序与采样，转成引擎支持的 CUBE 网格或增加格式支持；默认 sRGB 的说明不意味着项目现在能直接打开。

“需要转换”表示已知存在适配需求，**不表示转换方案已验证或可以立即自动执行**。IWLTBAP 的 Utility 目录中还有技术转换及基础校正素材，保留其用途，不把每张转换表算作一种照片风格。Lutify 中 KineLog3 与 VLog 的 5 对文件虽然数值相同，原始输入标签仍分别记录，不据此推断两种输入空间等同。

## 需要继续补资料的部分

PHLEARN 明确支持照片并给出 Photoshop 安装方法，但未规定照片的色彩配置；Joseph Carey、Lutify 的 Rec709-to-Rec709 等只注明 Rec.709，不能据此确定具体传递函数。林馆长的拍照目录与 709 文件名、柯达标准版、Pocket/Action 或 Mimo 设备用途也没有完整输入输出定义，因此暂保留为待确认。

IWLTBAP 的 `DJI_Phantom4_DLOG2sRGB` 和 `DJI_Phantom4_DLOG2sRGB_Improv` 文件头同时写了 sRGB 输出与 Rec.1886 Gamma，存在冲突，单独标记待核实。已知它们需要匹配 D-Log 输入，也不能据此跳过输出定义的核对。

以前的 **14 款照片候选**只是当时的优先预览集合，不是适用数量上限，也不是本轮的兼容性结论。历史预览及其记录完整保留。

## 格式限制单列

当前导入器支持 CUBE 的 13、17、32、33、65 网格、0–1 输入域和不超过 10 MB 的 UTF-8 文件。共有 **71 种 CUBE 映射**另有格式障碍，其中 **69 种主分类仍为“还不确定”**：即使解决格式问题，也仍须查明色彩空间。

例如 FILM CRUX 使用 16³、TDCat 使用 64³、部分 FilterGrade 使用 16³/25³；Pocket 的“星台光”是 40³，并同时依赖 Adobe RGB。后续可以评估重采样或扩展导入器。本轮保留原数据，没有做这些转换。

还有 **602 个附属格式文件**，另列“内部色彩定义／可转换性待确认，已知需要格式适配”，不混入 991 种 CUBE 的统计：3DL 306、CSP 10、ICC 107、XMP 169、ONPreset 10。它们可能是同款的其他格式，不能都算成新增风格；XMP/ONPreset 等也不能假定能完整转换成逐像素 CUBE。见 [附属格式清单](inventory/2026-10-30/photo-suitability/auxiliary.md)。

## 依据与记录

项目照片输入与 LUT 调用见 [imaging.py](../backend/app/imaging.py)，导入限制与原始 FileTransform 调用见 [luts.py](../backend/app/luts.py)。当前代码未自动按 LUT 注释转换色彩空间。

sRGB 使用分段传递函数；同样的原色并不使所有 Rec.709 编码值与 sRGB 等同。参见 [ICC sRGB 条目](https://registry.color.org/rgb-registry/srgb)及 [ASWF ColorInterop 显示空间说明](https://github.com/AcademySoftwareFoundation/ColorInterop/blob/main/Recommendations/02_DisplayColorSpaces/DisplayColorSpaces.md)。文件头 `Color profile` 的解读依据 [Export LUT 作者手册](https://johnrellis.com/lightroom/exportlut.htm)：导出时选择的配置应匹配应用该 LUT 的图像空间；上述同配置输入输出路线是结合其工作流作出的推断。

- [逐文件分类机器索引](inventory/2026-10-30/photo-suitability/catalog.json)：包含每份来源的原始文件头、输入输出声明、分类理由、所需步骤、格式障碍和历史状态。
- [说明资料及校验值](photo-suitability-evidence.json)：随包 PDF 的页码、README、保存的来源页面和技术参考链接。
- [分类校验摘要](photo-suitability-receipt-2026-10-30.json)：完整覆盖统计、输入索引与运行库的 SHA-256。
- [原有总目录](INVENTORY.md)：仍保留原始整理快照。新的适用性结论保存在本次分类索引，不覆盖旧快照中的 `not_reassessed` 字段。

原件未移动、未改色值；分类时运行库为 **11 款**，随后接入 **50 种原始 CUBE**，再新增 **81 种 CLF 照片转换版**，当前合计 131 种。历史效果记录保持原样，新增 39 种 CUBE 及 81 种 CLF 均未做本轮照片效果测试。授权状态沿用来源清单，本表评价的是技术适用性。

在项目根目录可重新生成这一批次的静态分类（不渲染图片）：

```bash
.venv/bin/python lut-library/tools/classify_photo_suitability.py
```

备份时保留整个 `lut-library/`；完整分类索引位于本地 `inventory/`，与 LUT 原包一样不提交普通 Git，摘要和规则脚本可追踪。
