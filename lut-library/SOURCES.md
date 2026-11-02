# LUT 来源与采购清单

更新：2026-10-30。当前项目只处理照片。**用户已停止继续领取和下载。** 已取得的素材统一见[已有 LUT 总目录](INVENTORY.md)：1393个CUBE来源文件合并为991种映射，另保留293个HaldCLUT文件；未新增效果测试。

已按后续授权将 **50 种可直接使用的映射**接入本地运行库：xMosaique 18、ON1 Color & Mood 10、IWLTBAP 22（保留原有 11 种、新增 39 种）。其余 941 种 CUBE 及其他格式继续归档。见 [可用目录](CATALOG.md)和 [接入记录](photo-activation-receipt-2026-10-30.json)；新增款尚未测试效果。

登记 **29 个来源/产品条目**（含3套已购素材、10组已收集免费来源及后续领取/采购线索）。这是一版可持续扩充的清单，不代表覆盖全部市场。

下方首批公开下载的历史批次归档 **1050 个 CUBE 源文件**，按完整数值与输入域去重后 **663 种映射**；其中 **11 种**与原有库重复，新增 **652 种映射**。另保留 **293 个 HaldCLUT 文件**（含1个Identity空白模板），没有转换、没有与 CUBE 做跨格式去重。

[打开本地素材目录](collected/2026-10-30/README.md) · [机器可读来源清单](sources.json) · [下载清单](free-downloads-2026-10-30.json) · [本批校验记录](collection-receipt-2026-10-30.json)

## 已收集的免费来源

下表数量来自本机实际文件。CUBE 的“映射数”只合并数值完全相同的文件，不能理解为经过效果判定的独立风格数。HaldCLUT 是以图像文件保存的颜色查找表，本项目暂时不直接加载。

| 来源 | CUBE 源文件 / 来源内映射 | HaldCLUT | 输入及记录 |
|---|---:|---:|---|
| [Joseph Carey — Rec.709 77 款](https://josephcarey.com/luts/) | 77 / 77 | 0 | 仅收 Rec.709 创意包；照片输入匹配待验证。 |
| [xMosaique — 18 款](https://xmosaique.com/luts/) | 18 / 18 | 0 | 发布者标注 Rec.709 / sRGB。 |
| [RawTherapee HaldCLUT](https://rawpedia.pixls.us/film_simulation/) | 0 / 0 | 295 | 原包说明默认sRGB，特殊输入依文件名；含294张模拟表和1张Identity模板，保持HaldCLUT原格式。 |
| [YahiaAngelo / Film-Luts](https://github.com/YahiaAngelo/Film-Luts) | 296 / 287 | 0 | 社区汇总，输入空间依文件说明，未验证。 |
| [IWLTBAP 官方免费包](https://luts.iwltbap.com/) | 522 / 155 | 0 | 含标准版本及原包附赠Log等变体；输入依文件说明。 |
| [TDCat 免费 LUT 合集](https://tdcat.com/downloads/free-lut-packs) | 29 / 29 | 0 | 创意LUT，输入空间待核实。 |
| [EditClips 创意 LUT](https://editclips.online/tools/free-luts-for-video) | 30 / 30 | 0 | 本次选择创意款，略过明确标注Log转Rec.709的技术转换。 |
| [VideoEditingLUTs 单款公开下载](https://videoeditingluts.com/) | 12 / 12 | 0 | 创意LUT，源站建议先转换到Rec.709，照片输入待验证。 |
| [RocketStock / Shutterstock 35 款](https://www.shutterstock.com/blog/free-luts-for-log-footage) | 35 / 35 | 0 | 35款包包括标准sRGB/Rec.709创意款；逐款输入待确认。未收单独13款Log包。 |
| [FilterGrade 五个官方免费包](https://filtergrade.com/free-luts-download/) | 31 / 31 | 0 | 电影、暖色、胶片、Super8和彩色包；输入依原作者说明，照片适配待验证。 |

IWLTBAP 复用项目原有7个免费原包，并补收官方免费合集；这些旧包中的未登记成员也进入本批归档。来源之间可能重复，表内数量不能直接相加作为新增量。

## 后续人工领取进度

2026-10-30：ON1 完整免费包已领取并下载，含100个CUBE原件；原包与校验记录保存在 `collected/2026-10-30-assisted/`。已合并为97种映射并进入全库总目录；上方首批历史统计不变，未做效果测试。

2026-10-30：Lutify.me 免费包已由用户通过 fylm.ai Lite 免费账户领取并下载。[原包](collected/2026-10-30-assisted/Lutify-Free-LUTs-Pack.zip)和[校验记录](collected/2026-10-30-assisted/lutify-receipt.json)已归档，ZIP完整性与复制前后SHA-256检查通过。包内有5种风格，每种含30个CUBE输入版本及1个XMP，共150个CUBE和5个XMP；其中5个CUBE标注Rec.709输入/输出。所有版本保留，已完成跨库精确去重，共145种映射并进入全库总目录；未做照片效果测试或运行库启用，上方首批历史统计不变。

## 已购买素材

| 素材 | 当前状态 | 下一步 |
|---|---|---|
| Pocket Action LUT预设 | 已有 28 个CUBE，照片适用性依输入版本 | 补充店铺、订单及作者授权信息；不重复采购 |
| 林馆长 iPhone 专用 LUT 合集2 | 已有 12 个CUBE，照片适用性依输入版本 | 补充店铺、订单及作者授权信息；不重复采购 |
| 柯达 5219 | 已有 34 个CUBE，照片适用性依输入版本 | 补充店铺、订单及作者授权信息；不重复采购 |

已有购买库详情见 [PURCHASED.md](PURCHASED.md)。购买包共74个CUBE、72种数值映射；原先14款照片候选只是优先测试列表，不代表其他素材被排除。

## 待领取、核实与采购

P1：优先补充照片标准输入和来源授权；P2：扩展风格覆盖；P3：线索或特殊输入，暂缓。优先级表示收集顺序，不是效果评分。

| 优先级 | 来源 / 产品 | 获取条件、价格 | 下一步 |
|---|---|---|---|
| P1 | [Bounce Color Free LUTs](https://www.bouncecolor.com/products/free-luts) | 免费商品；结账要求邮箱、姓名及账单地址 | 用户选择暂时跳过，未下单、未下载；保留来源 |
| P1 | [CINECOLOR Free Creative Tools](https://cinecolor.io/collections/free-creative-tools) | 已检查Day for Night免费商品；0元结账也要求账单地址 | 按当前地址偏好暂缓，未下单、未下载；保留来源 |
| P1 | [IWLTBAP 完整 LUT 包](https://luts.iwltbap.com/) | 作者官网购买；官网当日显示主包US$25；Bundle US$39，结账为准 | 先以免费包评估覆盖，采购前核实服务授权和已购重复 |
| P1 | [ON1 Free LUTs](https://www.on1.com/free/luts/) | 已由用户完成邮箱领取，原包下载成功，100个CUBE合并为97种映射 | 原包、逐文件索引及统一精确去重已完成；照片输入待确认 |
| P2 | [CinePacks LUTs Free Sample Pack](https://cinepacks.store/products/cinepack-luts-free-sample-pack) | 0元结账要求邮箱、姓名、账单地址和电话 | 按当前地址偏好暂缓，未下单、未下载；保留来源 |
| P2 | [FILM CRUX — Grecian Ideal](https://www.filmcrux.com/free-grecian-ideal-luts) | 用户已完成邮箱领取；原包实含9个CUBE | 9种映射已进入统一索引；原包完整保留，照片输入待核实 |
| P2 | [PHLEARN 免费 LUT Sample Pack](https://phlearn.com/tutorial/luts-sample-pack/) | 免费账户领取完成；5种风格，10个CUBE原件为两套相同的5款；另含3DL/CSP/ICC各5个及PDF指南 | [原包](collected/2026-10-30-assisted/PHLEARN%20Free%20LUTs%20Sample%20Pack%202026.zip)已校验并进入统一索引，5种映射；未做效果测试 |
| P2 | [FreshLUTs 创作者免费 LUT 平台](https://freshluts.com/) | 下载需免费账户；当前注册要求Name、Email和Password，无账单地址字段 | 用户已停止继续领取；保留来源线索，尚未下载 |
| P2 | [FixThePhoto 免费 LUT](https://fixthephoto.com/free-luts) | [Photoshop Contrast免费单款](https://fixthephoto.com/photoshop-luts/download-2)：用户反馈等待邮件；页面仍有验证码过期与站点额度提示，发送成功未确认 | 此前等待邮件且提交未确认；用户已停止继续领取，尚未下载 |
| P2 | [Color Grading Central 免费包](https://www.colorgradingcentral.com/free-luts-sign-up/) | 用户已提交，等待邮件中的下载链接；页面提示最多5分钟，并检查推广/垃圾邮件 | 此前等待邮件；用户已停止继续领取，尚未下载 |
| P2 | [Lutify.me 免费 LUT 包](https://lutify.me/free-luts/) | 免费账户领取完成；5种风格，150个CUBE输入版本合并为145种映射，另含5个XMP | 已进入统一索引并完成精确去重；照片适配与服务授权待核实 |
| P2 | [Lutify.me Bundle Pack](https://lutify.me/products/luts/bundle-pack/) | 与fylm.ai订阅/既有账户条件关联；按官网账户与套餐报价，不把限定账户价格当通用价 | 明确购买的是LUT下载权还是软件订阅，再采购 |
| P2 | [Panasonic LUMIX Lab 创作者 LUT](https://www.panasonic.com/global/consumer/lumix/lumix-lab.html) | 通过LUMIX Lab应用获取；导出及服务使用条件待核实；应用内来源；逐项核实 | 确认官方导出方式，按创作者记录来源 |
| P2 | [Triune Digital LUTs Library Vol.2](https://www.triunedigital.com/collections/all/color-grading) | 官网购买，核对合集包含的具体产品；分类页当日标价US$120；最终结账为准 | 先核对风格覆盖和服务授权；优先Rec.709版本 |
| P3 | [Juan Melara Print Film Emulation LUTs](https://juan-melara.squarespace.com/blog/print-film-emulation-luts-for-download-old) | 作者旧文章；需核对当前下载及输入要求；旧文提供免费资源 | 作为低优先来源线索，照片管线明确后再获取 |
| P3 | [Resolve Directory 来源发现目录](https://resolve.directory/) | 仅用作作者和产品线索；非采购商品 | 转到原作者页面逐项核实，不把目录条数计为LUT数量 |

首批公开下载未注册账号、提交邮箱、订阅或下单，新增采购支出为0。后续人工领取按上方进度单独登记：用户已完成ON1、FILM CRUX邮箱领取及fylm.ai Lite、PHLEARN免费账户注册与下载；Color Grading Central与FixThePhoto等待邮件链接，后者尚未确认发送成功。4个已取得的人工领取原包已统一整理：269个CUBE来源文件合并为256种映射，均为旧库之外的新映射。首批历史统计保持不变，全库统计见总目录；其余来源停止继续领取。

## 授权与来源记录

收集入库不等于确认可以把LUT内置到对外产品或提供原文件下载。逐来源记录如下；有不同许可的文件以每款 `sources` 字段和原包说明为准。

| 来源 | 当前记录 |
|---|---|
| [Joseph Carey — Rec.709 77 款](https://josephcarey.com/luts/) | 作者允许个人/客户作品，禁止出售或再分享 LUT 文件；服务内置授权未确认。 |
| [xMosaique — 18 款](https://xmosaique.com/luts/) | 混合许可：第三方声明列出的13款为MIT衍生，其余CC BY-NC 4.0；MIT集合上游权利仍需核实。 |
| [RawTherapee HaldCLUT](https://rawpedia.pixls.us/film_simulation/) | 原包README声明CC BY-SA 4.0，署名Pat David、Pavlov Dmitry、Michael Ezra；使用/修改/分发时保留相应署名及许可条件。 |
| [YahiaAngelo / Film-Luts](https://github.com/YahiaAngelo/Film-Luts) | 仓库声明MIT（另有说明除外），维护者同时声明不拥有所有LUT；上游授权待核实。 |
| [IWLTBAP 官方免费包](https://luts.iwltbap.com/) | 允许在作品中使用；禁止转售/分享文件；项目服务授权待确认。 |
| [TDCat 免费 LUT 合集](https://tdcat.com/downloads/free-lut-packs) | 作者公开提供免费ZIP；未找到明确服务内置/分发许可。 |
| [EditClips 创意 LUT](https://editclips.online/tools/free-luts-for-video) | 作者声明自行按颜色数学生成，可免费用于商业作品且无需署名；未找到独立的文件再分发/服务内置条款。 |
| [VideoEditingLUTs 单款公开下载](https://videoeditingluts.com/) | 官网FAQ声明免费、免版税、可用于商业作品且无需署名；单独下载无需邮箱。项目服务内置/再分发范围待核实。 |
| [RocketStock / Shutterstock 35 款](https://www.shutterstock.com/blog/free-luts-for-log-footage) | 作者公开免费包，明确禁止转售或再分发素材；服务内置授权未确认。 |
| [FilterGrade 五个官方免费包](https://filtergrade.com/free-luts-download/) | 作者文章提供公开免费下载，保留原包说明；服务内置/再分发授权待确认。 |

- xMosaique 的13款MIT衍生与5款CC BY-NC已逐文件标注；公开MIT声明及其上游权利未确认的情况均保留。
- 品牌和胶片名称按来源记录，不代表品牌官方出品。
- 原始下载、作者说明、网页快照及SHA-256保存在本批目录。公开页面明确的使用许可与未确认事项分别记录。

## 归档方式与后续维护

- `collected/2026-10-30/downloads/`：本轮下载的原始压缩包与单文件。
- `collected/2026-10-30/assets/`：按数值或字节内容去重后的原始LUT，不改色值。
- `collected/2026-10-30/catalog.json`：每款文件、网格、来源、许可、重复关系和待测试状态。
- `collected/2026-10-30/documents/`、`evidence/`：原包说明和来源页面。
- `collected/2026-10-30/archive-inventory.json`：说明文档、其他格式与无法解析的原件记录。
- 实际素材与网页快照只保存在本地，已排除普通Git提交；备份请复制整个 `lut-library/`。清单、下载URL、校验摘要和脚本可纳入Git。

本批 602 种映射通过当前引擎的格式检查；这里只检查文本、网格和数值范围，不代表照片效果或输入空间已验证。名称显示为Log等特殊输入的 110 种映射仅作原包归档，不作为已适配照片。

无法解析的CUBE原件：0 个。若出现无法解析的文件，将保留原件并单独登记，不计入有效映射数。

运行库仍为原来的11款；本批每款都保持 `enabled: false`、`effect_test_status: not_tested`。

从项目根目录重建或检查本批：

```bash
.venv/bin/python lut-library/tools/collect_free_luts.py fetch --manifest lut-library/free-downloads-2026-10-30.json
.venv/bin/python lut-library/tools/collect_free_luts.py index --manifest lut-library/free-downloads-2026-10-30.json
.venv/bin/python lut-library/tools/collect_free_luts.py verify --manifest lut-library/free-downloads-2026-10-30.json
```

新增来源时，先核对作者页面和领取条件；完成公开下载后保留原包及来源，再做数值去重。输入判断、效果测试和启用由后续单独执行。
