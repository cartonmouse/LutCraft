# 购买素材整理记录

当前全库整理结果见[已有 LUT 总目录](INVENTORY.md)。下文的14款照片候选是2026-10-29的优先预览子集，不是可用于照片的数量上限；其他素材完整保留，照片适配后续再确认。2026-10-30本轮仅离线整理，未新增预览或效果测试。

2026-10-29 从用户指定的百度网盘下载目录整理三套素材。项目原有运行库保留 11 款；购买素材单独存放在 `purchased/2026-10-29/`，用于核实输入条件、对比和选择。

2026-10-30 用户明确：**当前项目仅处理照片，不处理视频**。当前保留已接入的 11 款，新增素材优先验证 14 款照片候选；设备专用或输入未明的 LUT 只有在确认适用于照片 sRGB 管线后才考虑接入。视频/Log 版本仅归档，包含旧版目录中的 Log 文件，不进入本轮照片候选或接入计划。目录中的“视频版本”记录原包用途，不代表项目支持或计划开发视频功能。

| 原包 | 源 CUBE | 整理后的映射 |
|---|---:|---:|
| Pocket Action LUT预设 | 28 | 28 |
| 林馆长 iPhone 专用 LUT 合集2 | 12 | 12 |
| 柯达 5219 / XH | 34 | 32 |
| 合计 | 74 | 72 |

| 分类 | 数量 | 使用依据 |
|---|---:|---|
| 照片候选 | 14 | 林馆长 709 拍照版 6 款、XH 5219 标准新版 8 款；优先做 sRGB 样张确认 |
| 设备/输入待确认 | 31 | Pocket/Action、Mimo；部分文件注释为 Rec.709 gamma 2.4 |
| 视频版本 | 14 | XH 新版 V-Log 8 款；林馆长 Blackmagic 视频版 6 款，具体输入未注明 |
| 旧版归档 | 11 | XH 标准和 Log 旧版，扣除一个重复映射 |
| 待处理 | 2 | 星台光：40³ / Adobe RGB；透亮室内：32³ / Adobe RGB |

两个重复映射组是 `XH_5219_7` / `H哈苏暖`、`5219_cold` / `H哈苏冷`。逐项记录了每个原始文件的校验值和用途目录。相同数值不表示两种输入用途已经验证等同。

- [购买库说明](purchased/2026-10-29/README.md)
- [完整可点击目录](purchased/2026-10-29/CATALOG.md)
- [机器索引](purchased/2026-10-29/catalog.json) / [照片候选索引](purchased/2026-10-29/photo-candidates.json)
- [建筑海岸样片对比](purchased/2026-10-29/previews/coast/README.md)
- [粉色花海样片对比](purchased/2026-10-29/previews/pink-grass/README.md)

每个候选在两张项目样片上生成 50% 和 100% 强度预览。图像归一化为 sRGB 后直接应用原始 CUBE，使用项目的 OpenColorIO 四面体插值，不额外调曝光、白平衡、对比度或饱和度。这里只测试实际渲染效果，尚未验证人像、其他拍摄条件或 LUT 的准确输入空间。

所有 74 个 CUBE 均通过网格、行数、有限数值和校验值检查；73 个源文件符合当前引擎格式要求，一个 40³ 源文件不受当前导入器支持。格式通过不等于色彩空间兼容。

同时复制了 46 个松散 XMP（45 个不同文件）、4 个原始 ZIP 和 11 张说明图；视频教程和安装程序保留在原下载位置，原包清单记录其路径和 SHA-256。没有运行安装程序或修改下载文件。

每款元数据可供项目导入器读取，保存稳定 ID、名称、标签依据、来源、原名、输入条件及 SHA-256。`enabled=false`、`compatibility=unknown`；当前单次调色 Agent 只读取主 `catalog.json`，不会选到这些待确认文件。确认照片效果和输入/输出后，可将选定条目接入主库；旧版管理页也可导入照片候选目录为“待确认”资产。

本地购买库整体排除普通 Git，现有 Program 打包入口只包含主库。用户已说明购买；下载材料中没有明确的软件嵌入或再分发条款，需将购买凭证和条款补入来源记录。`重要声明.jpg` 是调色使用说明，不是已核实的再分发授权。

## 复核与重新整理

```bash
.venv/bin/python lut-library/tools/organize_purchased.py --verify --output lut-library/purchased/2026-10-29

.venv/bin/python lut-library/tools/organize_purchased.py \
  --source /path/to/purchased-luts \
  --output lut-library/purchased/2026-10-29
```

重复执行只接受内容一致的文件；已修改文件不会被覆盖。完整原包路径及大文件清单保存在购买库的 `source-inventory.json`。备份时复制购买库，并另保留原下载目录中的视频教程。

用新的样片生成预览，输出必须是尚不存在的目录：

```bash
.venv/bin/python lut-library/tools/preview_purchased.py \
  --library lut-library/purchased/2026-10-29 \
  --source /path/to/photo.jpg \
  --output lut-library/purchased/2026-10-29/previews/my-photo
```
