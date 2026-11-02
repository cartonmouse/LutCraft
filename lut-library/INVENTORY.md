# 已有 LUT 总目录

更新：2026-10-30。已按用户要求停止领取和下载；本次仅整理本地已有文件。

共 **1393 个 CUBE 来源文件**，按完整数值和输入域合并为 **991 种颜色映射**。
另有 **293 个 HaldCLUT 文件**（含 1 个 Identity 模板），保持原格式。不同输入版本或格式不等于不同视觉风格。

后续已接入 **50 种直接使用的 CUBE**，并将首批 **81 种**转换为通过数值校验的 CLF 照片版，运行目录共 **131 种**。全部原件保留；其余 **860 种来源映射**、HaldCLUT 和附属格式继续归档。没有新增照片效果测试，见 [运行目录](CATALOG.md)与 [转换报告](PHOTO-CONVERSION.md)。原统一索引与整理回执保留接入前快照，其中的 11 / 980 是当时状态；派生文件不计入原始 991 种来源映射的总数。

| 来源 | CUBE来源文件 | 来源内映射数 | HaldCLUT唯一文件 |
|---|---:|---:|---:|
| Pocket Action LUT预设 | 28 | 28 | 0 |
| 林馆长 iPhone 专用 LUT 合集2 | 12 | 12 | 0 |
| 柯达 5219 | 34 | 32 | 0 |
| ON1 Free LUTs | 100 | 97 | 0 |
| Lutify.me 免费 LUT 包 | 150 | 145 | 0 |
| Joseph Carey — Rec.709 77 款 | 77 | 77 | 0 |
| xMosaique — 18 款 | 18 | 18 | 0 |
| RawTherapee HaldCLUT | 0 | 0 | 293 |
| YahiaAngelo / Film-Luts | 296 | 287 | 0 |
| IWLTBAP 官方免费包 | 522 | 155 | 0 |
| TDCat 免费 LUT 合集 | 29 | 29 | 0 |
| EditClips 创意 LUT | 30 | 30 | 0 |
| VideoEditingLUTs 单款公开下载 | 12 | 12 | 0 |
| RocketStock / Shutterstock 35 款 | 35 | 35 | 0 |
| FilterGrade 五个官方免费包 | 31 | 31 | 0 |
| FILM CRUX — Grecian Ideal 免费 LUT | 9 | 9 | 0 |
| PHLEARN 免费 LUT Sample Pack | 10 | 5 | 0 |

来源之间可能共享映射，来源内映射数不能直接相加作为全库总数。源文件数不重复计入运行库工作副本。

精确合并后记录 402 个重复来源项，涉及 131 组映射；所有原包和来源记录保留，未删除下载原件。

## 文件入口

- [照片适用性分类：直接使用／需要转换／待确认](PHOTO-SUITABILITY.md)
- [已接入的 131 种照片 LUT](CATALOG.md)
- [81 种转换与数值校验结果](PHOTO-CONVERSION.md)
- [372 种待转换 LUT 的逐项方案](CONVERSION-PLAN.md)
- [完整 CUBE 文件目录](inventory/2026-10-30/CUBES.md)
- [统一机器索引](inventory/2026-10-30/catalog.json)
- [重复映射及全部来源](inventory/2026-10-30/duplicates.json)
- [其他格式与说明文档索引](inventory/2026-10-30/auxiliary.json)
- [本次整理校验摘要](inventory-receipt-2026-10-30.json)
- [来源与领取进度](SOURCES.md)

## 照片使用状态

- 已完成后续静态分类：991 种 CUBE 映射中，50 种有直接使用依据、372 种需要转换或适配、569 种待确认。逐文件理由见 [照片适用性分类](PHOTO-SUITABILITY.md)；原统一索引保留整理时的快照，新的结论及接入状态分别存于独立分类索引和接入记录。
- 以前的14款照片候选只是当时优先预览的子集，不是全库可用于照片的上限。其他素材完整保留。
- 输入空间、设备专用版本、Log版本、文件头颜色配置均保留在来源和复核标记中；不自动宣称与sRGB照片兼容。
- PHLEARN的10个CUBE为两套相同的5款；Lutify的150个CUBE属于5种风格的多输入版本，不算150种视觉风格。
- ON1 中 77 种 Adobe RGB 映射已在后续静态分类中列为需要转换，10 种 Color & Mood 列为有直接使用依据，另 10 种待确认；原始色值保持不变。
- 旧预览保持原记录，新领取资产仍为not_tested；项目当前只处理照片。

## 其他格式

| 格式 | 按字节去重的文件数 |
|---|---:|
| 3DL | 306 |
| CSP | 10 |
| ICC | 107 |
| ONPRESET | 10 |
| XMP | 169 |

XMP、ONPreset和其他格式按原件归档，不计入CUBE数量，未做跨格式视觉去重或格式转换。

## 本地存储与复核

原有目录不搬移：已购包在purchased/，首批免费包在collected/2026-10-30/，人工领取原包及CUBE在collected/2026-10-30-assisted/。统一索引和补充格式在inventory/2026-10-30/。

备份整个lut-library目录；已购包中的教程视频/安装程序仍在原下载位置，详见原购买库清单。所有授权说明保留；收集不代表已确认服务内置或再分发许可。

```bash
.venv/bin/python lut-library/tools/organize_existing.py verify
```
