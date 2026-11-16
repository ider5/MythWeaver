# MythWeaver

[中文](README.md#中文) · **English**

[![CI](https://github.com/ider5/MythWeaver/actions/workflows/ci.yml/badge.svg)](https://github.com/ider5/MythWeaver/actions/workflows/ci.yml)

A single-machine workbench for continuing web novels. Layered summaries, vector retrieval, and a Story Bible compress a long source into about 16K tokens of generation context. Continuation is streamed, then checked by a consistency critic loop.

## Capabilities

- **Ingest**: split chapters, summarize chapters and volumes, extract entities, embed with sqlite-vec. Chapters that are already embedded are skipped; unfinished chapters resume summary and extraction from their status. Progress is SSE.
- **Post-chapter write-back**: after a chapter is generated, list new/updated characters, settings, and plot threads against the Story Bible; apply only after confirm. Manuscript ingest still merges automatically.
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

## Home, import, and empty states

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

## Workbench

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

## Manuscript and reference

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

## Tasks

Workbench path: `/novels/{id}/tasks`. The page counts in-progress and retryable tasks, and labels `batch_generate` as 连续生成. An empty list says ingest, outline, revise-commit, and batch generation all show up here. If cancel does not finish immediately, the UI says the current step stops when it ends.

| Action | Behavior |
|---|---|
| Cancel | `POST /api/tasks/{id}/cancel` for a queued or running task. A finished task returns 409. Cancelling again returns the current task. |
| Retry | `POST /api/tasks/{id}/retry` only when status is `failed` or `cancelled` and `recoverable` is true. Retryable types today: `ingest`, `outline_generate`, `revise_commit`. The call returns a new task. Ingest retry runs ingest again. |
| Progress | `GET /api/tasks/{id}/events` (SSE). Terminal states: `completed`, `failed`, `cancelled`. |

Batch generation (`batch_generate`) can be cancelled. It is not a retryable type.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 |
| Data | SQLite (WAL) + SQLAlchemy 2.0 async + sqlite-vec |
| LLM | Official OpenAI / Anthropic SDKs (custom `base_url`), in-process asyncio task queue |
| Agent | **LangGraph** critic loop (`AGENT_RUNTIME=langgraph`, fallback `legacy`) |
| Frontend | Vue 3, TypeScript, Vite, Pinia, TailwindCSS |
| Deploy | Docker Compose, nginx, Makefile, `scripts/package.sh` |
| Tests | pytest, pytest-asyncio, httpx |

## Layout

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

## Requirements

- Python **3.11+**
- Node.js 18+ for the local frontend (CI uses Node 20)
- An LLM API (OpenAI-compatible and/or Anthropic)
- Docker Compose for the self-host path

## Quick start

### 1. Environment

```bash
cd backend
cp .env.example .env          # Windows: copy .env.example .env
```

Edit `backend/.env`. Set `API_KEY`, `BASE_URL`, and model names for summary, generation, and embedding. Do not commit real keys.

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/api/health`

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (default `http://localhost:5173`). In dev, `/api` is proxied to `http://localhost:8000`.

### 4. Package and one-command deploy

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

## Configuration

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

LLM settings (`/settings/providers`) include presets for OpenAI, DeepSeek, Moonshot, Tongyi, Zhipu, OpenRouter, Ollama, and custom. A preset fills the default base URL and model. “Test connection” calls `POST /api/providers/test`. The key is used for that probe only and is not stored. After a successful test, write the same values into `backend/.env`.

## Tests

```bash
cd backend
pytest
```

`backend/pytest.ini` points tests at `tests/`. Cases that need a real API expect you to configure `.env`. The default suite uses mocks and local logic.

CI is [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Pushes to `main` or `master`, and pull requests into those branches, run in parallel:

- Backend: Python 3.11, install `requirements.txt`, run `pytest` (in-test mocks; no API keys injected)
- Frontend: Node.js 20, `npm ci`, then `npm run build` (includes `vue-tsc`)

`sqlite-vec` is installed from its PyPI wheel. CPython from `actions/setup-python` can load SQLite extensions.

## Docs and API

- [Architecture](docs/ARCHITECTURE.md): modules, data model, generation loop
- [API spec](docs/API_SPEC.md): full REST / SSE list

Entry points:

- `GET /api/health`, `GET /api/config` (includes `stage_routes`)
- `GET /api/providers`, `POST /api/providers/test`
- `GET/POST /api/novels`, `POST /api/novels/import/preview` and `/confirm`, `POST /api/novels/{id}/ingest`, `GET /api/novels/{id}/export`
- `/api/novels/{id}/bible`: characters, world settings, plot threads
- `POST /api/novels/{id}/outlines/generate`, `POST .../outlines/{oid}/confirm`
- `POST` and `GET /api/novels/{id}/generate` (and `/stream`), `POST .../generate/batch`
- `GET /api/tasks`, `POST /api/tasks/{id}/cancel` and `/retry`, `GET /api/tasks/{id}/events`
- `GET /api/costs`

## License

This repository does not include a `LICENSE` file. Confirm rights before reuse or redistribution.
