# MythWeaver

单机部署的网络小说自动续写 Agent。通过分层摘要、向量检索与 Story Bible，将长篇原文压缩为约 16K token 的生成上下文，支持流式续写与一致性 Critic 回路。

## 核心能力

- **入库压缩**：自动分章 → 章/卷摘要 → 实体抽取 → sqlite-vec 向量化（断点续传 + SSE 进度）
- **Story Bible**：人物（含别称）、世界观、伏笔线的结构化知识库，可编辑修正
- **大纲先行**：生成 / 编辑 / 确认大纲后再逐章续写（保存大纲时按条目 id 更新，已生成章节的关联会保留）
- **流式续写**：SSE 实时输出；按目标章号组装上一章正文、摘要、RAG、Bible、文风样本与递归记忆（无需先点「修订入库」才能写下章）
- **一致性 Critic**：规则 + LLM 校验，短章最多 2 轮自动修正；超过篇幅阈值的长章只审查、不整章重写
- **修订入库**：人工修订后增量更新摘要 / 实体 / 向量与递归记忆

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+、FastAPI、Uvicorn、Pydantic v2 |
| 数据 | SQLite（WAL）+ SQLAlchemy 2.0 async + sqlite-vec |
| LLM | OpenAI / Anthropic 官方 SDK（自定义 `base_url`），进程内 asyncio 任务队列 |
| 前端 | Vue 3、TypeScript、Vite、Vue Router、TailwindCSS |
| 测试 | pytest、pytest-asyncio、httpx |

## 目录结构

```
MythWeaver/
├── backend/          # FastAPI 应用、LLM 适配、服务与测试
├── frontend/         # Vue3 界面（导入 / Bible / 大纲 / 续写）
├── data/             # SQLite 库与导入备份（运行时生成）
└── docs/             # 架构与 API 文档
```

## 环境要求

- Python **3.11+**
- Node.js（建议 18+，用于前端）
- 可用的 LLM API（OpenAI 兼容和/或 Anthropic）

## 快速开始

### 1. 配置环境变量

```bash
cd backend
cp .env.example .env          # Windows 可用 copy .env.example .env
```

编辑 `backend/.env`，填入摘要 / 生成 / Embedding 的 `API_KEY`、`BASE_URL` 与模型名。示例字段见 `.env.example`（勿提交真实密钥）。Kimi、智谱等 OpenAI 兼容端点的写法也在该文件中。

### 2. 安装并启动后端

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：`GET http://localhost:8000/api/health`

默认只允许浏览器从 `http://localhost:5173` 与 `http://127.0.0.1:5173` 跨域访问 API。开发时走 Vite 的 `/api` 代理即可，不必改 CORS。若前端源不是上述地址（例如局域网 IP），在 `.env` 里把该 Origin 加进 `CORS_ORIGINS`（逗号分隔）。不要使用 `*` 且开启 credentials。

进程重启后，未完成的入库 / 大纲 / 修订任务会标为失败，可在界面重试。

### 3. 安装并启动前端

另开终端：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（默认 `http://localhost:5173`）。开发模式下 `/api` 会代理到 `http://localhost:8000`。

## 基本使用流程

1. **导入**：上传小说文本（或目录），预览分章后确认入库
2. **入库**：触发摘要 / 实体 / 向量化任务，等待 SSE 进度完成（完成后每章应已写入向量，供 RAG 使用）
3. **Story Bible**：检查并修正人物、世界观、伏笔
4. **大纲**：生成大纲 → 编辑 → 确认
5. **续写**：按大纲条目流式生成 → 查看一致性报告 → 人工修订 → 确认入库（增量更新知识库）

长章（目标字数超过 `CHAPTER_SEGMENT_THRESHOLD`，默认 4500）会按大纲要点分段流式拼接；一致性检验仍会跑，但不会整章 Critic 重写。

## 配置说明

配置均在 `backend/.env`（模板：`backend/.env.example`）。

### 双协议 Provider

- `SUMMARY_PROVIDER` / `GENERATION_PROVIDER`：`openai` 或 `anthropic`
- 各自独立的 `*_BASE_URL`、`*_API_KEY`、`*_MODEL`
- Embedding 走 OpenAI 兼容端点：`EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` / `EMBEDDING_DIMS`

### 模型分级

| 用途 | 前缀 | 说明 |
|---|---|---|
| 摘要 / 抽取 / 校验 | `SUMMARY_*` | 廉价模型，入库摘要/抽取 |
| 续写 / Critic | `GENERATION_*` | 高质量生成 |
| 向量检索 | `EMBEDDING_*` | OpenAI 兼容 embedding |

其它常用项：

| 变量 | 说明 |
|---|---|
| `CONTEXT_TOKEN_BUDGET` | 生成上下文预算，默认 16000 |
| `INGEST_CONCURRENCY` / `LLM_MAX_CONCURRENCY` | 默认均为 2，适配组织并发上限 3 |
| `EMBEDDING_MAX_CONCURRENCY` / `EMBEDDING_BATCH_SIZE` | 向量化与 chat 解耦 |
| `CHAPTER_SEGMENT_THRESHOLD` | 超过则分段生成，默认 4500 字 |
| `GENERATION_MAX_TOKENS` | 单次生成 `max_tokens` 上限 |
| `SSE_HEARTBEAT_INTERVAL` | 续写 SSE 心跳（秒，默认 12）；前端空闲超时约 45s |
| `CORS_ORIGINS` | 允许的浏览器 Origin，逗号分隔 |
| `LLM_RPM` / `LLM_TPM` / `LLM_MAX_RETRIES` | 限流与重试 |
| `COST_*` | 成本单价（USD / 1M tokens）；`GET /api/costs` 对全部记录汇总 |

密钥是否已配置可通过 `GET /api/config` 查看（不返回明文 key）。

## 测试

```bash
cd backend
pytest
```

测试路径由 `backend/pytest.ini` 指定为 `tests/`。需要真实 API 的用例请自行配置 `.env`；默认以 mock / 本地逻辑为主。

## 文档

- [架构说明](docs/ARCHITECTURE.md) — 模块划分、数据模型、生成回路
- [API 规格](docs/API_SPEC.md) — REST / SSE 接口一览
