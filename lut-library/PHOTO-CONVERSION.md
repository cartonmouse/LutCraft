# 81 种 LUT 照片转换与数值验收

2026-10-30。**81 种全部转换、通过数值校验并接入本地项目，当前运行库共 131 种。** 原有 50 种的 ID、路径、字节和元数据保持不变。没有照片效果测试，没有新增下载、自动分析任务或发布操作。

## 结果与格式

| 项目 | 结果 |
|---|---:|
| Adobe RGB (1998) 来源 | 79 种：ON1 77 + Pocket Action 2 |
| Rec.709 Gamma 2.4 来源 | 2 种：富士 NC、阿那亚 809 |
| 已通过并接入的转换版 | 81 个自包含 CLF 3 文件 |
| 当前运行库 | 50 个 CUBE + 81 个 CLF = 131 种 |
| 未接入的原始 CUBE 映射 | 860 种，继续归档 |
| 本轮照片效果测试 | 0 |

先按原方案生成并检查了 81 个 65³ CUBE。仅 BW10、BW4、Cinematic-10 三个通过既定门槛，其余 78 个在局部非线性变化或色域边界出现较大插值误差。**没有降低门槛或启用不合格版本。** 这批统一改用 CLF 保存颜色空间转换与原 LUT 的完整计算链，避免重新采样为单张三维网格。65³ 对照文件和全部误差记录独立保留，不在运行目录中。

CLF 中嵌入原 LUT 的 float32 数值表和四面体插值定义，80 个保留 32³ 源网格，“星台光”保留 40³ 源网格。源 CUBE 原件仍逐字节保留；CLF 是新派生文件，不冒充作者原版。当前单次调色入口已支持 CLF 和 CUBE。旧工作台上传入口及只支持 CUBE 的第三方软件不能直接使用这些 CLF。

## 数值验收

参考链使用独立的 float64 四面体插值器、标准色域矩阵与分段 sRGB 公式；实际文件使用项目同版本 OpenColorIO 2.6.0 的 float32 CPU 路径加载。每个源表还用 8,219 个颜色点交叉核对独立插值器与 OpenColorIO，源网格 40³ 也包含在内。

每种覆盖 65³ 网格单元中心、均匀随机、暗部偏置、六个色域边界面、十二条边、灰阶、sRGB 拐点、原网格结点及其邻域，并另用独立种子的 100 万个随机点复核；每种合计 1,728,530–1,812,075 个输入样本。分别在 25%、50%、75%、100% 强度下，按项目实际的“编码 sRGB 混合后再裁切”计算误差。

| 指标 | 门槛 | 全批最差实测 |
|---|---:|---:|
| 最终 RGB 最大绝对通道误差 | 1/255 ≈ 0.00392157 | 0.001582059，约 0.4034 个 8-bit 色阶 |
| 最终 RGB RMS | 0.25/255 ≈ 0.00098039 | 0.0000110754，约 0.00282 个 8-bit 色阶 |
| 混合／裁切前最大误差（诊断） | 单独记录 | 0.002713005 |

这些是对确定样本集合的数值验收，不能证明连续色域每一点都满足同一上界，也不代表照片好看、风格选择准确或与作者原始 Lightroom 预设逐图等效。尚未做任何本轮照片预览。

## 颜色规则与可复现性

- Adobe RGB 使用 D65 原色矩阵与精确指数 563/256 = 2.19921875。Rec.709 Gamma 2.4 使用相同 sRGB/Rec.709 原色及纯 2.4 幂函数；没有借用系统 ITU-709.icc。
- 使用相对 RGB 编码，不额外套用绝对显示亮度、观察环境补偿、黑点补偿或视频窄范围缩放。
- 保留负值及超白浮点输出，在项目原有强度混合之后再裁切；没有提前裁切或添加色域压缩。Adobe RGB 超出 sRGB 的颜色不能宣称无损保留。
- CLF 的 monCurve 使用 gamma 2.4、offset 0.055 的连续版本，其计算得到的拐点／斜率与标准中取整的 0.04045／12.92 略有区别。报告已明确记录，并针对标准分段参考链验证了实际差异；不宣称二者数学上完全相同。
- 按 Export LUT 同配置工作流解释源输出空间，这是有资料依据的推断，不是原作者预设的视觉认证。
- 固定源 SHA-256、派生 SHA-256、矩阵、曲线、插值方式、实现脚本摘要、NumPy/OpenColorIO 版本、随机种子及采样集合。CLF 不含外部文件引用。

技术依据：[Adobe RGB 规范](https://www.adobe.com/digitalimag/pdfs/AdobeRGB1998.pdf)、[ICC sRGB 定义](https://registry.color.org/rgb-registry/srgb)、[Export LUT 手册](https://johnrellis.com/lightroom/exportlut.htm)、[OpenColorIO 曲线定义](https://opencolorio.readthedocs.io/en/latest/api/transforms.html#exponentwithlineartransform)。

## 原件、接入与复核

原有 991 种来源映射的统一索引不改写；81 种源 CUBE、下载原包和其他素材保留原路径与哈希。这 81 个派生版本不计作新增采购来源或额外独立风格。其余 291 种待转换方案、569 种待确认 CUBE、293 个 HaldCLUT 和 602 个附属格式文件继续归档。

- [运行目录](CATALOG.md)：131 种，项目下一次调用直接读取。
- [接入回执](photo-conversion-receipt-2026-10-30.json)：原 50 种快照、当前目录哈希、81 个父映射及派生文件。
- [完整数值结果](derived/2026-10-30-srgb-v1/conversion.json)：包括全部 65³ 对照版的通过／失败结果。
- [转换配方](derived/2026-10-30-srgb-v1/recipe.json)：颜色规则、版本与实现参数。
- [原 50 种快照](inventory/2026-10-30/before-photo-conversion/catalog.json)：供接入前后逐项比对。

元数据中的 `parent.path` 和 `parent.sha256` 指向真正的上游原件；`original_sha256` 为兼容旧代码仍表示运行文件自身的完整性摘要，另有 `artifact_sha256` 明确标记。所有新增版本均标记 `derived: true`、`file_modified: true`、`effect_test_status: not_tested`。

项目只增加了已归档、通过摘要校验的 CLF 加载路径，严格接受自包含 Matrix/Exponent/LUT3D 子集；文件大小上限仍为 10 MiB。XML 外部引用、实体、未知节点和非有限数据会被拒绝。照片强度混合、裁切和图像输出流程未改动。

```bash
.venv/bin/python lut-library/tools/convert_photo_luts.py verify
.venv/bin/python lut-library/tools/organize_existing.py verify
# 需要重新计算时才执行；只处理 RGB 数组，不读取照片：
.venv/bin/python lut-library/tools/convert_photo_luts.py verify --numerical
```

## 逐项接入清单

误差以“最终归一化 RGB 最大绝对通道误差 × 255”表示；格式统一为 CLF，网格列表示内嵌原表，并非重新采样网格。

| 来源 | 名称 | 原表网格 | 最大误差（8-bit 色阶） | 派生文件 |
|---|---|---:|---:|---|
| ON1 | Aqua | 32³ | 0.039625 | [CLF](derived/2026-10-30-srgb-v1/cube-90150778b8a2e01491f5/srgb.clf) |
| ON1 | Aqua and Orange Dark | 32³ | 0.171630 | [CLF](derived/2026-10-30-srgb-v1/cube-de576e407f96296daef3/srgb.clf) |
| ON1 | Blues | 32³ | 0.229531 | [CLF](derived/2026-10-30-srgb-v1/cube-11157bb80d04c139e7e3/srgb.clf) |
| ON1 | BW1 | 32³ | 0.005877 | [CLF](derived/2026-10-30-srgb-v1/cube-e6c75f3ee0ff9243c314/srgb.clf) |
| ON1 | BW10 | 32³ | 0.006413 | [CLF](derived/2026-10-30-srgb-v1/cube-8bf10f65a472a54e9d37/srgb.clf) |
| ON1 | BW2 | 32³ | 0.009007 | [CLF](derived/2026-10-30-srgb-v1/cube-9a81bbb6d38928143f79/srgb.clf) |
| ON1 | BW3 | 32³ | 0.007573 | [CLF](derived/2026-10-30-srgb-v1/cube-3a0715c42b4e6c12ca78/srgb.clf) |
| ON1 | BW4 | 32³ | 0.004976 | [CLF](derived/2026-10-30-srgb-v1/cube-b9a42d29f43a3dc07bed/srgb.clf) |
| ON1 | BW5 | 32³ | 0.006618 | [CLF](derived/2026-10-30-srgb-v1/cube-19d961650ab36c6d7795/srgb.clf) |
| ON1 | BW6 | 32³ | 0.006917 | [CLF](derived/2026-10-30-srgb-v1/cube-831d0f05d604b31d1fb4/srgb.clf) |
| ON1 | BW7 | 32³ | 0.009177 | [CLF](derived/2026-10-30-srgb-v1/cube-26884363a1e824c350d4/srgb.clf) |
| ON1 | BW8 | 32³ | 0.007097 | [CLF](derived/2026-10-30-srgb-v1/cube-594db366fdfc4aeb2d7b/srgb.clf) |
| ON1 | BW9 | 32³ | 0.011116 | [CLF](derived/2026-10-30-srgb-v1/cube-a35f2b6ba602ececab11/srgb.clf) |
| ON1 | Cinematic-1 | 32³ | 0.113328 | [CLF](derived/2026-10-30-srgb-v1/cube-f4b4a5fc05d2d62fe89b/srgb.clf) |
| ON1 | Cinematic-10 | 32³ | 0.005720 | [CLF](derived/2026-10-30-srgb-v1/cube-7d52b7b43d3dde1287f6/srgb.clf) |
| ON1 | Cinematic-2 | 32³ | 0.170064 | [CLF](derived/2026-10-30-srgb-v1/cube-7573608f9521316f9558/srgb.clf) |
| ON1 | Cinematic-3 | 32³ | 0.081891 | [CLF](derived/2026-10-30-srgb-v1/cube-0e8db828e332c23e3bd6/srgb.clf) |
| ON1 | Cinematic-4 | 32³ | 0.081067 | [CLF](derived/2026-10-30-srgb-v1/cube-33941569bfb22bcbf8da/srgb.clf) |
| ON1 | Cinematic-5 | 32³ | 0.096537 | [CLF](derived/2026-10-30-srgb-v1/cube-74b83dcc04db36f0c920/srgb.clf) |
| ON1 | Cinematic-6 | 32³ | 0.083548 | [CLF](derived/2026-10-30-srgb-v1/cube-4dc16f340635b6fc7761/srgb.clf) |
| ON1 | Cinematic-7 | 32³ | 0.039377 | [CLF](derived/2026-10-30-srgb-v1/cube-33d894467b9c1582393a/srgb.clf) |
| ON1 | Cinematic-8 | 32³ | 0.064533 | [CLF](derived/2026-10-30-srgb-v1/cube-bdfd499015f9f271e2d3/srgb.clf) |
| ON1 | Cinematic-9 | 32³ | 0.116763 | [CLF](derived/2026-10-30-srgb-v1/cube-7612dacf47c134576b9e/srgb.clf) |
| ON1 | Earth Tone Boost | 32³ | 0.137773 | [CLF](derived/2026-10-30-srgb-v1/cube-5958a7d70eb93b9dc429/srgb.clf) |
| ON1 | Green_Blues | 32³ | 0.162890 | [CLF](derived/2026-10-30-srgb-v1/cube-aebf8e8715cab123376d/srgb.clf) |
| ON1 | Green_Yellow | 32³ | 0.187570 | [CLF](derived/2026-10-30-srgb-v1/cube-4974c06996791e7d4f7b/srgb.clf) |
| ON1 | Landscape1 | 32³ | 0.069664 | [CLF](derived/2026-10-30-srgb-v1/cube-7de0040b2ffcff473e8b/srgb.clf) |
| ON1 | Landscape10 | 32³ | 0.142588 | [CLF](derived/2026-10-30-srgb-v1/cube-c60a001e0b675ead43a8/srgb.clf) |
| ON1 | Landscape2 | 32³ | 0.065027 | [CLF](derived/2026-10-30-srgb-v1/cube-5ff4c310f68cb3dffd01/srgb.clf) |
| ON1 | Landscape3 | 32³ | 0.056068 | [CLF](derived/2026-10-30-srgb-v1/cube-aa44fbaf92b5bdac6b0c/srgb.clf) |
| ON1 | Landscape4 | 32³ | 0.092550 | [CLF](derived/2026-10-30-srgb-v1/cube-c59b703eb0e88186fa1b/srgb.clf) |
| ON1 | Landscape5 | 32³ | 0.076652 | [CLF](derived/2026-10-30-srgb-v1/cube-359e621b1f67e45e8d24/srgb.clf) |
| ON1 | Landscape6 | 32³ | 0.041383 | [CLF](derived/2026-10-30-srgb-v1/cube-5bd2e9d74fec13729976/srgb.clf) |
| ON1 | Landscape7 | 32³ | 0.025072 | [CLF](derived/2026-10-30-srgb-v1/cube-23cb1bb2d78524799d81/srgb.clf) |
| ON1 | Landscape8 | 32³ | 0.041803 | [CLF](derived/2026-10-30-srgb-v1/cube-2cfe8e19f6a305ac5859/srgb.clf) |
| ON1 | Landscape9 | 32³ | 0.111789 | [CLF](derived/2026-10-30-srgb-v1/cube-1bd1fac2b4b2d4182624/srgb.clf) |
| ON1 | LC1 | 32³ | 0.010648 | [CLF](derived/2026-10-30-srgb-v1/cube-299266c5e1209d83e332/srgb.clf) |
| ON1 | LC10 | 32³ | 0.055274 | [CLF](derived/2026-10-30-srgb-v1/cube-9003295b9577835fc8f1/srgb.clf) |
| ON1 | LC2 | 32³ | 0.008756 | [CLF](derived/2026-10-30-srgb-v1/cube-656db5ff45fdd4cb9e29/srgb.clf) |
| ON1 | LC3 | 32³ | 0.046864 | [CLF](derived/2026-10-30-srgb-v1/cube-0e1d64b153821931cf6a/srgb.clf) |
| ON1 | LC4 | 32³ | 0.086793 | [CLF](derived/2026-10-30-srgb-v1/cube-f5809229a6e0a731c848/srgb.clf) |
| ON1 | LC5 | 32³ | 0.033026 | [CLF](derived/2026-10-30-srgb-v1/cube-c014f78f76bb50e8744c/srgb.clf) |
| ON1 | LC6 | 32³ | 0.033616 | [CLF](derived/2026-10-30-srgb-v1/cube-34f24178f97a0b333455/srgb.clf) |
| ON1 | LC7 | 32³ | 0.126760 | [CLF](derived/2026-10-30-srgb-v1/cube-ff7d4da216259f4954a6/srgb.clf) |
| ON1 | LC8 | 32³ | 0.071206 | [CLF](derived/2026-10-30-srgb-v1/cube-8bc786bb0f53f674eb9c/srgb.clf) |
| ON1 | LC9 | 32³ | 0.403425 | [CLF](derived/2026-10-30-srgb-v1/cube-af9019af602fd86b6b38/srgb.clf) |
| ON1 | Moody1 | 32³ | 0.124564 | [CLF](derived/2026-10-30-srgb-v1/cube-65d7ddfca17e8562c1f8/srgb.clf) |
| ON1 | Moody10 | 32³ | 0.010765 | [CLF](derived/2026-10-30-srgb-v1/cube-d01c4c86d53d7c898e9e/srgb.clf) |
| ON1 | Moody2 | 32³ | 0.006109 | [CLF](derived/2026-10-30-srgb-v1/cube-b57ddcd38e0e0dc15ef9/srgb.clf) |
| ON1 | Moody3 | 32³ | 0.007899 | [CLF](derived/2026-10-30-srgb-v1/cube-2fbee2ca0bb636117347/srgb.clf) |
| ON1 | Moody4 | 32³ | 0.116052 | [CLF](derived/2026-10-30-srgb-v1/cube-beb037e960e151e20fbc/srgb.clf) |
| ON1 | Moody5 | 32³ | 0.039908 | [CLF](derived/2026-10-30-srgb-v1/cube-df3a691652ca57999086/srgb.clf) |
| ON1 | Moody6 | 32³ | 0.116533 | [CLF](derived/2026-10-30-srgb-v1/cube-de2993411bac0d4e2092/srgb.clf) |
| ON1 | Moody7 | 32³ | 0.077399 | [CLF](derived/2026-10-30-srgb-v1/cube-d2f33d71047dce9e0fee/srgb.clf) |
| ON1 | Moody8 | 32³ | 0.083313 | [CLF](derived/2026-10-30-srgb-v1/cube-82c52501a714a59ce250/srgb.clf) |
| ON1 | Moody9 | 32³ | 0.057805 | [CLF](derived/2026-10-30-srgb-v1/cube-836f8d6af2d803236523/srgb.clf) |
| ON1 | NW-1 | 32³ | 0.073481 | [CLF](derived/2026-10-30-srgb-v1/cube-dd8cbd28a789e47b0f47/srgb.clf) |
| ON1 | NW-10 | 32³ | 0.008215 | [CLF](derived/2026-10-30-srgb-v1/cube-89fdb7ce8065a98b5318/srgb.clf) |
| ON1 | NW-2 | 32³ | 0.035819 | [CLF](derived/2026-10-30-srgb-v1/cube-0c6962135556a2e8bcf3/srgb.clf) |
| ON1 | NW-3 | 32³ | 0.069952 | [CLF](derived/2026-10-30-srgb-v1/cube-54efbdc3bb567a7f5bee/srgb.clf) |
| ON1 | NW-4 | 32³ | 0.230411 | [CLF](derived/2026-10-30-srgb-v1/cube-929661e2bf7aae3903c8/srgb.clf) |
| ON1 | NW-5 | 32³ | 0.198783 | [CLF](derived/2026-10-30-srgb-v1/cube-8f6cf960c207025083b7/srgb.clf) |
| ON1 | NW-6 | 32³ | 0.053896 | [CLF](derived/2026-10-30-srgb-v1/cube-dcf745bf95062531cc1f/srgb.clf) |
| ON1 | NW-7 | 32³ | 0.043226 | [CLF](derived/2026-10-30-srgb-v1/cube-c96bb71cefe7b89997ba/srgb.clf) |
| ON1 | NW-8 | 32³ | 0.142022 | [CLF](derived/2026-10-30-srgb-v1/cube-9c19ba5ec6f29a9353a6/srgb.clf) |
| ON1 | NW-9 | 32³ | 0.036409 | [CLF](derived/2026-10-30-srgb-v1/cube-60e0165f1a8a5ffbef38/srgb.clf) |
| ON1 | Oranges | 32³ | 0.152361 | [CLF](derived/2026-10-30-srgb-v1/cube-9bfa4d2b7cb46e050f5a/srgb.clf) |
| ON1 | Portrait1 | 32³ | 0.085093 | [CLF](derived/2026-10-30-srgb-v1/cube-01d43fd0038a9e9ccbd8/srgb.clf) |
| ON1 | Portrait10 | 32³ | 0.042045 | [CLF](derived/2026-10-30-srgb-v1/cube-133740a488be57af6b9a/srgb.clf) |
| ON1 | Portrait2 | 32³ | 0.007650 | [CLF](derived/2026-10-30-srgb-v1/cube-6fc8da09d4bcb17e48b1/srgb.clf) |
| ON1 | Portrait3 | 32³ | 0.013843 | [CLF](derived/2026-10-30-srgb-v1/cube-7dcc869da5701b7ae373/srgb.clf) |
| ON1 | Portrait4 | 32³ | 0.007952 | [CLF](derived/2026-10-30-srgb-v1/cube-e11d1adbfc92ea4e3b5d/srgb.clf) |
| ON1 | Portrait5 | 32³ | 0.072617 | [CLF](derived/2026-10-30-srgb-v1/cube-83cdbb2ab8017f283fe9/srgb.clf) |
| ON1 | Portrait9 | 32³ | 0.026065 | [CLF](derived/2026-10-30-srgb-v1/cube-1482966ab924c68a66e8/srgb.clf) |
| ON1 | Purple | 32³ | 0.082985 | [CLF](derived/2026-10-30-srgb-v1/cube-206f9dcc0e8a1387bb46/srgb.clf) |
| ON1 | Reds | 32³ | 0.184062 | [CLF](derived/2026-10-30-srgb-v1/cube-c7cd4c53097e5f59e047/srgb.clf) |
| ON1 | Reds_Oranges_Yellows | 32³ | 0.058120 | [CLF](derived/2026-10-30-srgb-v1/cube-cca3006b6c48383a3a85/srgb.clf) |
| Pocket Action | 富士 NC | 32³ | 0.017907 | [CLF](derived/2026-10-30-srgb-v1/cube-b94ba102ef76f41cf0f7/srgb.clf) |
| Pocket Action | 星台光 | 40³ | 0.300732 | [CLF](derived/2026-10-30-srgb-v1/cube-4dd1631d9dfbe2ef223d/srgb.clf) |
| Pocket Action | 透亮室内 | 32³ | 0.061916 | [CLF](derived/2026-10-30-srgb-v1/cube-79319696a461885027c3/srgb.clf) |
| Pocket Action | 阿那亚 809 | 32³ | 0.025607 | [CLF](derived/2026-10-30-srgb-v1/cube-17328770fe5eccbe4ab0/srgb.clf) |
