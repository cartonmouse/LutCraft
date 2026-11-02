# HaldCLUT 照片接入记录

2026-10-30 从已有 RawTherapee Film Simulation Collection 归档接入 **291 种不同数值映射**，当前共 **422 种**：50 个原始 CUBE、81 个 CLF 照片转换版、291 个原生 HaldCLUT。本轮没有继续下载 LUT，也没有批量生成照片效果图。

292 个风格源文件全部通过数值校验。其中 `TealOrange1` 与 `TealOrange` 的文件字节不同，解码后的完整查色映射相同，合并为一个运行条目并保留两个名称及源文件记录。另一个 Identity TIFF 是基准模板，继续归档，不作为风格加入选择器。未进行跨格式的视觉相似度去重；映射数量不等于独立视觉风格数量。

## 使用

后续状态：手动试用入口已按用户要求暂时关闭；下述操作描述保留接入时的用法，新增效果图库正在讨论方案。运行库及记录保留。

刷新 [本地页面](http://127.0.0.1:4175/)，在“手动试用 LUT”搜索 **RawTherapee**，选择照片、LUT 与强度后应用。新增条目与原有 CUBE/CLF 共用照片归一化、强度混合与结果保存流程，每次从原图开始。OpenClaw 的当前目录读取入口也能获取新增条目。

## 读取方法与依据

原包 README 明确声明：除文件名另行说明外，查色表使用 sRGB。本批没有其他输入空间的文件名声明。README 与作者署名已复制到 [许可与来源说明](licenses/rawtherapee-haldclut/README.txt)，按原包 CC BY-SA 4.0 记录 Pat David、Pavlov Dmitry、Michael Ezra。

HaldCLUT PNG 表示查色数值，不是效果预览图。实际运行保留原始 PNG 字节，不改变网格或色值。原始 292 个风格源中，291 个是 144³ 网格，1 个是 256³；65 个是灰度采样表，`Negative` 为 16 位 RGB，其余是 8 位 RGB。删除重复运行映射后仍保留全部原始文件。

当前 OCIO 不接受大于 129³ 的内存 LUT3D 网格，所以本轮增加独立的 Hald 查色处理器：红轴最快，随后绿轴、蓝轴，按原始整数位深归一化，使用三线性插值。灰度表等量扩展为 RGB；不执行表图像的 ICC 转换、自动旋转或 16 位转 8 位。照片自身仍按现有流程转换为 sRGB。两个最近使用的查色表可缓存，RGB 计算分块执行。

格式和轴顺序依据 [RawPedia Film Simulation](https://rawpedia.pixls.us/film_simulation/)；插值约定核对 [RawTherapee Hald 实现](https://raw.githubusercontent.com/RawTherapee/RawTherapee/dev/rtengine/clutstore.cc)。这只对应 Hald 查色步骤，不宣称与 RawTherapee 完整 RAW 工作流或胶片实物效果相同。原有 CUBE/CLF 继续使用原来的 OCIO 四面体插值。

## 数值校验

- 每个风格源验证 **134,245 组 RGB**：33³ 全域网格、随机样本、原表采样点及其两侧、六个边界面、灰阶和越界截断。
- 生产 float32 分块处理器与独立 float64 八角点加权参考计算对比，另检查 25%、50%、75%、100% 强度混合。
- 门槛：最大通道误差 ≤ `2e-5`，RMS ≤ `2e-6`；292 个源均通过。全批最大通道误差为 **0.00000109585**，约 **0.00028 个 8 位码值**。
- 原始 16 位 Identity TIFF 抽样验证轴顺序与量化精度；未接入选择列表。
- 单元检查覆盖非对称通道变换、可解析三线性函数、8/16 位 Identity、灰度表、边界、非法表、文件哈希和调用入口；手动接口另外覆盖实际 Hald 调用。

以上是采样数值与功能验证，不是连续域误差证明或照片观感验收。新增条目的效果状态保持 `not_tested`，由用户逐款查看。

## 原件与历史记录

原有 131 种的 ID、路径、文件字节和元数据保持不变。接入前的完整目录、元数据及已验证实现备份在 `inventory/2026-10-30/before-hald-activation/`。旧接入回执未修改；新回执记录前后实现哈希，旧验证器沿回执链检查 50 → 131 → 422 的历史与当前状态。

- [当前目录](CATALOG.md)
- [逐文件数值校验、原件及重复映射记录](derived/2026-10-30-hald-native/validation.json)
- [Hald 接入回执](hald-activation-receipt-2026-10-30.json)

其余 **860 种 CUBE 来源映射**及附属格式仍保持归档：291 种待进一步适配或保留技术用途，569 种输入输出资料不充分。没有将这些项目默认按 sRGB 启用。

在项目根目录复核完整归档、历史运行库及当前加载入口：

```bash
.venv/bin/python lut-library/tools/organize_existing.py verify
```

只复核本批 Hald（加 `--numerical` 才重跑数值样本）：

```bash
.venv/bin/python lut-library/tools/activate_hald_luts.py verify
```
