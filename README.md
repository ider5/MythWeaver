# MythWeaver

[**中文**](#中文) · [English](#english) · [README.en.md](README.en.md)

[![CI](https://github.com/ider5/MythWeaver/actions/workflows/ci.yml/badge.svg)](https://github.com/ider5/MythWeaver/actions/workflows/ci.yml)

单机部署的网络小说续写工作台。分层摘要、向量检索与 Story Bible 把长篇压成约 16K token 的生成上下文，再流式续写，并用一致性 Critic 回路收束。

## 中文

### 核心能力

- **入库压缩**：自动分章 → 章/卷摘要 → 实体抽取 → sqlite-vec 向量化。已经向量化的章会跳过；未完成的章按状态继续摘要与抽取。进度走 SSE。
- **写后回写**：生成章节后对照 Story Bible 列出人物、设定、伏笔的新增与更新，勾选确认后才写入；原稿入库仍自动合并。
- **从零开书**：前提、题材、文风 → Story Bible 种子 → 大纲 → 开篇，不要求导入原稿；与「导入续写」入口分开。
- **Story Bible**：人物（含别称）、世界观、伏笔线，可编辑。人物关系画成关系图：对方姓名对上人物卡或别称时连到同一人。伏笔、主线、支线按出现章节与回收章节排成时间线。图和时间线由前端根据 Bible 数据绘制。
- **大纲先行**：生成、编辑、确认后再写。条目含蓝图：主角小目标、冲突与转折、章末悬念、出场人物、要点。确认后这些字段进入检索与生成提示。
- **流式续写**：SSE 输出。上下文组装最近正文、摘要、RAG、Bible、文风样本与递归记忆。
- **导演 · 连续生成**：已确认大纲上，从某一序号起连续写最多 10 章。Critic 未通过、生成失败或取消时，正在写的一章会写完，下一章不再开始。
- **一致性 Critic**：规则 + LLM，最多 2 轮自动修正，并给出问题报告。默认 **LangGraph**（`AGENT_RUNTIME=langgraph`），可回退 `legacy`。审阅页可勾选问题、预览修稿，确认后才写入。
- **任务**：取消排队中或执行中的任务。失败或已取消、且可恢复的入库、大纲生成、修订入库可以重试。
- **用量**：按阶段显示模型路由，并按用途汇总 token 与估算成本。

两条入口：

| 路径 | 做法 |
|---|---|
| **续写** | 导入原稿（`manuscript`）。入库后在工作台确认大纲，再逐章或连续生成。 |
| **从零开书** | `/create` 或首页「从零开书」：前提/题材/文风 → 种子设定 → 大纲 → 开篇；不要求导入原稿。 |

参考（`reference`）只拆文风与设定，不走续写。

### 首页、导入与空状态

首页是作品架，按 **原稿 / 参考 / 全部** 筛选。打开原稿进入续写；打开参考进入设定（按钮文案是「拆解」）。

| 空状态 | 去向 |
|---|---|
| 书架还是空的 | 导入小说，或新建原稿 |
| 默认续写里没有原稿 | 导入原稿（`/import?role=manuscript`），或新建原稿 |
| 还没有参考小说 | 导入参考（`/import?role=reference`） |

导入页先选用途，再选文件：

- **原稿**：接着写这本书。入库后可大纲、续写，并导出成书。
- **参考**：只拆文风与结构。不会成为可续写正文，也不会导出成书。

支持单个 txt/md，或一个文件夹里的 txt/md。预览分章后可改标题、作者、题材，再确认。确认后自动开始入库。`/import?role=manuscript` 或 `reference` 会预选用途。

### 工作台

分区：**设定**、**大纲**、**续写**（参考本没有这一页）、**用量**、**任务**。参考本打开续写时只说明不会进入续写，并链到设定。

**大纲**三步：规划 → 校对确认 → 连写。

1. 规划章数（1–30，默认 5）和可选指导语，生成大纲。失败可在本页重试。
2. 在蓝图上改标题、梗概、小目标、冲突、悬念、出场人物、要点。先保存再确认。未保存的修改刷新后会丢失。删除大纲会保留已生成正文，只解除关联。
3. 确认后可以连写。导演面板贴在蓝图旁边：已确认大纲、连续序号、`count` 1–10。`run_critic` 为真时，报告 `ok=false`、含 `severity=error`，或没有一致性报告，就停下后续章。只有 warning 且 `ok` 仍为真则继续。参考本返回 **409**。

**续写**四步：选章 → 成稿 → 审阅 → 入库。

- 没有大纲条目时：书还没有章节，提示先生成大纲或导入原文；原文已入库，则提示确认大纲后再写下一章。
- 流式生成可设本章目标字数（1500–30000）。可开关一致性检验，Critic 轮数 0–2。长章超过 `CHAPTER_SEGMENT_THRESHOLD`（默认 4500 字）时按要点分段生成，只审查、不整章重写。
- 版本：`generated` 草稿、`critic_revised` Critic、`user_edited` 修订。
- 审阅里勾选问题后预览修稿，点「确认采用修稿」才写入。「保存修订并入库」做增量摘要、抽取、向量与记忆；失败可重试入库。

### 原稿与参考

导入确认时写入 `role`。已有书和未传该字段的请求默认为 `manuscript`。旧库启动时自动补上 `novels.role`。

| `role` | 用途 |
|---|---|
| `manuscript` | 原稿。可入库、大纲、续写，并可导出 txt/md。列表默认只显示这一类。 |
| `reference` | 仿写参考。仍会入库，抽出 Story Bible 与文风样本。不进入默认续写列表，不能作为章节生成来源，不能导出为书。参考章节不会写进原稿正文。 |

- `POST /api/novels`、`PATCH /api/novels/{id}`、`POST /api/novels/import/confirm` 接受 `manuscript` 或 `reference`
- `GET /api/novels?role=manuscript` 是续写的默认来源；`role=reference` 只返回参考本。不传 `role` 时返回全部
- `GET /api/novels/{id}/export` 对参考本返回 **409**
- `POST /api/novels/{id}/generate` 与 `POST /api/novels/{id}/generate/batch` 对参考本返回 **409**。`GET /api/novels/{id}/generate/stream` 返回 SSE `error`，不改小说状态、不写章节
- `POST /api/novels/{id}/ingest` 对参考本仍然可用

### 任务

工作台路径：`/novels/{id}/tasks`。页上汇总进行中与可重试数量；`batch_generate` 显示为「连续生成」。空列表说明入库、大纲、修订和连续生成都会出现在这里。取消若未立刻结束，界面提示当前步骤结束后停止。

| 动作 | 行为 |
|---|---|
| 取消 | `POST /api/tasks/{id}/cancel`。排队中或执行中可取消。已结束返回 409；重复取消返回当前任务。 |
| 重试 | `POST /api/tasks/{id}/retry`。仅 `failed` 或 `cancelled` 且 `recoverable=true`。当前可重试：`ingest`、`outline_generate`、`revise_commit`。返回新任务。入库重试会重新跑入库。 |
| 进度 | `GET /api/tasks/{id}/events` SSE。终态：`completed` / `failed` / `cancelled`。 |

连续生成（`batch_generate`）可以取消，不在可重试类型里。

### 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+、FastAPI、Uvicorn、Pydantic v2 |
| 数据 | SQLite（WAL）+ SQLAlchemy 2.0 async + sqlite-vec |
| LLM | OpenAI / Anthropic 官方 SDK（自定义 `base_url`），进程内 asyncio 任务队列 |
| Agent | **LangGraph** 编排 Critic 回路（`AGENT_RUNTIME=langgraph`，可回退 `legacy`） |
| 前端 | Vue 3、TypeScript、Vite、Pinia、TailwindCSS |
| 部署 | Docker Compose、nginx、Makefile、`scripts/package.sh` |
| 测试 | pytest、pytest-asyncio、httpx |

### 目录结构

```
MythWeaver/
├── backend/                 # FastAPI、LLM 适配、服务、Agent 与测试
├── frontend/                # Vue 3（首页 / 导入 / 设定 / 大纲 / 续写 / 用量 / 任务）
├── data/                    # SQLite 与导入备份（运行时生成）
├── docs/                    # 架构说明与 API 规格
├── scripts/package.sh       # 前端 dist，或构建 Compose 镜像
├── Makefile                 # up / down / package / dist
├── docker-compose.yml       # 后端 + nginx 前端
├── Dockerfile.backend
├── Dockerfile.frontend
├── nginx.conf
└── .github/workflows/       # CI
```

### 环境要求

- Python **3.11+**
- Node.js 18+（本地前端；CI 使用 Node 20）
- 可用的 LLM API（OpenAI 兼容和/或 Anthropic）
- 自托管时需要 Docker Compose

### 快速开始

#### 1. 配置环境变量

```bash
cd backend
cp .env.example .env          # Windows: copy .env.example .env
```

编辑 `backend/.env`，填入摘要、生成、Embedding 的 `API_KEY`、`BASE_URL` 与模型名。不要提交真实密钥。

#### 2. 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：`GET http://localhost:8000/api/health`

#### 3. 前端

```bash
cd frontend
npm install
npm run dev
```

打开 Vite 提示的地址（默认 `http://localhost:5173`）。开发模式下 `/api` 代理到 `http://localhost:8000`。

#### 4. 打包与一键部署

先准备 `backend/.env`。密钥留在环境文件里，不打进镜像。

```bash
make up      # docker compose up --build -d
```

打开 **http://localhost:8080**。nginx 把 `/api` 反代到后端；数据在卷 `mythweaver-data`。前端会等后端 `/api/health` 通过后再启动。`make down` 停止。

只构建镜像（需要 Docker，且已有 `backend/.env`）：

```bash
make package                  # ./scripts/package.sh docker
docker compose up -d
```

只产出前端静态文件（自行用 nginx 托管，并把 `/api` 反代到后端 8000）：

```bash
make dist                     # ./scripts/package.sh dist
# 输出 dist/release/web
```

### 配置

配置在 `backend/.env`，模板 `backend/.env.example`。

- `SUMMARY_PROVIDER` / `GENERATION_PROVIDER`：`openai` 或 `anthropic`，各自有 `*_BASE_URL`、`*_API_KEY`、`*_MODEL`
- Embedding 走 OpenAI 兼容端点：`EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` / `EMBEDDING_DIMS`。Kimi 官方没有 embedding，需要另配向量服务
- `AGENT_RUNTIME`：`langgraph`（默认）或 `legacy`
- `CONTEXT_TOKEN_BUDGET` 默认 16000
- `INGEST_CONCURRENCY` 与 `LLM_MAX_CONCURRENCY` 默认 2（给组织并发上限 3 留余量）。`EMBEDDING_MAX_CONCURRENCY` 单独设置。另有 `LLM_RPM` / `LLM_TPM`
- 篇幅：`GENERATION_MAX_TOKENS`、`CHAPTER_SEGMENT_THRESHOLD`、`SEGMENT_TARGET_CHARS`
- `GET /api/config` 只报告密钥是否已配置，不返回明文

用量页（`/novels/{id}/costs`）读 `stage_routes` 与 `GET /api/costs`：

| 阶段 | 界面上的模型 | 用途标签 |
|---|---|---|
| 摘要 / 抽取 | `SUMMARY_*` | summary, extract, memory, style |
| 大纲 / 续写 | `GENERATION_*` | outline, generation |
| 审校 Critic | 界面显示 `SUMMARY_*` | critic, consistency |
| 向量化 | `EMBEDDING_*`（provider 标为 openai） | embed |

一致性校验（`consistency`）调用摘要端点。Critic 自动修稿（`critic`）调用生成端点；正文长于分段阈值时跳过整章重写。成本上，`critic` 与 `consistency` 按 `COST_SUMMARY_*` 估算，`outline` 与 `generation` 按 `COST_GENERATION_*`，`embed` 按 `COST_EMBEDDING`（USD / 1M tokens）。`GET /api/costs?novel_id=` 返回总额、`by_purpose`、`by_purpose_tokens` 和最近调用。

前端「LLM 设置」（`/settings/providers`）可以查看当前生效的厂商、模型和密钥状态（匿名或掩码），并把正在生效的连接存成命名配置。配置写在本机 SQLite，启用后续写和向量立刻改用该配置。接口不返回明文密钥。「测试连接」仍然只探测、不把这次输入单独落库。没有启用配置时，仍读 `backend/.env`。

### 厂商预设与配置档案

前端「LLM 设置」页列出常见 OpenAI 兼容厂商，选中后填入默认 Base URL 和模型。「测试连接」调用 `POST /api/providers/test`，这次填写的密钥只用于探测。

同一页可以「存下当前生效配置」。档案包括续写 / 摘要 / 向量的地址、模型和密钥，保存在本机数据库。列表里可以启用、改名、用当前生效覆盖，或删除。启用后 `GET /api/config` 的 `stage_routes` 与后续生成、向量请求都走该档案。删除正在使用的档案后回到 `.env`。响应里的密钥只有 `anonymous` 或末四位掩码。

### 测试

```bash
cd backend
pytest
```

测试目录由 `backend/pytest.ini` 指定为 `tests/`。需要真实 API 的用例请自行配置 `.env`；默认以 mock 与本地逻辑为主。

持续集成见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。推送到 `main` 或 `master`，以及对这两个分支的 pull request，会并行执行：

- 后端：Python 3.11，安装 `requirements.txt` 后运行 `pytest`（沿用测试内的 mock，不注入 API 密钥）
- 前端：Node.js 20，`npm ci` 后执行 `npm run build`（含 `vue-tsc`）

`sqlite-vec` 使用 PyPI wheel。GitHub 托管 runner 上由 `actions/setup-python` 提供的 CPython 可加载 SQLite 扩展。

### 文档与接口

- [架构说明](docs/ARCHITECTURE.md)：模块、数据模型、生成回路
- [API 规格](docs/API_SPEC.md)：REST / SSE 全文

常用入口：

- `GET /api/health`（接口、数据库、模型；`?probe=llm` 探测续写密钥）、`GET /api/config`（含 `stage_routes`）
- `GET /api/providers`、`POST /api/providers/test`
- `GET/POST /api/novels`，`POST /api/novels/import/preview` 与 `/confirm`，`POST /api/novels/{id}/ingest`，`GET /api/novels/{id}/export`
- `/api/novels/{id}/bible`：人物、世界观、伏笔
- `POST /api/novels/{id}/outlines/generate`，`POST .../outlines/{oid}/confirm`
- `POST` 与 `GET /api/novels/{id}/generate`（及 `/stream`），`POST .../generate/batch`
- `GET /api/tasks`，`POST /api/tasks/{id}/cancel` 与 `/retry`，`GET /api/tasks/{id}/events`
- `GET /api/costs`

### 许可

仓库根目录没有 `LICENSE` 文件。再使用或再分发前请自行确认权利。

---

## English

[中文](#中文) · [README.en.md](README.en.md)

A single-machine workbench for continuing web novels. Layered summaries, vector retrieval, and a Story Bible compress a long source into about 16K tokens of generation context. Continuation is streamed, then checked by a consistency critic loop.

The same page is also published as [README.en.md](README.en.md).

### Capabilities

- **Ingest**: split chapters, summarize chapters and volumes, extract entities, embed with sqlite-vec. Chapters that are already embedded are skipped; unfinished chapters resume summary and extraction from their status. Progress is SSE.
- **Story Bible**: characters (with aliases), world settings, and plot threads, all editable. Relationships become a graph: a name that matches a card or an alias links to that character. Foreshadowing, main plots, and side plots are laid out on a timeline by the chapter where they appear and the chapter where they resolve. The graph and timeline are drawn in the frontend from Bible data.
- **Outline first**: generate, edit, and confirm before writing. Each beat has a blueprint: the lead's goal, conflict and turn, end hook, on-stage characters, and key points. After confirmation those fields go into retrieval and the generation prompt.
- **Streaming continuation**: SSE. Context assembles recent prose, summaries, RAG, the Bible, style samples, and recurrent memory.
- **Director**: on a confirmed outline, write up to 10 consecutive chapters from a chosen order. If the critic fails, generation errors, or the task is cancelled, the chapter in progress finishes and the next one does not start.
- **Consistency critic**: rules plus an LLM, at most 2 automatic revise rounds, plus an issue report. **LangGraph** is the default (`AGENT_RUNTIME=langgraph`); `legacy` is the fallback. On the review step you select issues, preview a revision, and confirm before it is saved.
- **Tasks**: cancel a queued or running task. Retry is available for failed or cancelled ingest, outline generation, and revise-commit when the task is recoverable.
- **Usage**: stage model routes, plus token and estimated cost totals per purpose.

Two ways in:

| Path | What you do |
|---|---|
| **Continuation** | Import a manuscript (`manuscript`). After ingest, confirm an outline in the workbench, then write chapter by chapter or in a batch. |
| **From scratch** | On an empty shelf, choose “新建原稿”: enter a title only. `POST /api/novels` creates an empty book with `role=manuscript` and opens the outline page. |

A reference book (`reference`) is for style and setting only. It is not a continuation source.

### Home, import, and empty states

The home page is a shelf filtered by **manuscript / reference / all**. Opening a manuscript goes to continuation. Opening a reference goes to the Bible (the button says 拆解).

| Empty state | Next step |
|---|---|
| Shelf is empty | Import a book, or create a blank manuscript |
| No manuscript in the default continuation list | Import a manuscript (`/import?role=manuscript`), or create a blank one |
| No reference books | Import a reference (`/import?role=reference`) |

Import asks for the role before the file:

- **Manuscript**: continue this book. After ingest you can outline, write, and export.
- **Reference**: extract style and structure only. It does not become continuable prose and cannot be exported as a book.

Upload one `.txt` or `.md` file, or a folder of them. Preview the chapter split, edit title, author, and genre, then confirm. Confirm starts ingest. `/import?role=manuscript` or `reference` preselects the role.

### Workbench

Sections: **Bible**, **Outline**, **Write** (hidden for a reference), **Usage**, **Tasks**. Opening Write on a reference only explains that it will not be continued, and links to the Bible.

**Outline** has three steps: plan, review and confirm, batch write.

1. Set a chapter count (1–30, default 5) and an optional guidance note, then generate. A failed generate can be retried on this page.
2. Edit title, summary, goal, conflict, hook, characters, and key points on the blueprint. Save, then confirm. Unsaved edits are lost on refresh. Deleting an outline keeps generated chapter text and only unlinks it.
3. After confirmation, batch writing is available. The director sits beside the blueprint. It needs a confirmed outline, consecutive orders, and a `count` of 1–10. When `run_critic` is on, a report with `ok=false`, an issue of `severity=error`, or a missing consistency report stops later chapters. Warnings with `ok` still true do not. A reference returns **409**.

**Write** has four steps: pick a chapter, draft, review, commit.

- With no outline items: an empty book asks you to generate an outline or import source text; an ingested book asks you to confirm an outline before the next chapter.
- Streaming can target 1500–30000 characters. Consistency checking can be turned off. Critic rounds are 0–2. A chapter longer than `CHAPTER_SEGMENT_THRESHOLD` (default 4500 characters) is generated in segments from the key points: it is checked, and the whole chapter is not rewritten.
- Versions: `generated` (draft), `critic_revised` (Critic), `user_edited` (revision).
- In review, select issues, preview a revision, then confirm before it is written. “Save revision and ingest” updates summaries, entities, vectors, and memory. A failed commit can be retried.

### Manuscript and reference

`role` is stored when import is confirmed. Existing books, and requests that omit the field, default to `manuscript`. Older databases gain `novels.role` on startup.

| `role` | Use |
|---|---|
| `manuscript` | Source you can continue. Ingest, outline, write, and export as txt/md. The list defaults to this role. |
| `reference` | A model to imitate. It is still ingested, and yields a Story Bible and style samples. It stays out of the default continuation list, cannot be a generation source, and cannot be exported as a book. Its chapters are not copied into a manuscript. |

- `POST /api/novels`, `PATCH /api/novels/{id}`, and `POST /api/novels/import/confirm` accept `manuscript` or `reference`
- `GET /api/novels?role=manuscript` is the default continuation source; `role=reference` returns only references. Omitting `role` returns both
- `GET /api/novels/{id}/export` returns **409** for a reference
- `POST /api/novels/{id}/generate` and `POST /api/novels/{id}/generate/batch` return **409** for a reference. `GET /api/novels/{id}/generate/stream` emits an SSE `error` and does not change novel state or write a chapter
- `POST /api/novels/{id}/ingest` still works for a reference

### Tasks

Workbench path: `/novels/{id}/tasks`. The page counts in-progress and retryable tasks, and labels `batch_generate` as 连续生成. An empty list says ingest, outline, revise-commit, and batch generation all show up here. If cancel does not finish immediately, the UI says the current step stops when it ends.

| Action | Behavior |
|---|---|
| Cancel | `POST /api/tasks/{id}/cancel` for a queued or running task. A finished task returns 409. Cancelling again returns the current task. |
| Retry | `POST /api/tasks/{id}/retry` only when status is `failed` or `cancelled` and `recoverable` is true. Retryable types today: `ingest`, `outline_generate`, `revise_commit`. The call returns a new task. Ingest retry runs ingest again. |
| Progress | `GET /api/tasks/{id}/events` (SSE). Terminal states: `completed`, `failed`, `cancelled`. |

Batch generation (`batch_generate`) can be cancelled. It is not a retryable type.

### Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 |
| Data | SQLite (WAL) + SQLAlchemy 2.0 async + sqlite-vec |
| LLM | Official OpenAI / Anthropic SDKs (custom `base_url`), in-process asyncio task queue |
| Agent | **LangGraph** critic loop (`AGENT_RUNTIME=langgraph`, fallback `legacy`) |
| Frontend | Vue 3, TypeScript, Vite, Pinia, TailwindCSS |
| Deploy | Docker Compose, nginx, Makefile, `scripts/package.sh` |
| Tests | pytest, pytest-asyncio, httpx |

### Layout

```
MythWeaver/
├── backend/                 # FastAPI, LLM adapters, services, agents, tests
├── frontend/                # Vue 3 (home / import / bible / outline / write / usage / tasks)
├── data/                    # SQLite and import backups (created at runtime)
├── docs/                    # Architecture and API spec
├── scripts/package.sh       # Frontend dist, or Compose image build
├── Makefile                 # up / down / package / dist
├── docker-compose.yml       # API + nginx UI
├── Dockerfile.backend
├── Dockerfile.frontend
├── nginx.conf
└── .github/workflows/       # CI
```

### Requirements

- Python **3.11+**
- Node.js 18+ for the local frontend (CI uses Node 20)
- An LLM API (OpenAI-compatible and/or Anthropic)
- Docker Compose for the self-host path

### Quick start

#### 1. Environment

```bash
cd backend
cp .env.example .env          # Windows: copy .env.example .env
```

Edit `backend/.env`. Set `API_KEY`, `BASE_URL`, and model names for summary, generation, and embedding. Do not commit real keys.

#### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/api/health`

#### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (default `http://localhost:5173`). In dev, `/api` is proxied to `http://localhost:8000`.

#### 4. Package and one-command deploy

Prepare `backend/.env` first. Keys stay in that file; they are not baked into the image.

```bash
make up      # docker compose up --build -d
```

Open **http://localhost:8080**. nginx proxies `/api` to the backend. Data lives in the `mythweaver-data` volume. The frontend waits until `/api/health` succeeds. `make down` stops the stack.

Build images only (Docker required, and `backend/.env` must exist):

```bash
make package                  # ./scripts/package.sh docker
docker compose up -d
```

Frontend static files only (serve them yourself and proxy `/api` to backend port 8000):

```bash
make dist                     # ./scripts/package.sh dist
# writes dist/release/web
```

### Configuration

Settings live in `backend/.env`. The template is `backend/.env.example`.

- `SUMMARY_PROVIDER` / `GENERATION_PROVIDER`: `openai` or `anthropic`, each with `*_BASE_URL`, `*_API_KEY`, and `*_MODEL`
- Embeddings use an OpenAI-compatible endpoint: `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` / `EMBEDDING_DIMS`. Moonshot/Kimi has no official embedding API; point `EMBEDDING_*` at another service
- `AGENT_RUNTIME`: `langgraph` (default) or `legacy`
- `CONTEXT_TOKEN_BUDGET` defaults to 16000
- `INGEST_CONCURRENCY` and `LLM_MAX_CONCURRENCY` default to 2 (headroom under an org limit of 3). `EMBEDDING_MAX_CONCURRENCY` is separate. `LLM_RPM` / `LLM_TPM` apply as well
- Length: `GENERATION_MAX_TOKENS`, `CHAPTER_SEGMENT_THRESHOLD`, `SEGMENT_TARGET_CHARS`
- `GET /api/config` reports whether keys are set. It does not return the key text

The usage page (`/novels/{id}/costs`) reads `stage_routes` and `GET /api/costs`:

| Stage | Model shown | Purpose tags |
|---|---|---|
| Summary / extract | `SUMMARY_*` | summary, extract, memory, style |
| Outline / write | `GENERATION_*` | outline, generation |
| Critic | UI shows `SUMMARY_*` | critic, consistency |
| Embedding | `EMBEDDING_*` (provider labeled openai) | embed |

The consistency check (`consistency`) calls the summary endpoint. Automatic critic rewrites (`critic`) call the generation endpoint; chapters longer than the segment threshold skip a full rewrite. For cost, `critic` and `consistency` use `COST_SUMMARY_*`, `outline` and `generation` use `COST_GENERATION_*`, and `embed` uses `COST_EMBEDDING` (USD per 1M tokens). `GET /api/costs?novel_id=` returns the total, `by_purpose`, `by_purpose_tokens`, and recent calls.

LLM settings (`/settings/providers`) show the active provider, models, and key mode (anonymous or masked). The current connection can be saved as a named profile in the local SQLite database. Activating a profile switches generation and embedding immediately. Connection tests still do not store the probe key. With no profile active, the app reads `backend/.env`.

### Tests

```bash
cd backend
pytest
```

`backend/pytest.ini` points tests at `tests/`. Cases that need a real API expect you to configure `.env`. The default suite uses mocks and local logic.

CI is [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Pushes to `main` or `master`, and pull requests into those branches, run in parallel:

- Backend: Python 3.11, install `requirements.txt`, run `pytest` (in-test mocks; no API keys injected)
- Frontend: Node.js 20, `npm ci`, then `npm run build` (includes `vue-tsc`)

`sqlite-vec` is installed from its PyPI wheel. CPython from `actions/setup-python` can load SQLite extensions.

### Docs and API

- [Architecture](docs/ARCHITECTURE.md): modules, data model, generation loop
- [API spec](docs/API_SPEC.md): full REST / SSE list

Entry points:

- `GET /api/health` (API, database, model; `?probe=llm` checks the saved generation key), `GET /api/config` (includes `stage_routes`)
- `GET /api/providers`, `POST /api/providers/test`
- `GET/POST /api/novels`, `POST /api/novels/import/preview` and `/confirm`, `POST /api/novels/{id}/ingest`, `GET /api/novels/{id}/export`
- `/api/novels/{id}/bible`: characters, world settings, plot threads
- `POST /api/novels/{id}/outlines/generate`, `POST .../outlines/{oid}/confirm`
- `POST` and `GET /api/novels/{id}/generate` (and `/stream`), `POST .../generate/batch`
- `GET /api/tasks`, `POST /api/tasks/{id}/cancel` and `/retry`, `GET /api/tasks/{id}/events`
- `GET /api/costs`

### License

This repository does not include a `LICENSE` file. Confirm rights before reuse or redistribution.
