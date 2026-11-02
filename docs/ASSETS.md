# 素材与许可范围

GitHub 发布以源码为主，不将本地开发素材自动视为可再分发资产。

| 内容 | 是否进入发布目录 | 说明 |
| --- | --- | --- |
| Python、TypeScript、JavaScript、HTML、CSS、脚本与测试 | 是 | 保留当前源码和构建配置 |
| Python／pnpm 依赖锁文件 | 是 | 依赖本体不提交，安装时获取 |
| `.env.example` | 是 | 空配置模板；真实 `.env` 留在本地 |
| LUT 目录、元数据、来源说明与收录回执 | 是 | 保留索引、摘要、适配状态；不包含 LUT 数值文件 |
| 样片绑定、风格文案与辅助图配置 | 是 | 来源链接移除临时令牌；照片本体不提交 |
| CUBE、CLF、Hald PNG、购买包与其他调色素材 | 否 | 仅本地使用；使用和分发范围由各自许可决定 |
| 原始照片、图库构建、处理结果、截图与历史会话 | 否 | 保留本地；源码发布不包含这些数据 |
| 衍生 LUT、验证中间目录与下载包内 PDF | 否 | 不作为源码交付；说明中的相关链接仅在本地素材齐全时有效 |
| `docs/assets/lut-studio-icon-white.png` | 是 | 本项目使用 image_gen 生成的白底图标；非第三方摄影样片 |
| `prototypes/lut-studio/assets/lucide.min.js` | 是 | 随附 `LUCIDE-LICENSE`；保留原有许可声明 |

项目尚未选择整体开源许可证，本次整理不擅自添加 MIT、Apache 等授权。第三方代码、依赖与 LUT 的许可各自独立，不因项目发布而改变。

不要将 `scripts/prepare_openagent.py` 产生的 Program 目录上传 GitHub：它面向另一个交付流程，会复制本机已恢复的 LUT 文件。GitHub 源码导出应使用 `scripts/prepare_github.py`。
