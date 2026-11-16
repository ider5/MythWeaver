# MythWeaver 同行对标报告

更新时间：2026-11-17（Asia/Shanghai）  
基准产品：MythWeaver（`ider5/MythWeaver`）— 单机 FastAPI + Vue3 网络小说续写 Agent  
证据：仓库 README / `docs/` / 代码；已合并 PR #3–#18

## 1. 结论摘要

MythWeaver 在**长文入库压缩（分层摘要 + sqlite-vec RAG）**、**Story Bible + 大纲门禁 + SSE 续写 + Critic**、**半自动批量导演**、以及**自托管打包**上已形成清晰差异化。相对明星同行，剩余主要差距在：

1. **从零开书**与续写入口的完整分流（进行中）
2. **章后状态回写确认**（Goink / StoryForge 风格，进行中）
3. **写法/去 AI 资产库**仍偏规则与文风样本，未做成可编辑引擎
4. **桌面分发**仍以 Docker / 源码为主，无安装包

目标路径：对齐 Pagekin / show-me-the-story 的本地闭环与部署；有选择地追赶 Biz Novel Studio 的编排层，不全量复制多媒体延展。

## 2. 主要同行

| 项目 | 形态 | 为何选为基准 |
|------|------|--------------|
| [EthanYoQ/Pagekin](https://github.com/EthanYoQ/Pagekin) | Electron 本地写作 | UX/闭环主基准 |
| [ExplosiveCoderflome/AI-Novel-Writing-Assistant](https://github.com/ExplosiveCoderflome/AI-Novel-Writing-Assistant) | Electron + LangGraph | 能力上限参考 |
| [Nigh/show-me-the-story](https://github.com/Nigh/show-me-the-story) | 单二进制 + Web UI | 轻量自托管基准 |
| [sigpanic/goink](https://github.com/sigpanic/goink) | Wails + sqlite-vec | 写后记忆维护对照 |
| [yuanbw2025/storyforge](https://github.com/yuanbw2025/storyforge) | 浏览器长篇工作台 | 章后确认对照 |

## 3. 能力矩阵

图例：● 强 / ◐ 有 / ○ 弱或无

| 能力 | MythWeaver | Pagekin | Biz Novel Studio | show-me-the-story |
|------|:---:|:---:|:---:|:---:|
| 本地/自托管 | ● | ● | ● | ● |
| 长文导入入库 | ● | ● | ● | ● |
| 分层摘要压缩超长文 | ● | ◐ | ◐ | ◐ |
| 向量 RAG | ● sqlite-vec | ◐ | ● Qdrant | ◐ |
| Story Bible | ● + 关系图/时间线（#12） | ● | ● | ● |
| 大纲 / 蓝图 | ● 蓝图字段（#6） | ● | ● | ● |
| 流式续写 | ● SSE | ● | ● | ● |
| Critic / 审校 | ● LangGraph≤2轮（#7）+ 勾选修稿（#8） | ● | ● | ● |
| 拆书 / 仿写 | ● 原稿/参考（#10） | ● | ● | ◐ |
| 导入引导 / 空状态 | ●（#17） | ● | ● | ◐ |
| 写作/大纲台流程 | ● 步骤化精简（#18） | ● | ● | ◐ |
| 任务可视/取消 | ●（#11） | ● | ● | ◐ |
| 自动导演/批量 | ● ≤10章半自动（#13） | ◐ | ● | ◐ |
| 用量与阶段路由 | ●（#14） | ◐ | ● | ○ |
| 一键分发 | ● Compose + package/Makefile（#4/#15） | ● | ● | ● |
| CI | ●（#3） | ● | ● | ● |
| 从零开书 | ◐ 空书表单入口（#17）；完整模式进行中 | ● | ● | ● |
| 章后状态回写 | ○ 进行中 | ◐ | ◐ | ◐ |
| 写法/去 AI 资产 | ◐ 文风+规则 | ● | ● | ● |

## 4. MythWeaver 相对优势

- 超长原文 → 约 16K 上下文的分层摘要 + RAG
- Critic 自动回路写入生成路径（规则 + LLM，最多 2 轮）
- 后端测试面较宽；Web 栈轻（FastAPI + Vue），易二次开发

## 5. 已关闭差距（#3–#18）

CI、Docker/打包、模型预设、蓝图字段、LangGraph Critic、修稿勾选、首页视觉、参考导入、任务中心、Bible 可视化、批量导演、阶段路由/用量、导入向导与空状态、写作/大纲台流程精简。

## 6. 仍在推进

- 从零开书与续写 UI 分流
- 章后 Bible/设定回写提案与确认
- 中英双语 README
- Story Bible 编辑体验、任务中心动效
- Round 2 运行录屏与验收证据回写

## 7. 「达到或超越」判定

「达到」：P0–P1 已满足（见 `parity-acceptance.md`）。  
「超越」：需同书样本对比（上下文 token / 一致性问题）或更短可重复部署路径的证据。
