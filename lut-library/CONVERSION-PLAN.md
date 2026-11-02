# 372 种 LUT 的照片流程转换方案

> 此文件保留规划阶段的记录。后续首批 81 种已完成 CLF 照片转换、数值校验与接入；当前运行库为 131 种，执行结果见 [转换报告](PHOTO-CONVERSION.md)。下文的“未执行／50 种”是制定方案时的状态。

2026-10-30。**建议先推进 81 种输入、输出定义较明确的转换方案。** 本轮仅核对资料、文件头、现有数值范围记录和本机 ICC 标签，没有生成衍生 LUT、计算 LUT 效果或修改运行库；当前可用库仍为 50 种。

这里的“可靠”指可以依据明确的编码定义，建立可重复、可检验的转换链。它不意味着照片一定好看、还原作者全部 Lightroom 效果、完全无损，或已通过验证。所有生成、数值验证和照片效果测试都留待后续执行。

## 全部 372 种的处理结论

| 处理结论 | 映射数 | 构成与建议 | 逐文件清单 |
|---|---:|---|---|
| 转换链定义明确，优先实施 | **81** | Adobe RGB 79；明确 Gamma 2.4 的 2 种 | [81 种](inventory/2026-10-30/conversion-plan/defined_route.md) |
| 条件式方案，先补依据 | **23** | EditClips BT.1886 8；Lutify 工作空间版本 15 | [23 种](inventory/2026-10-30/conversion-plan/conditional.md) |
| 优先同款标准版 | **178** | IWLTBAP 53；Lutify 相机／扫描输入版 125 | [178 种及对应版本](inventory/2026-10-30/conversion-plan/prefer_standard.md) |
| 技术工具继续归档 | **76** | IWLTBAP Utility：Log→显示、显示→Log、Log→Log 等 | [76 种](inventory/2026-10-30/conversion-plan/utility_archive.md) |
| 资料不足，暂缓 | **14** | 已购柯达 5219 Log 版：新版 8、旧版 6 | [14 种](inventory/2026-10-30/conversion-plan/insufficient.md) |

总数按完整数值映射去重；不是新增风格数。每种映射只归入上表一行。HaldCLUT 和其他待确认 CUBE 不在这次 372 种的范围内，仍完整归档。

## 首批 81 种：方案明确

### Adobe RGB (1998)：79 种

包括 **ON1 77 种**，以及已购 Pocket Action 的 **“透亮室内”“星台光”**。文件头均标明 `AdobeRGB1998.icc`。Export LUT 作者说明，生成时选定的配置应与应用图像的空间匹配；本方案根据该工具的工作流，将输出也按同一配置解释。这是有依据的推断，尚未与作者原始预设逐图对照。[Export LUT 手册](https://johnrellis.com/lightroom/exportlut.htm)

拟采用相对编码值的确定性转换链：

```text
项目 sRGB 编码值
→ sRGB 解码为线性 RGB
→ D65 下线性 sRGB 转线性 Adobe RGB
→ Adobe RGB 编码
→ 原 LUT（保持原数值，使用四面体插值）
→ Adobe RGB 解码
→ 线性 Adobe RGB 转线性 sRGB
→ 扩展 sRGB 编码值
→ 项目既有强度混合及最终裁切
```

Adobe RGB 的原色、D65 白点及纯幂函数指数 **2.19921875**有明确规范；sRGB 采用分段函数。转换不是把两边 Gamma 都写成 2.2，也不是给文件换一个 sRGB 标签。[Adobe 编码规范，第 10 页](https://www.adobe.com/digitalimag/pdfs/AdobeRGB1998.pdf)、[ICC sRGB 定义](https://registry.color.org/rgb-registry/srgb)

本机已有 `/System/Library/ColorSync/Profiles/AdobeRGB1998.icc`，已静态读取其三通道 TRC，均为 2.19921875，并记录文件哈希；没有使用它计算颜色。这证明本机有可核查的标准配置，不证明它与作者电脑上的文件逐字节相同。

实施时优先采用有版本记录的标准矩阵与曲线，以相对 RGB 白点归一化；不额外模拟显示器亮度或观察环境。若改用 ICC 色彩管理引擎，必须固定源／目标 ICC、渲染意图、黑点补偿和裁切位置，作为另一套明确记录的实现；不能把 ICC 中经适配的 XYZ 标签直接当作 D65 矩阵拼接。

Adobe RGB 的部分颜色无法在 sRGB 中完整保留。原 LUT 的输出即使在 Adobe RGB 的 0–1 内，转换后仍可能超出 sRGB。方案保留中间浮点范围，由当前项目在强度混合后裁切；未来必须量化色域越界，不能宣称所有颜色均无损保留。

为使这条参考链可复现，拟明确采用如下工程延拓：转换后的负线性 sRGB 值走 `12.92 × C` 线性段，超过 1 的正值继续使用 sRGB 幂函数段；只在现有强度混合后裁切。该约定与色域压缩不是同一件事，需要单独记录，不能声称与所有 ICC 引擎的越界处理一致。

“星台光”的原始网格为 **40³**，当前导入器不直接接收。后续转换工具应把它作为原始源表读取，在完整转换链上一次采样为支持的网格，初拟 **65³**；避免先做一次独立重采样、再二次转换。提高网格不会恢复原表没有的细节。

### 明确 Rec.709 Gamma 2.4：2 种

已购 Pocket Action 的 **“富士 NC”“阿那亚 809”**，文件头都指向 Export LUT 自带的 `Rec709gamma2.4.icc`，比泛称 Rec.709 更明确。作者文档也区分其 Gamma 2.2 与 Gamma 2.4 配置。[配置说明](https://johnrellis.com/lightroom/exportlut.htm)

拟采用：

```text
sRGB 解码 → 纯 Gamma 2.4 编码 → 原 LUT
→ Gamma 2.4 解码 → sRGB 编码
```

两端按相同 Rec.709/sRGB 原色、D65 和归一化全范围处理，不需要额外色域矩阵。实施前核对原插件 ICC，或固定采用明确的标准曲线实现；不以名称相似的系统配置替代。

**本机的 `ITU-709.icc` 不能直接当作 Gamma 2.4 配置使用。** 静态读取显示，它采用带分段参数的 TRC，首参数约为 2.222229，不是纯 2.4。这一差异已记入机器索引的 ICC 检查记录。

首批可以先实施 ON1 77、“透亮室内”、以及这 2 种，共 **80 种**；“星台光”另做 40³ 源网格读取与重采样检查。此处是实施顺序，81 种仍全部属于定义明确的方案组。

## 23 种条件式方案

### EditClips BT.1886：8 种

包括 Cinema Print、Clean Neutral、Cool Negative、B&W Film、Slide Film、Super 8、Tungsten Night、Warm Negative。文件头明确输入、输出是 Rec.709 / BT.1886，但没有给出完整的黑白电平和范围约定。

BT.1886 的 EOTF 包含黑电平、白电平参数；只有采用黑电平为零并作白点归一化等相应条件，才简化成纯 Gamma 2.4。这个条件不能静默当作作者已经确认的事实。[ITU-R BT.1886，Annex 1](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.1886-0-201103-I%21%21PDF-E.pdf)

先确认或明确记录 `LB`、`LW`、归一化方式和输入范围，再用“sRGB ↔ 已确定参数的 BT.1886”前后包裹原 LUT。CUBE 的 0–1 输入域本身不证明内部使用视频窄范围，不能自动套 16–235 或 64–940 缩放。

### Lutify 工作空间版本：15 种

5 个风格各有 ACEScct→ACEScct、DWG→DWG、RWG→RWG，共 15 种。它们有潜在的适配路径，但目前不足以保证与作者的照片导出一致：

| 版本 | 数量 | 已知条件 | 仍需确认 |
|---|---:|---|---|
| ACEScct→ACEScct | 5 | 编码、AP1 原色有规范 | fylm.ai/ACES 版本、sRGB 输入变换、显示输出变换、是否已包含 gamut compress 等步骤 |
| DWG→DWG | 5 | DWG 色域有规范 | 是否搭配 DaVinci Intermediate、两端范围与渲染处理 |
| RWG→RWG | 5 | RWG 色域有规范 | 是否搭配 Log3G10、两端范围与渲染处理 |

相应标准分别见 [ACEScct](https://docs.acescentral.com/encodings/acescct/)、[Blackmagic DWG/Intermediate](https://documents.blackmagicdesign.com/InformationNotes/DaVinci_Resolve_17_Wide_Gamut_Intermediate.pdf?_v=1628751610000)、[RED RWG/Log3G10](https://docs.red.com/955-0187/PDF/915-0187%20Rev-C%20%20%20RED%20OPS%2C%20White%20Paper%20on%20REDWideGamutRGB%20and%20Log3G10.pdf)。标准说明“如何定义空间”，不会自动证明某个简称文件使用了完整的相同配置。

优先方案是取得或复现匹配版本的作者 Look，在明确的 sRGB 输入、sRGB 输出色彩管理流程中导出。fylm.ai 官方提供了针对照片的这种导出路线，且区分输入变换、Look 与输出变换。[fylm.ai 导出说明](https://fylm.ai/docs/lut-export-options/)

若只按数学公式把显示参考 sRGB 解码后转入工作空间，再反向编码，得到的是我们定义的新适配版本，不能直接宣称还原作者的场景参考调色。JPEG 的色调映射和高光损失不能从一个通用 Log 编码步骤中恢复。原文件头的节点摘要也不足以锁定所有内部 Look 资源及软件版本。

## 178 种优先使用标准版

**IWLTBAP 53 种**已逐项找到当前运行库中的同款 Standard/STD/K 系列候选。优先使用这些现有照片版本，无需为了数量再生成 53 张衍生表。对应关系基于名称、作者包目录及已有说明；有网格、修订差异时保留多个候选，没有做视觉等效确认。

**Lutify 125 种相机／扫描输入映射**只涉及 Amy、Claire、FilmBoost10、FilmTone3、PrintFilm2 五个风格。每个风格有一个 Rec709→Rec709 对应版本。后续应以这 5 个标准版或原始 Look 为中心，核实完整编码或重新导出 sRGB 版本，而不是逐一包装 125 个相机输入版本。

fylm.ai 官方的 ACES 流程把其 SDR Rec709 显示目标说明为 BT.1886、100 cd/m²，这是继续核对的依据；仍不能据此锁定本包所有历史导出的输入处理、黑电平与软件版本。[官方流程说明](https://fylm.ai/docs/how-to-setup-aces-colour-managed-workflow-in-davinci-resolve-for-use-with-fylm-ai/)

这 5 个 Rec709 对应文件目前仍在“待确认”归档中，**不属于本次 372 种计数，也没有自动加入 50 种运行库**。上面的 15 个工作空间版本同样来自这五个风格，不应再算成十五种独立风格。

Lutify 中 5 对 KineLog3/VLog 原始来源具有相同数值映射、不同输入标签。方案保留两个来源，并优先走同风格标准版路线，不能把重复数值当作两种相机输入空间等同的证明。

## 继续归档的 90 种

**76 种 IWLTBAP Utility**承担技术转换，包含相机 Log 到显示空间、显示空间到 Log、BMDFilm 到 Log-C 和 Generic 曲线等。它们可作为将来特定输入流程的工具，但不为当前 sRGB 照片提供独立创意风格的可靠承诺。本轮不反求整表、不取消或重复叠加其中的技术曲线。

**14 种已购柯达 5219 Log 版本**缺少足够的完整输入／输出定义。新版 8 种可以定位同编号标准版；标准版本身仍待确认。旧版 6 种没有足够依据建立一一对应关系。需向作者补齐输入色域、曲线及版本、输出空间、满／窄范围和是否已包含技术显示变换；当前没有发起联系或领取操作。

## 后续实施与验收约定

以下都是后续方案，本轮没有执行：

1. **固定输入与计算规则。** 对每个源文件记录 SHA-256、来源、原始域、网格、曲线／矩阵定义及实现版本。只处理明确批准的清单。保留原件，在独立 `derived/` 目录生成衍生文件，建立父映射 ID，不覆盖或改名伪装原件。
2. **先实现完整参考链，再一次采样。** 明确选择同一四面体插值，使用浮点中间值。初拟生成 `LUT_3D_SIZE 65`、0–1 输入域的纯 3D CUBE；不引入当前导入器不支持的 1D shaper 指令。OpenColorIO 提供输入／目标空间和网格配置的烘焙接口，但本轮未调用。[Baker 文档](https://opencolorio.readthedocs.io/en/latest/api/baker.html)
3. **保持强度语义。** 项目现在是在 sRGB 编码值上混合 LUT 结果，之后再裁切至 0–1。衍生 LUT 的完整输出也应回到 sRGB；不要把强度混合挪到 Adobe RGB/Log 域，也不要在混合前静默截断输出。新采用的色域压缩或早期裁切必须另建版本并记录原因。
4. **数值验收先于照片验收。** 未来用灰阶、边界颜色及独立采样点比较“参考转换链”和“衍生 CUBE”，同时记录裁切前的范围、混合后的误差；检查多个强度档位。可暂以最终归一化 RGB 的最大误差不超过 `1/255`、RMS 不超过 `0.25/255` 作为初始工程门槛，必须明确这不是行业标准，也不是本轮通过结果。65³ 不满足时停止接入，保留浮点参考链并评估实现方式，不强行宣称可靠。
5. **文件与元数据验收。** 精确核对行数、有限数值、输入域、UTF-8 和实际文件大小 ≤10 MiB；不能只因 65³ 就假定一定小于限制。记录原件／衍生哈希、方案版本、输入输出、色域政策、数值验证状态，以及独立的照片效果状态。
6. **最后才考虑启用。** 数值转换通过不等于照片效果已验收。效果测试与新增接入由后续任务安排，本轮不改变现有运行库。

原 372 种中已有 **8 种**数据的输出范围超出 0–1（7 种 Lutify、1 种 IWLTBAP）；这是既有静态数值范围记录，未用照片或采样图计算。它们均有单独标记。转换计划必须明确如何处理负值／超白，不能在解码前随意截断。

## 交付记录

- [逐映射机器索引](inventory/2026-10-30/conversion-plan/catalog.json)：372 种方案、708 份来源上下文、标准版候选、阻碍和实施条件。
- [本轮证据记录](conversion-plan-evidence.json)：官方技术文档链接及本地资料校验值。
- [方案校验摘要](conversion-plan-receipt-2026-10-30.json)：372 个源文件哈希、分类与当前运行索引的保护摘要。
- [当前 50 种可用 LUT](CATALOG.md)：本轮未变化。

可离线重新生成方案列表；该脚本不包含颜色处理或下载操作：

```bash
.venv/bin/python lut-library/tools/plan_photo_conversions.py
```
