# MythWeaver 同行对标报告

更新时间：2026-11-17（Asia/Shanghai）  
证据锚点：`origin/master` `663938f`（含已合并 PR #3–#28）  
基准产品：MythWeaver（`ider5/MythWeaver`）— 单机 FastAPI + Vue 3 网络小说续写  
材料：仓库 README / `docs/` / 当前代码与测试。同行格沿用 [#19](https://github.com/ider5/MythWeaver/pull/19) 与 2026-11-16 笔记，本轮没有重爬对方仓库。

## 1. 结论摘要

MythWeaver 的差异仍在长文入库压缩（分层摘要 + sqlite-vec）、Story Bible 与大纲门禁、SSE 续写、Critic 回路、最多 10 章的半自动连续生成，以及 Compose / Makefile 自托管。

[#19](https://github.com/ider5/MythWeaver/pull/19) 里标成进行中的 Round 2 产品项已经落在 master 上：从零开书与续写分流、生成章回写确认、中英 README、Story Bible 编辑、任务中心、匿名 OpenAI 兼容端点、本机外观、工作区保持与任务去重。#28 把界面句子和续写提示词改成可执行约束，没有变成可编辑的写法库。

仍敞开的差距：

1. **写法 / 去 AI** 仍是固定提示词（`anti_ai.j2` 等）加文风字段。用户不能增删规则资产。
2. **分发** 仍是 Docker Compose、Makefile、源码。没有安装包，也没有单二进制。
3. **生成章回写** 可以勾选后写入，但没有原文出处。原稿入库仍自动合并设定。
4. **界面只有中文。** README 双语不等于产品内双语写作。
5. **导出** 目前是 txt / md。EPUB 在未合并的 [#29](https://github.com/ider5/MythWeaver/pull/29)。
6. 没有版本历史、WebDAV、Skill 导入、项目 ZIP。世界地图、全自动导演、漫画 / 短剧不追。
7. 没有同书样本的上下文 token 或一致性对照，不能称超越。

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
| 流式续写 | ● SSE | ● | ● | ● |
| Critic / 审校 | ● LangGraph ≤2 轮（#7）+ 勾选修稿（#8） | ● | ● | ● |
| 拆书 / 仿写 | ● 原稿 / 参考（#10） | ● | ● | ◐ |
| 导入引导 / 空状态 | ●（#17） | ● | ● | ◐ |
| 写作 / 大纲台流程 | ● 大纲三步、续写四步（#18） | ● | ● | ◐ |
| 任务可视 / 取消 | ● 状态、进度、取消 / 重试（#11 #20）；同书同类型进行中再入队 409（#27） | ● | ● | ◐ |
| 自动导演 / 批量 | ● ≤10 章半自动（#13） | ◐ | ● | ◐ |
| 用量与阶段路由 | ●（#14） | ◐ | ● | ○ |
| 一键分发 | ● Compose + package / Makefile（#4 #15）。无安装包、无单二进制 | ● | ● | ● |
| CI | ●（#3） | ● | ● | ● |
| 从零开书 | ● 与续写分流（#24）。开篇复用大纲 + 连续生成 | ● | ● | ● |
| 章后状态回写 | ● 生成章差异勾选后写入或放弃（#21）。入库仍自动合并；无出处 | ◐ | ◐ | ◐ |
| 写法 / 去 AI 资产 | ◐ 提示词已收成场面约束（#28），仍不可编辑 | ● | ● | ● |
| 双语文档 | ● `README.md` + `README.en.md`（#23）。界面仍中文 | 未复测 | 未复测 | ◐ 笔记里的双语是写作语言 |
| 匿名 OpenAI 兼容端点 | ● 见 §3.1（#22） | ◐ Ollama / BYOK | 未复测 | ◐ OpenAI 兼容 |
| 本机外观 | ● 见 §3.1（#26） | 未复测 | 未复测 | 未复测 |
| 会话内导航保持 | ● 见 §3.1（#27）。刷新后草稿丢失 | 未复测 | 未复测 | 未复测 |
| 导出成书 | ◐ txt / md。EPUB 未合并（#29） | 未复测 | 未复测 | 未复测 |

### 3.1 Round 2 落到代码里的行为

对照 [#19](https://github.com/ider5/MythWeaver/pull/19) 当时写的「进行中」。

| 项 | 现在能做什么 | 边界 | 证据 |
|----|----------------|------|------|
| 视觉系统 | 首页与工作区色板、层级、少量入场动画 | 不是主题市场 | [#16](https://github.com/ider5/MythWeaver/pull/16) `frontend/src/assets/main.css` |
| 导入 / 空状态 | 首页按原稿 / 参考 / 全部筛选。空书架指向导入或开书。导入先选用途再选文件 | 参考本不能续写、不能导出 | [#17](https://github.com/ider5/MythWeaver/pull/17) |
| 写作 / 大纲台 | 大纲：规划 → 校对确认 → 连写。续写：选章 → 成稿 → 审阅 → 入库 | 未保存的大纲修改刷新后丢失 | [#18](https://github.com/ider5/MythWeaver/pull/18) README「工作台」 |
| 任务中心 | 进行中 / 可重试计数；排队、进行中、取消中、完成、失败、已取消；进度条与 SSE 百分比；取消与重试 | 可重试仍只有 `ingest`、`outline_generate`、`revise_commit`。连续生成可取消，不可重试 | [#20](https://github.com/ider5/MythWeaver/pull/20) `TaskHistory.vue` |
| 生成章回写 | 对照人物、世界观、伏笔列出新增与更新。勾选 `change_ids` 后 `apply`，或整单 `dismiss` | 无变化和仅出场更新会跳过。重复 apply 为 409。原稿入库仍自动合并。字段有前后值，没有章节引文 | [#21](https://github.com/ider5/MythWeaver/pull/21) `backend/tests/test_writeback.py` |
| 匿名兼容端点 | 密钥为 `anonymous` / `none` / `no-key` / `nokey` 时去掉 `Authorization`。OVH 预设在厂商列表里。这三档在「是否已配置」里算已配置 | 空字符串仍算未配置。连接测试拒绝空密钥，接受上述字面量。没有专用 pytest | [#22](https://github.com/ider5/MythWeaver/pull/22) `backend/app/llm/client.py`、`services/providers.py`、`routers/tasks.py` |
| 中英 README | `README.md` 含中英两节，并有 `README.en.md` | 界面文案仍是中文 | [#23](https://github.com/ider5/MythWeaver/pull/23) |
| 从零开书 | `POST /api/novels/scratch` 得到 `origin=scratch`、`status=blank`。`/scratch/seed` 用前提播种 Story Bible。之后走现有大纲确认和连续生成。导航是「开书」对「续写」；工作台标签是「开篇」 | 从零开书不能入库（409）。导入书不能播种（409）。前提至少 8 字。开篇不是另一套写作引擎 | [#24](https://github.com/ider5/MythWeaver/pull/24) `backend/tests/test_scratch_novel.py` |
| Bible 编辑 | 人物、世界观、伏笔可新建、保存、删除。关系可逐条或原文。未保存时切换有拦截 | 本 PR 只改前端。关系图和时间线仍由前端用 Bible 数据绘制 | [#25](https://github.com/ider5/MythWeaver/pull/25) `StoryBible.vue` |
| 外观与动效 | `/settings/appearance`：薄雾 / 墨色、四种强调色、标准 / 紧凑。写入本机 `localStorage`（`mythweaver.ui`） | 不同步到服务器。动效跟随系统 `prefers-reduced-motion`，设置页没有动效开关 | [#26](https://github.com/ider5/MythWeaver/pull/26) `useUiPrefs.ts` |
| 导航保持与任务去重 | 顶栏 KeepAlive（最多 12，键为路径前三段，同一本书共用工作区壳）。分区内再 KeepAlive（最多 8）。Pinia 记住大纲选中、筛选、任务筛选和导入草稿。同书同类型已有 pending/running 时再入队返回 409 | 刷新后 Pinia 草稿丢失。外观偏好除外，那个在 localStorage | [#27](https://github.com/ider5/MythWeaver/pull/27) `test_duplicate_ingest_rejected` |
| 文案与提示词 | 界面短句说明这一屏做什么。`anti_ai.j2` 改成先写场面、少讲解、少套句。禁写词表还在 | 规则仍写死在模板里，不是资产库 | [#28](https://github.com/ider5/MythWeaver/pull/28) `anti_ai.j2` |

## 4. MythWeaver 相对优势

- 超长原文压到约 16K 上下文：分层摘要 + RAG
- Critic 自动回路写在生成路径里（规则 + LLM，最多 2 轮），另有勾选修稿
- 半自动连续生成最多 10 章，Critic 未通过或失败时停在下一章之前
- 后端测试覆盖续写、从零开书、回写和任务去重；Web 栈是 FastAPI + Vue

匿名端点和本机外观是可用性，不计入相对 Pagekin / Biz 的优势。Pagekin 已有 Ollama 与 BYOK。

## 5. 已关闭差距（#3–#28）

CI、Docker / 打包、模型预设、蓝图字段、LangGraph Critic、修稿勾选、首页与工作区视觉、参考导入、任务取消 / 重试与任务中心、Bible 可视化与编辑、批量导演、阶段路由 / 用量、导入向导与空状态、写作 / 大纲台、生成章回写确认、匿名兼容端点、中英 README、从零开书分流、本机外观、工作区 KeepAlive 与任务去重、提示词与界面句子收紧。

## 6. 仍敞开

- 可编辑的写法 / 去 AI 资产库（#28 没有做这个）
- 安装包或单二进制
- 事实出处、项目 ZIP、版本历史、WebDAV、Skill 导入
- 产品内双语写作；界面多语言
- 导出 EPUB：[#29](https://github.com/ider5/MythWeaver/pull/29) 未合并。master 上仍是 txt / md
- Round 2 运行录屏。仓库里没有。Round 1 只在项目 Context `media/mythweaver-running-demo.mp4`
- 世界地图、全自动导演、漫画 / 短剧：上限参考，不追
- 同书样本对比，用来判断是否超越

## 7. 「达到或超越」判定

「达到」：P0–P1 已满足，见 `parity-acceptance.md`。Round 2 里原先挡住产品闭环的从零开书、生成章确认、任务中心和 Bible 编辑已经有代码和测试（Bible 编辑与任务中心主要是界面，没有新的组件测试）。

「超越」：仍缺同书样本（上下文 token / 一致性问题）或比 show-me-the-story 更短的可重复安装路径。本报告不把 Round 2 记成超越。
