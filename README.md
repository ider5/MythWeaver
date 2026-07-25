# MythWeaver

单机部署的网络小说自动续写 Agent。通过分层摘要、向量检索与 Story Bible，将长篇原文压缩为约 16K token 的生成上下文，支持流式续写与一致性 Critic 回路。

## 核心能力

- **入库压缩**：自动分章 → 章/卷摘要 → 实体抽取 → sqlite-vec 向量化（断点续传 + SSE 进度）
- **Story Bible**：人物（含别称）、世界观、伏笔线的结构化知识库，可编辑修正
- **大纲先行**：生成/编辑/确认大纲后再逐章续写
- **流式续写**：SSE 实时输出；组装最近正文、摘要、RAG、Bible、文风样本与递归记忆
- **一致性 Critic**：规则 + LLM 校验，最多 2 轮自动修正，输出问题报告

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+、FastAPI、Uvicorn、Pydantic v2 |
| 数据 | SQLite（WAL）+ SQLAlchemy 2.0 async + sqlite-vec |
| LLM | OpenAI / Anthropic 官方 SDK（自定义 `base_url`），进程内 asyncio 任务队列 |
| 前端 | Vue 3、TypeScript、Vite、Pinia、TailwindCSS |
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
copy .env.example .env   # Windows；macOS/Linux 用 cp .env.example .env
```

编辑 `backend/.env`，填入摘要 / 生成 / Embedding 的 `API_KEY`、`BASE_URL` 与模型名。示例字段见 `.env.example`（勿提交真实密钥）。

### 2. 安装并启动后端

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：`GET http://localhost:8000/api/health`

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
2. **入库**：触发摘要 / 实体 / 向量化任务，等待 SSE 进度完成
3. **Story Bible**：检查并修正人物、世界观、伏笔
4. **大纲**：生成大纲 → 编辑 → 确认
5. **续写**：按大纲条目流式生成 → 查看一致性报告 → 人工修订 → 确认入库（增量更新知识库）

## 配置说明

配置均在 `backend/.env`（模板：`backend/.env.example`）。

### 双协议 Provider

- `SUMMARY_PROVIDER` / `GENERATION_PROVIDER`：`openai` 或 `anthropic`
- 各自独立的 `*_BASE_URL`、`*_API_KEY`、`*_MODEL`
- Embedding 走 OpenAI 兼容端点：`EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`

### 模型分级

| 用途 | 前缀 | 说明 |
|---|---|---|
| 摘要 / 抽取 / 校验 | `SUMMARY_*` | 廉价模型，入库摘要/抽取 |
| 续写 / Critic | `GENERATION_*` | 高质量生成 |
| 向量检索 | `EMBEDDING_*` | OpenAI 兼容 embedding |

其它常用项：`CONTEXT_TOKEN_BUDGET`（默认 16000）、`INGEST_CONCURRENCY` / `LLM_MAX_CONCURRENCY`（默认均为 2，适配组织并发上限 3）、`EMBEDDING_MAX_CONCURRENCY`、`LLM_RPM` / `LLM_TPM`、成本单价 `COST_*`。

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
