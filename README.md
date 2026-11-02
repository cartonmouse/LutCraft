<div align="center">

<img src="docs/assets/lut-studio-icon-white.png" alt="LutCraft 项目图标" width="180" />

# LutCraft

**一个理解照片风格、选择真实 LUT，并交付调色成品的 AI 照片助手。**

用一句话描述想要的感觉，或先在风格图库找到喜欢的效果，再用于自己的照片。

<p>
  <a href="integrations/openclaw/single-pass/README.md">Agent 接入</a> ·
  <a href="prototypes/lut-studio/README.md">风格图库</a> ·
</p>

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)
![FastAPI](https://img.shields.io/badge/Web-FastAPI-009688.svg)
![OpenClaw](https://img.shields.io/badge/Agent-OpenClaw-6E56CF.svg)
![LUT](https://img.shields.io/badge/LUT-CUBE%20%2F%20CLF%20%2F%20HaldCLUT-FF8C42.svg)
![Image](https://img.shields.io/badge/Image-JPEG%20%2F%20PNG-34785C.svg)

</div>

#### **找到照片的下一种感觉。**

## 功能闭环

| 环节 | 能力 |
| --- | --- |
| 描述风格 | 提供照片，用自然语言表达暖调、黑白等偏好，也可指定 LUT 和强度 |
| 浏览与选择 | 搜索名称、品牌或关键词，筛选彩色／黑白风格 |
| 理解效果 | 查看风格介绍、主样片原图对比，以及每款的 3 张辅助效果图 |
| Agent 决策 | OpenClaw 调用原生工具，结合用户要求、LUT 描述与照片统计选择风格 |
| 真实调色 | 使用实际 LUT 处理原图，按指定强度生成新图片 |
| 保存与交付 | 保留原图，提供结果预览、图片下载和 Agent 批次 ZIP |

**两种入口，共用同一调色引擎：**

- **风格图库：**先看样片，再上传自己的照片；单次处理一张，支持 50%／100% 强度，无需模型调用。
- **自然语言 Agent：**提交照片和风格要求，由宿主调用 OpenClaw；每批 1–10 张，同批使用相同 LUT 和强度。当前图库页面不提供聊天输入框。

## 快速启动

### 获取项目

```bash
git clone https://github.com/cartonmouse/LutCraft.git
cd LutCraft
```

### 环境要求

- Python 3.11 或更高版本。
- Node.js 22.12 或更高版本、pnpm；前端声明的包管理器版本为 11.25.0。
- 使用自然语言 Agent 时，需要项目内 OpenClaw，以及支持工具调用的 OpenAI-compatible 模型服务。
- 当前启动脚本使用 Bash，已在 macOS 验证。

### 安装

在项目根目录执行：

```bash
bash scripts/setup.sh
```

脚本创建 `.venv`、安装锁定的 Python 和前端依赖，并构建旧版 React 工作台。仅在 `.env` 不存在时复制 `.env.example`，不会覆盖已有配置。当前风格图库使用原生 HTML／CSS／JavaScript。

### 启动图库

```bash
bash prototypes/lut-studio/start.sh
```

启动后访问：

- 风格图库：<http://127.0.0.1:4175/>
- 我的结果：<http://127.0.0.1:4175/results>
- 健康检查：<http://127.0.0.1:4175/api/health>

如果端口被占用，可以换用 4176：

```bash
LUT_PROTOTYPE_PORT=4176 bash prototypes/lut-studio/start.sh
```

此时访问 <http://127.0.0.1:4176/>。停止服务时在终端按 `Ctrl+C`；当前服务仅监听本机地址，使用单个 worker。

### 首次克隆后的素材状态

**仓库包含源码、目录和样片配置，不附带第三方 LUT 原文件、真实照片及渲染结果。** 全新克隆可以启动页面，但在恢复素材前，图库会等待样片构建。

恢复实际效果需要：

1. 与 `lut-library/catalog.json` 对应的 LUT 原文件。
2. `data/style-gallery/current.json` 及其指向的完整图库构建。
3. 如需重新制作样片，另行恢复配置中引用的照片，或换成自己有权使用的照片。

具体目录、校验方式与重建说明见 [素材恢复指南](docs/GITHUB-PUBLISH.md#克隆后的运行边界)。不要把本地照片、购买包或 `.env` 加入 Git。

## LUT 与风格图库

截至 2026-11-02，现有本地素材配置的交付状态如下；这些数量不代表 GitHub 附带的素材数量。

| 内容 | 当前状态 |
| --- | --- |
| 可用且已上架的 LUT | 706 款 |
| 运行格式 | 326 种 CUBE、89 种 CLF、291 种 HaldCLUT |
| 主样片 | 每款一组，保留原图及 50%／100% 效果 |
| 辅助效果图 | 每款 3 张，共 2,118 张，均按对应 LUT 的 100% 强度渲染 |
| 风格说明 | 已上架款均有介绍、特征与辅助图说明 |
| 暂时下架 | 290 款待适配、未配齐样片的条目；文件与配置保留 |

图库支持名称、品牌与关键词搜索，彩色／黑白筛选，首批加载 48 款。详情可以对比原图、切换主样片强度、查看辅助图，并将当前风格用于自己的照片。

样片使用真实照片，同一原片可以用于不同 LUT。效果图展示 LUT 对该输入的实际作用；原片可能已有色调，不作为未经调色的校准图，也不保证任意照片获得相同观感。

目录与配置入口：

- [`lut-library/CATALOG.md`](lut-library/CATALOG.md)：本地可用 LUT 目录。
- [`lut-library/ARCHIVE-INTAKE.md`](lut-library/ARCHIVE-INTAKE.md)：归档接入依据与待适配范围。
- [`prototypes/lut-studio/style-samples.json`](prototypes/lut-studio/style-samples.json)：逐款主样片绑定。
- [`prototypes/lut-studio/style-stories.json`](prototypes/lut-studio/style-stories.json)：风格介绍与辅助图配置。

## Agent 与模型配置

### 图库模式

浏览样片、选择 LUT 和应用照片由本地程序直接完成，不需要 API Key，也不调用生图模型。实际效果来自 LUT 数值变换。

### 自然语言调色

安装项目隔离的 OpenClaw 运行时：

```bash
source scripts/env.sh
"$LUT_PNPM" --dir integrations/openclaw/local install --frozen-lockfile
```

本地固定版本为 OpenClaw `2026.6.11`。在 `.env` 中填写自己的模型配置：

```dotenv
MODEL_API_URL=https://your-provider.example/v1
MODEL_NAME=your-tool-calling-model
MODEL_API_KEY=your-api-key
```

原生运行器读取这三项配置，将模型服务地址作为 OpenAI-compatible Base URL；也兼容以 `/chat/completions` 结尾的地址。本地已有 `deepseek-flash` 的真实调用记录，具体可用模型以你接入的服务为准。

Agent 调用两个原生工具：

| 工具 | 作用 |
| --- | --- |
| `lut_inspect_request` | 读取本次风格要求、图片亮度／RGB 统计和真实 LUT 目录 |
| `lut_apply` | 按选定的 `lut_id`、`strength`、`reason` 执行调色，返回真实成品与结果清单 |

例如：“把这两张照片调成柔和中性的经典黑白，强度 100%。”

任务由本地宿主准备输入并调用 `run_openclaw`，不是在图库页内发送聊天。当前选择依据不包含视觉场景识别；输入或配置不完整时会报错，不自动切换到其他模型。调用细节见 [单次调色接入说明](integrations/openclaw/single-pass/README.md)。

`.env.example` 中的 `AGENT_RUNTIME` 用于旧工作台，不是当前图库的模型开关。当前未在 OpenAgent 远端部署；平台模型、附件交付与发布需另行验收。

## 技术架构

```text
入口 A：照片 + 自然语言风格             入口 B：风格图库
             │                               │
             ▼                               ▼
       OpenClaw main                   浏览 / 对比 / 上传
             │                               │
       inspect → apply                 选择 LUT 与强度
             │                               │
             └─────────────┬─────────────────┘
                           ▼
                    共享照片处理引擎
                           │
              输入校验 → LUT 摘要校验
                           │
              原图处理 → LUT 应用 → 编码
                           │
                           ▼
                 新图片 / 清单 / 结果页
```

| 层 | 技术与职责 |
| --- | --- |
| Web | FastAPI、Uvicorn、原生 HTML／CSS／JavaScript；图库与结果查看 |
| Agent | OpenClaw 原生插件；理解要求、选择真实 LUT、调用受控工具 |
| Imaging | pyvips／libvips、OpenColorIO、NumPy；照片归一化、LUT 处理与强度混合 |
| Catalog | JSON 目录、元数据、来源与 SHA-256；限定可用风格并校验文件完整性 |
| Gallery | 样片绑定、逐款介绍、不可变构建；完整生成后切换当前构建指针 |
| Results | 本地文件与 JSON 清单；保留原图、处理结果和历史批次 |
| Legacy | React 工作台与 SQLite；保留旧版参数调节、预设和项目管理实现 |

## 项目目录

```text
LutCraft/
├─ backend/
│  ├─ app/                      图像引擎、LUT 加载、Agent 运行与结果管理
│  ├─ tests/                    后端与数值测试
│  └─ requirements.lock         Python 依赖锁文件
├─ prototypes/lut-studio/       当前风格图库、结果页、服务与样片配置
├─ integrations/openclaw/
│  ├─ single-pass/              原生插件与 Agent 规则
│  ├─ local/                    隔离运行时的依赖配置
│  └─ plugin/                   旧工作台工具适配实现
├─ frontend/                    旧版 React 工作台
├─ lut-library/                 LUT 目录、来源、元数据与管理脚本
├─ scripts/                     安装、启动、样片构建和发布准备
├─ docs/                        项目图标、素材与发布说明、旧版文档
├─ data/                        本地照片、图库构建、结果与会话（不提交）
└─ .env.example                 空环境变量模板
```

## 数据与持久化

| 路径 | 保存内容 |
| --- | --- |
| `data/style-gallery/current.json` | 当前激活的图库构建 ID |
| `data/style-gallery/builds/<id>/` | 构建清单、预览图、辅助图及文件摘要 |
| `data/lut-preview/runs/<id>/` | 用户照片应用结果、原图与展示记录 |
| `data/single-pass/<task_id>/` | 本地 Agent 的输入、隔离运行状态和调色成品 |
| `lut-library/catalog.json` | 可用 LUT 索引；实际 LUT 文件保存在目录指定位置 |

每次从原图生成新文件，原图保留。图库构建完整生成后才更新当前指针，失败时不会将半成品发布为当前版本。`data/` 全部留在本地，需要单独备份；GitHub 源码不包含个人结果与会话。

## API

以下为当前本机图库服务接口：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/health` | 运行时与图库模式状态 |
| `GET` | `/api/styles` | 已上架风格、预览地址、详情介绍和页面临时令牌 |
| `GET` | `/api/styles/{build_id}/files/{filename}` | 获取清单登记的样片或效果图 |
| `POST` | `/api/styles/apply` | 对上传照片应用指定构建中的 LUT |
| `GET` | `/api/preview` | 最近完成的结果 |
| `GET` | `/api/history` | 已保存的结果批次 |
| `GET` | `/api/previews/{run_id}` | 指定批次详情 |
| `GET` | `/api/previews/{run_id}/files/{filename}` | 指定批次的结果文件 |

应用接口通过查询参数接收 `build_id`、`lut_id` 和 `strength=0.5|1`，请求体为原始 JPEG／PNG 字节，需要当前页面的 `x-lut-preview-token`，并校验同源 Origin。完整约定见 [图库接口说明](prototypes/lut-studio/README.md#接口与边界)。

服务默认不开放 `/docs`，旧手动预览写入入口也默认关闭；健康检查中的 `configured` 指 Agent 模型运行时是否就绪，不影响不依赖模型的图库操作。


## 文档

- [Agent 接入说明](integrations/openclaw/single-pass/README.md)：原生工具、模型配置、输入输出与平台交付边界。
- [风格图库说明](prototypes/lut-studio/README.md)：样片制作、详情配置、构建发布与接口。
- [LUT 归档接入](lut-library/ARCHIVE-INTAKE.md)：已接入映射与待适配素材。



