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
| Agent | **LangGraph** 编排 Critic 回路（`AGENT_RUNTIME=langgraph`，可回退 `legacy`） |
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

### 4. 打包与一键部署（推荐自托管）

先准备 `backend/.env`（从 `backend/.env.example` 复制，勿把密钥写进镜像）。

**一条命令拉起 API + UI（Docker）：**

```bash
./scripts/package.sh docker   # 等价于构建镜像
docker compose up --build -d
```

浏览器打开 **http://localhost:8080**。nginx 将 `/api` 反代到后端；数据在卷 `mythweaver-data`。后端健康检查：`/api/health`。

仅打包前端静态资源（自行挂 nginx）：

```bash
./scripts/package.sh dist   # 输出到 dist/release/web
```

对标 show-me-the-story 一类本地工具：尽量一条命令可写。

## 基本使用流程

1. **导入**：先选「原稿」或「参考」，再上传文本（或目录），预览分章后确认入库
2. **入库**：触发摘要 / 实体 / 向量化任务，等待 SSE 进度完成
3. **Story Bible**：检查并修正人物、世界观、伏笔
4. **大纲**：生成大纲 → 编辑 → 确认
5. **续写**：按大纲条目流式生成，或在已确认大纲上连续生成最多 10 章（Critic 未通过则停下）→ 查看一致性报告 → 人工修订 → 确认入库（增量更新知识库）

## 原稿与参考

导入确认时写入 `role`。已有书和未传该字段的请求默认为 `manuscript`。旧库启动时自动补上 `novels.role`。

| `role` | 用途 |
|---|---|
| `manuscript` | 原稿。可入库、大纲、续写，并可导出为 txt/md 成书。列表默认只显示这一类。 |
| `reference` | 仿写参考。仍会入库，抽出 Story Bible 与文风样本；**不**进入默认续写列表，**不能**作为章节生成来源，**不能**导出为书。参考章节不会写进原稿正文。 |

接口约定：

- `POST /api/novels`、`PATCH /api/novels/{id}`、`POST /api/novels/import/confirm` 接受 `role`：`manuscript` 或 `reference`
- `GET /api/novels?role=manuscript` 是续写的默认来源；`role=reference` 只返回参考本。不传 `role` 时返回全部
- `GET /api/novels/{id}/export` 对参考本返回 **409**
- `POST /api/novels/{id}/generate` 与 `POST /api/novels/{id}/generate/batch` 对参考本返回 **409**。`GET /api/novels/{id}/generate/stream` 返回 SSE `error`，不改小说状态、不写章节
- `POST /api/novels/{id}/ingest` 对参考本仍然可用

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

### 厂商预设与连接测试

前端「LLM 设置」页（`/settings/providers`）提供常见 OpenAI 兼容厂商预设（OpenAI、DeepSeek、Moonshot、通义、智谱、OpenRouter、Ollama、自定义）。选择预设会填入默认 Base URL 与模型；「测试连接」调用 `POST /api/providers/test`，密钥**仅用于本次探测、不落库**。测通后请把相同值写入 `backend/.env` 的 `SUMMARY_*` / `GENERATION_*` / `EMBEDDING_*`。

## 测试

```bash
cd backend
pytest
```

测试路径由 `backend/pytest.ini` 指定为 `tests/`。需要真实 API 的用例请自行配置 `.env`；默认以 mock / 本地逻辑为主。

持续集成见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。推送到 `main` 或 `master`，以及针对这两个分支的 pull request，会并行执行：

- 后端：Python 3.11，安装 `requirements.txt` 后运行 `pytest`（沿用测试内的 mock，不注入 API 密钥）
- 前端：Node.js 20，`npm ci` 后执行 `npm run build`（含 `vue-tsc`）

`sqlite-vec` 使用 PyPI wheel。GitHub 托管 runner 上由 `actions/setup-python` 提供的 CPython 可加载 SQLite 扩展，无需额外 apt 包。

## 文档

- [架构说明](docs/ARCHITECTURE.md) — 模块划分、数据模型、生成回路
- [API 规格](docs/API_SPEC.md) — REST / SSE 接口一览
