# MythWeaver 同行对标报告

更新时间：2026-11-17（Asia/Shanghai）  
证据锚点：`origin/master` `168954f`（含已合并 PR #3–#38）  
基准产品：MythWeaver（`ider5/MythWeaver`）— 单机 FastAPI + Vue 3 网络小说续写  
材料：仓库 README / `docs/` / 当前代码与测试。同行格沿用 [#19](https://github.com/ider5/MythWeaver/pull/19) 与 2026-11-16 笔记，本轮没有重爬对方仓库。

## 1. 结论摘要

MythWeaver 的差异仍在长文入库压缩（分层摘要 + sqlite-vec）、Story Bible 与大纲门禁、SSE 续写、Critic 回路、最多 10 章的半自动连续生成，以及 Compose / Makefile 自托管。

Round 2 已落到 master 的主路径包括：品牌首页与外观、从零开书与续写分流、LLM 命名配置、首次引导与健康一览、写作质量信号、单本 ZIP 备份、任务断线重连与重启可恢复草稿、EPUB 导出与章节版本对照、生成章回写确认、任务中心与去重、匿名 OpenAI 兼容端点。

仍敞开的差距：

1. **写法 / 去 AI** 仍以固定提示词为主（`anti_ai.j2` 等）。阶段 Skill 导入仍在推进，尚未合入。
2. **分发** 仍是 Docker Compose、Makefile、源码。没有安装包，也没有单二进制（打包再打磨中）。
3. **生成章回写** 可以勾选后写入，但没有原文出处。原稿入库仍自动合并设定。
4. **界面只有中文。** README 双语不等于产品内双语写作。
5. 没有 WebDAV、段落级修稿接受、EPUB 导入（导入在推进）。世界地图、全自动导演、漫画 / 短剧不追。
6. 没有同书样本的上下文 token 或一致性对照，不能称超越。

目标路径不变：对齐 Pagekin 的本地闭环、show-me-the-story 的自托管；Biz Novel Studio 只作能力上限，不复制多媒体延展。

## 2. 主要同行

| 项目 | 形态 | 为何选为基准 |
|------|------|--------------|
| [EthanYoQ/Pagekin](https://github.com/EthanYoQ/Pagekin) | Electron 本地写作 | UX / 闭环主基准 |
| [ExplosiveCoderflome/AI-Novel-Writing-Assistant](https://github.com/ExplosiveCoderflome/AI-Novel-Writing-Assistant) | Electron + LangGraph | 能力上限（Biz Novel Studio） |
| [Nigh/show-me-the-story](https://github.com/Nigh/show-me-the-story) | 单二进制 + Web UI | 轻量自托管基准 |
| [sigpanic/goink](https://github.com/sigpanic/goink) | Wails + sqlite-vec | 写后记忆对照 |
| [yuanbw2025/storyforge](https://github.com/yuanbw2025/storyforge) | 浏览器长篇工作台 | 章后确认对照 |

## 3. 能力矩阵

图例：● 强 / ◐ 有 / ○ 弱或无 / 未复测 = 本轮没有重读该仓库

| 能力 | MythWeaver | Pagekin | Biz Novel Studio | show-me-the-story |
|------|:---:|:---:|:---:|:---:|
| 本地 / 自托管 | ● | ● | ● | ● |
| 长文导入入库 | ● | ● | ● | ● |
| 分层摘要压缩超长文 | ● | ◐ | ◐ | ◐ |
| 向量 RAG | ● sqlite-vec | ◐ | ● Qdrant | ◐ |
| Story Bible | ● 可编辑 + 关系图 / 时间线（#12 #25）+ 生成章回写（#21） | ● | ● | ● |
| 大纲 / 蓝图 | ● 蓝图字段（#6） | ● | ● | ● |
| 流式续写 | ● SSE + 断线重连 / 草稿（#38） | ● | ● | ● |
| Critic / 审校 | ● LangGraph ≤2 轮（#7）+ 勾选修稿（#8）+ 质量信号（#36） | ● | ● | ● |
| 拆书 / 仿写 | ● 原稿 / 参考（#10） | ● | ● | ◐ |
| 导入引导 / 空状态 | ●（#17）+ 首次引导 / 健康（#35） | ● | ● | ◐ |
| 写作 / 大纲台流程 | ● 大纲三步、续写四步（#18）；版本行对照（#30） | ● | ● | ◐ |
| 任务可视 / 取消 | ● 状态、进度、取消 / 重试（#11 #20）；同书同类型进行中再入队 409（#27）；重启可恢复草稿（#38） | ● | ● | ◐ |
| 自动导演 / 批量 | ● ≤10 章半自动（#13）；篇幅 / 钩子缺失可暂停（#36） | ◐ | ● | ◐ |
| 用量与阶段路由 | ●（#14）+ 命名 LLM 配置（#32） | ◐ | ● | ○ |
| 一键分发 | ● Compose + package / Makefile（#4 #15）。无安装包、无单二进制 | ● | ● | ● |
| CI | ●（#3） | ● | ● | ● |
| 从零开书 | ● 与续写分流（#24） | ● | ● | ● |
| 章后状态回写 | ● 勾选写入或放弃（#21）。无出处 | ◐ | ◐ | ◐ |
| 写法 / 去 AI 资产 | ◐ 场面约束提示词（#28）；Skill 导入未合入 | ● | ● | ● |
| 双语文档 | ● `README.md` + `README.en.md`（#23）。界面仍中文 | 未复测 | 未复测 | ◐ |
| 匿名 OpenAI 兼容端点 | ●（#22） | ◐ Ollama / BYOK | 未复测 | ◐ |
| 本机外观 | ●（#26）+ 品牌首页（#34） | 未复测 | 未复测 | 未复测 |
| 会话内导航保持 | ● KeepAlive（#27）；续写流跨标签保持（#38） | 未复测 | 未复测 | 未复测 |
| 导出 / 备份 | ● txt / md / EPUB 2（#29）；单本 ZIP 备份 / 恢复（#37）。EPUB 导入未合入 | 未复测 | 未复测 | 未复测 |

### 3.1 Round 2 Wave A–B 落到代码里的行为

| 项 | 现在能做什么 | 边界 | 证据 |
|----|----------------|------|------|
| 品牌首页 | 全幅品牌首屏：开书 / 续写分流 CTA，作品区与首屏分层 | 不是主题市场 | [#34](https://github.com/ider5/MythWeaver/pull/34) |
| 首次引导 / 健康 | `/settings/health`：接口、库、续写配置；空书架 / 未配密钥引导 | 探测 LLM 另需 `?probe=llm` | [#35](https://github.com/ider5/MythWeaver/pull/35) |
| 写作质量信号 | 未回收伏笔、文风漂移提示、批量篇幅 / 钩子暂停 | 警告可继续；严格暂停可配置 | [#36](https://github.com/ider5/MythWeaver/pull/36) |
| 项目 ZIP | 单本导出行数据；恢复为新书 | 不含任务 / 费用；无 WebDAV | [#37](https://github.com/ider5/MythWeaver/pull/37) |
| 草稿存活 | 分段落库；SSE `Last-Event-ID` 重连；离开续写页不断流；重启后可编辑草稿 | 未完成任务仍标 failed / interrupted by restart | [#38](https://github.com/ider5/MythWeaver/pull/38) |
| LLM 命名配置 | 多套配置切换，优先于裸 `.env` | 密钥仍本地保管 | [#32](https://github.com/ider5/MythWeaver/pull/32) |
| 导出 EPUB | 工作台 TXT / MD / EPUB 2 | 参考本 409；首页「导出」仍偏 TXT | [#29](https://github.com/ider5/MythWeaver/pull/29) |

更早 Round 2 行为（视觉、导入空状态、任务中心、回写、开书分流、Bible 编辑、外观、KeepAlive、去 AI 文案、版本对照）见历史 [#16](https://github.com/ider5/MythWeaver/pull/16)–[#30](https://github.com/ider5/MythWeaver/pull/30)。

## 4. MythWeaver 相对优势

- 超长原文压到约 16K 上下文：分层摘要 + RAG
- Critic 自动回路写在生成路径里（规则 + LLM，最多 2 轮），另有勾选修稿与批量质量暂停
- 半自动连续生成最多 10 章，Critic 未通过或失败时停在下一章之前
- 断线 / 重启后分段落库与可恢复草稿，续写流可跨标签保持
- 后端测试覆盖续写、从零开书、回写、备份和任务去重；Web 栈是 FastAPI + Vue

匿名端点和本机外观是可用性，不计入相对 Pagekin / Biz 的优势。Pagekin 已有 Ollama 与 BYOK。

## 5. 已关闭差距（#3–#38）

CI、Docker / 打包、模型预设、蓝图字段、LangGraph Critic、修稿勾选、首页与工作区视觉、参考导入、任务取消 / 重试与任务中心、Bible 可视化与编辑、批量导演、阶段路由 / 用量、导入向导与空状态、写作 / 大纲台、生成章回写确认、匿名兼容端点、中英 README、从零开书分流、本机外观、工作区 KeepAlive 与任务去重、提示词与界面句子收紧、原稿 EPUB 导出、章节版本按行对照、LLM 命名配置、品牌首页、首次引导与健康、写作质量信号、单本 ZIP 备份、任务断线重连与重启草稿。

## 6. 仍敞开

写这份清单时，下列能力仍缺或未合入：

- 可编辑的写法 / 去 AI 资产库与阶段 Skill 导入（进行中）
- 安装包或单二进制（打包再打磨中）
- 事实出处、WebDAV、段落级修稿接受、EPUB 导入（导入进行中）
- 产品内双语写作；界面多语言
- 世界地图、全自动导演、漫画 / 短剧：上限参考，不追
- 同书样本对比，用来判断是否超越

运行演示在项目 Context：`media/round2-walkthrough.mp4`、`media/round2-waveb-walkthrough.mp4`（非仓库内文件）。

## 7. 「达到或超越」判定

「达到」：P0–P1 已满足，见项目 Context `docs/parity-acceptance.md`。Round 2 主路径（开书 / 续写、任务可靠性、质量信号、备份、健康与品牌首页）已有合并 PR 与运行演示。

「超越」：仍缺同书样本（上下文 token / 一致性问题）或比 show-me-the-story 更短的可重复安装路径。本报告不把 Round 2 记成超越。
