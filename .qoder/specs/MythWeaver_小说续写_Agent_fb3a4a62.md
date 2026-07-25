# MythWeaver — 网络小说自动续写 Agent 实施计划

## Summary

在空白工作区构建单机部署的小说续写系统。核心思路：
- **百万字上下文压缩**：分层摘要（章级 300 字 / 卷级 1000 字）+ sqlite-vec 向量检索（RAG）+ Story Bible 结构化知识库，动态压缩为约 16K token 的生成上下文（压缩比约 60:1）。
- **一致性保障**：Story Bible 每次生成强制注入 + 递归记忆状态（RecurrentGPT 思路）+ 文风样本 few-shot + 生成后一致性校验与 Critic 自检回路。
- **世界观/人物/剧情单独建模**：Story Bible 独立存储人物卡（含别称表）、世界观设定、伏笔线、时间线，入库时由 LLM 自动抽取，用户可编辑修正。
- **双协议 API 驱动**：直接用 openai / anthropic 官方 SDK 的 base_url 参数做统一适配层（不引入 LiteLLM/LangChain），摘要用廉价模型、生成用高质量模型分级配置。
- **工作流**：导入小说 → 自动分章 → 入库管线（摘要/实体抽取/向量化）→ 生成大纲（用户确认/编辑）→ 逐章流式生成 → 一致性报告 + Critic 修正 → 人工修订 → 入库并增量更新知识库。

## 技术栈（最终决定）

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+，FastAPI 0.110+，Uvicorn，Pydantic v2 |
| 数据库 | SQLite（WAL 模式）+ SQLAlchemy 2.0（async），单文件 `data/mythweaver.db` |
| 向量检索 | sqlite-vec 扩展；embedding 走 OpenAI 兼容 API（`text-embedding-3-small` 或用户配置的兼容端点），不引入本地 torch 依赖 |
| LLM | openai>=1.x 与 anthropic>=0.25 官方 SDK，双协议均支持自定义 base_url |
| 中文处理 | 内置正则分章 + jieba（人名/关键词）+ opencc-python-reimplemented（繁简统一） |
| Token 计数 | tiktoken（近似估算，中文按 1.5 token/字兜底） |
| 异步任务 | 进程内 asyncio 队列 + SQLite 持久化任务表（AsyncTask），SSE 推送进度、轮询兜底；不用 Celery/Redis |
| 前端 | Vue 3 + TypeScript + Vite + Pinia + TailwindCSS + axios，原生 EventSource 处理 SSE |
| 测试 | pytest + pytest-asyncio + httpx |

## 目录结构

```
MythWeaver/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口 + CORS + 静态托管
│   │   ├── config.py                # pydantic-settings：双协议端点/模型分级/token预算
│   │   ├── db.py                    # SQLite(WAL) + sqlite-vec 初始化
│   │   ├── models/                  # SQLAlchemy: Novel/Chapter/ChapterVersion/Summary/
│   │   │                            #   Character/PlotThread/WorldSetting/Outline/AsyncTask/CostLog
│   │   ├── schemas/                 # Pydantic 请求/响应模型
│   │   ├── llm/
│   │   │   ├── client.py            # 双协议统一客户端（chat/stream/embed，统一流式增量格式）
│   │   │   ├── rate_limiter.py      # RPM/TPM 限流 + 指数退避重试
│   │   │   ├── cost_tracker.py      # 每次调用记录 token 与成本
│   │   │   └── prompts/             # Jinja2 模板：摘要/实体抽取/大纲/续写/critic/风格卡（分题材）
│   │   ├── services/
│   │   │   ├── ingestion.py         # 入库管线：分章→并发摘要→实体抽取→向量化，断点续传+进度
│   │   │   ├── context_builder.py   # 上下文组装（token 预算分配，核心质量模块）
│   │   │   ├── outline.py           # 大纲生成/编辑/确认
│   │   │   ├── generation.py        # 单章流式生成 + 递归记忆状态更新
│   │   │   ├── consistency.py       # 一致性校验 + Critic 自检回路
│   │   │   ├── story_bible.py       # Story Bible CRUD + 自动抽取合并
│   │   │   ├── retrieval.py         # 向量检索 + 关键词混合检索
│   │   │   └── tasks.py             # asyncio 任务队列 + AsyncTask 状态机
│   │   ├── routers/                 # novels/chapters/story_bible/outline/generation/tasks/config
│   │   └── utils/chinese_text.py    # 分章正则集、字数统计、繁简统一、文本清洗
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/                        # Vue3+TS+Vite：小说列表/导入向导/Story Bible 编辑器/
│                                    #   大纲工作台/续写工作台(SSE)/章节修订与版本对比
├── data/                            # mythweaver.db + 导入原文备份
└── docs/                            # ARCHITECTURE.md / API_SPEC.md
```

## 关键设计决策

### 1. 上下文压缩与 token 预算（context_builder.py）
生成单章时组装约 16K token 上下文，预算分配：
- 最近 2 章全文（连贯性锚点）：约 8K
- 前 5 章章级摘要 + 相关卷级摘要：约 2K
- RAG 检索 top-8 相关历史情节摘要（按大纲要点作查询）：约 1.5K
- Story Bible（当前活跃人物卡 + 相关世界观设定 + 未回收伏笔）：约 2.5K
- 文风样本（从原文自动选取 2-3 段代表性段落，few-shot）：约 1.5K
- 递归记忆状态（上一章结尾状态、人物位置/情绪、时间线游标）：约 0.5K
超预算时按 优先级从低到高裁剪：卷摘要 → RAG 条数 → 章摘要数量，最近 2 章全文与 Story Bible 不裁剪。

### 2. Story Bible 数据模型
- `Character`：name、aliases（别称/绰号/道号数组，解决中文称谓一致性）、role、当前状态（存活/修为/位置）、性格与语言特征、关系图 JSON、最后出场章
- `WorldSetting`：分类（力量体系/地理/组织/规则）、内容、禁止事项（DO NOT VIOLATE 条款）
- `PlotThread`：伏笔/主线支线、状态（未回收/已回收）、引入章节
- 入库时用廉价模型逐章抽取并合并去重；生成新章入库后增量更新；全部可在前端编辑

### 3. 生成与质量回路（generation.py + consistency.py）
1. 按大纲要点 + 组装上下文流式生成章节（SSE 推送给前端）
2. 生成后自动校验：人名/别称匹配 Story Bible、禁止事项违反检测、修为/状态突变检测、与最近章节的衔接检查（用廉价模型做结构化校验）
3. 校验发现问题 → Critic 回路（最多 2 轮）：将问题清单回喂 LLM 修正
4. 输出一致性报告给用户 → 人工修订 → 确认入库 → 触发该章摘要/实体/向量增量更新 + 递归记忆状态更新
5. 每章保留版本链：generated → critic_revised → user_edited，支持 diff 与回滚

### 4. 双协议适配层（llm/client.py）
- `provider: openai | anthropic`，各自官方 SDK + base_url 注入；embedding 单独配置 OpenAI 兼容端点
- 统一 `chat()/stream()/embed()` 接口，流式增量统一为 `{delta_text}` 格式
- 模型分级：`SUMMARY_MODEL`（廉价）/ `GENERATION_MODEL`（高质量）/ `EMBEDDING_MODEL`，均可独立配置 provider+base_url+key
- 限流（RPM/TPM 双维度）+ 指数退避重试（3 次，带 jitter）+ CostLog 成本落库

### 5. 入库管线（ingestion.py）
- 分章：多正则模式（第X章/第X卷/Chapter N/序章）自动择优，失败则按字数兜底分割；支持目录结构导入（卷目录/章文件）
- 编码检测（chardet）+ 繁简统一 + BOM/空白清洗
- 并发批处理（信号量控制并发 8-10），逐章完成即持久化状态（status: raw→summarized→extracted→embedded），支持中断后断点续传
- 300 万字入库预估成本约 $5-10（廉价模型），前端展示预估与实时进度

## 里程碑与依赖

### M1 — 基础框架与入库（先行，无依赖）
1. 项目骨架：backend 目录结构、config、SQLite+sqlite-vec 初始化、全部数据模型建表
2. LLM 双协议客户端 + 限流重试 + 成本追踪（含双端点集成测试）
3. 中文文本处理 + 分章解析器 + 两种导入模式
4. 入库管线（摘要/实体抽取/向量化）+ asyncio 任务队列 + SSE 进度
5. 前端骨架：小说列表、导入向导（含分章预览确认）、入库进度页

### M2 — 续写核心（依赖 M1）
6. context_builder（token 预算组装）+ retrieval（混合检索）
7. Story Bible 服务 + 前端编辑器（人物卡/世界观/伏笔线）
8. 大纲生成 → 前端大纲工作台（确认/编辑/重生成）
9. 单章流式生成 + 递归记忆状态 + 前端续写工作台（SSE 实时显示）
10. 章节版本管理 + 人工修订入库 + 增量知识库更新

### M3 — 质量回路与打磨（依赖 M2）
11. 一致性校验 + Critic 自检回路 + 前端一致性报告展示
12. 分题材 Prompt 模板库（玄幻/都市/言情）+ 文风样本自动提取
13. 成本看板、任务历史、端到端测试与文档

依赖链：1→2→4，1→3→4，4→6→8→9→10→11；前端各页面依赖对应后端路由完成；7 可与 6 并行；12/13 依赖 11。

## Test Plan
- 单元测试：分章正则（覆盖 20+ 格式变体）、token 预算裁剪逻辑、别称匹配、双协议客户端（mock）
- 集成测试：用一部短篇样例小说走通 导入→入库→大纲→生成→修订→入库 全流程
- 双端点真实验证：分别配置 OpenAI 兼容端点与 Anthropic 兼容端点各跑一次生成
- 前端 E2E：浏览器验证导入向导、Story Bible 编辑、大纲确认、SSE 流式生成、版本对比

## Risks & Mitigations
- **续写质量不达标（最大风险）**：Prompt 模板集中管理便于迭代；文风 few-shot + Story Bible 强注入 + Critic 回路；每章人工修订兜底
- **上下文窗口溢出**：严格 tiktoken 计数 + 优先级裁剪策略
- **入库中断/API 限流**：逐章持久化状态支持断点续传；指数退避；并发信号量
- **数据丢失**：WAL 模式 + 章节版本链 + 导入原文备份留存
- **端点兼容性差异**：适配层集成测试覆盖双协议；embedding 端点独立可配

## Rejected Alternatives
- **PostgreSQL + Qdrant + Redis + Celery**（Sam 案）：单机单用户场景过重，SQLite+sqlite-vec+asyncio 队列足够，保留后期迁移接口
- **LiteLLM / LangChain**：两家官方 SDK 均原生支持 base_url，中间层徒增依赖与调试成本
- **本地 bge-m3 embedding**：引入 torch 重依赖，违背"API 驱动"原则，改为 OpenAI 兼容 embedding 端点（可配置）
- **原生 HTML 前端**（Tina 案 M1）：与用户已确认的 Web 界面诉求不符，直接采用 Vue 3
- **全自动多章连续生成**：一致性风险过高，本期采用大纲先行 + 逐章人工确认，架构预留批量队列扩展点