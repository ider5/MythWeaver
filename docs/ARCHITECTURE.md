# MythWeaver 架构说明

## 概览

MythWeaver 是单机部署的网络小说自动续写系统。通过分层摘要、sqlite-vec 向量检索与 Story Bible，将长篇原文压缩为约 16K token 的生成上下文，并在生成后走一致性校验与 Critic 回路。

## 分层结构

```
frontend (Vue3)  --HTTP/SSE-->  backend (FastAPI)
                                   ├── routers
                                   ├── services（入库/上下文/大纲/生成/校验）
                                   ├── llm（双协议客户端）
                                   └── SQLite + sqlite-vec
```

## 核心模块

| 模块 | 职责 |
|------|------|
| `ingestion` | 分章、摘要、实体抽取、向量化；asyncio 任务 + SSE 进度 |
| `context_builder` | 按 token 预算组装上下文；裁剪优先级：卷摘要→RAG→章摘要 |
| `retrieval` | embedding + 关键词混合检索 |
| `story_bible` | 人物（含别称）/世界观/伏笔 CRUD 与抽取合并 |
| `outline` | 大纲生成、编辑、确认 |
| `generation` | 单章流式生成、版本链、修订入库、递归记忆 |
| `consistency` | 规则+LLM 校验，Critic 最多 2 轮 |

## 数据模型

Novel → Chapter → ChapterVersion（generated / critic_revised / user_edited）  
Novel → Summary（chapter / volume）  
Novel → Character / WorldSetting / PlotThread  
Novel → Outline → OutlineItem  
AsyncTask / CostLog / RecurrentMemory / StyleSample

## 生成回路

1. 大纲要点 + 上下文 → 流式生成（SSE）
2. 一致性校验 → Critic（≤2）→ 报告
3. 人工修订 → 确认入库 → 增量摘要/实体/向量 + 递归记忆更新

## LLM 适配

- `provider: openai | anthropic`，官方 SDK + `base_url`
- 分级：`SUMMARY_*` / `GENERATION_*` / `EMBEDDING_*`
- 限流 RPM/TPM + 指数退避；`CostLog` 落库

## 任务系统

进程内 `asyncio` 队列 + `AsyncTask` 表；SSE 推送进度，超时轮询兜底。不使用 Celery/Redis。
