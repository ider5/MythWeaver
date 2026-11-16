# MythWeaver API 规格

Base URL：`http://localhost:8000`（前端开发代理 `/api`）

## 健康检查

- `GET /api/health` → `{ status, app, ready, first_run, novel_count, checks }`
  - `checks.api` / `checks.db`：`ok`、`detail`。数据库不可读写时 HTTP 503，`status` 为 `degraded`。
  - `checks.llm`：`ok`、`configured`、`probed`、`detail`、`latency_ms`、`reply`、`stages`（摘要 / 续写 / 向量的地址与模型，不含密钥）。`sk-your-*` 视为未配置；`anonymous` 视为已配置。
  - 密钥未配置仍返回 200，避免空密钥把容器健康检查打失败。
  - `?probe=llm`（也接受 `1` / `true`）用当前生效的续写密钥（已启用的配置，否则 `.env`）调用与 `POST /api/providers/test` 相同的探测。未配置时不发请求。
  - `first_run`：没有书，或续写密钥未配置。

## 配置

- `GET /api/config` → 模型与密钥是否配置（不返回明文 key）；含 `stage_routes`（阶段→provider/model/用途）

## LLM 厂商预设

- `GET /api/providers` → `{ presets: [{ id, label, base_url, default_model, models, docs_url, notes }] }`
- `POST /api/providers/test` → body `{ vendor_id?, api_key, base_url?, model? }`；响应 `{ ok, error?, latency_ms?, reply?, base_url?, model? }`。这次探测的密钥不落库。
- `GET /api/providers/active` → 当前生效连接（`source`: `env` | `profile`）。含 provider、base_url、模型、向量维度；密钥只回 `generation_key` / `summary_key` / `embedding_key` 的 `{ mode: anonymous|keyed, mask }`，没有明文。
- `GET /api/providers/profiles` → `{ profiles: [...] }`，字段同上，另有 `id`、`name`、`is_active`。
- `POST /api/providers/profiles` → `{ name, from_current?, activate?, ... }`。`from_current: true` 把正在生效的地址、模型和密钥存成新配置（密钥仍只回掩码）。否则提交续写与向量字段。
- `PATCH /api/providers/profiles/{id}` → 改名或改字段。密钥字段省略则保留，`""` 清空。
- `POST /api/providers/profiles/{id}/activate` → 启用。续写、摘要、向量立刻改走该配置。
- `POST /api/providers/profiles/{id}/update-from-current` → 用当前生效配置覆盖这条，不切换。
- `DELETE /api/providers/profiles/{id}` → 删除。删掉正在用的那条后回到 `.env`。配置存在本机 SQLite。

## 阶段写法

只接受 SKILL.md 文本。frontmatter 仅 `name`、`description`、`stage`（`outline` | `draft` | `critic` | `revise`）。正文是提示词。安装前用预览接口看解析结果；预览不落库、不调用模型。服务端不执行脚本、不加载 YAML 对象、不读取同目录其他文件。启用后的提示词按字面量写入对应阶段：大纲 `outline.j2`、正文 `generation.j2`、审校 `consistency.j2`、修稿 `critic.j2`。正文里的 `{{ }}` 或 `{% %}` 不会被当成模板执行。

- `GET /api/skills` → 已安装列表。`enabled` 为真且未超出该阶段篇幅时 `injected` 为真。
- `GET /api/skills/catalog` → 内置示例的名称、说明和阶段，不含正文。
- `POST /api/skills/preview` → `{ source }` 或 `{ catalog_id }`，二选一。返回 `{ ok, errors, name, description, stage, stage_label, body, already_installed }`。
- `POST /api/skills` → 同样的来源，另加 `replace`。同名且未覆盖返回 409。超出阶段篇幅则保存但 `enabled=false`，并带 `warning`。非法文件返回 400，不落库。
- `PATCH /api/skills/{id}` → `{ enabled }`。打开后会超出篇幅则 409。
- `DELETE /api/skills/{id}` → `{ message, id }`。

## 小说

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/novels` | 列表。可选 `?role=manuscript` 或 `?role=reference`，以及 `?origin=import` 或 `?origin=scratch`。续写默认来源用 `manuscript` |
| POST | `/api/novels` | 创建导入向的空书。`role` 缺省 `manuscript`，`origin` 固定 `import` |
| POST | `/api/novels/scratch` | 从零开书。`{ title, genre?, premise, writing_style, author? }`。不接收原稿，`origin=scratch`，`status=blank` |
| POST | `/api/novels/{id}/scratch/seed` | 用前提播种 Story Bible。导入书返回 409。成功后 `status=seeded` |
| GET | `/api/novels/{id}` | 详情，含 `role` |
| PATCH | `/api/novels/{id}` | 更新，可改 `role` |
| DELETE | `/api/novels/{id}` | 删除 |
| POST | `/api/novels/import/preview` | multipart：`file`（txt / md / epub）或 `files`（txt / md）+ `title`。EPUB 按目录拆章，预览带书内标题、作者和卷名 |
| POST | `/api/novels/import/confirm` | `{ import_token, title?, author?, genre?, role? }`。`role`：`manuscript`（原稿，默认可续写导出）或 `reference`（参考，只拆文风与设定） |
| POST | `/api/novels/{id}/ingest` | 启动入库 → `{ task_id }`。参考本同样可入库 |
| GET | `/api/novels/{id}/export` | 导出 txt / md / epub。可选 `volume` 或 `chapter_id`，二者只能有一个；缺省导出全书。参考本返回 409 |
| GET | `/api/novels/{id}/backup` | 下载单本 ZIP 数据备份。原稿与参考本都可以。不含任务、费用和 WebDAV |
| POST | `/api/novels/backup/restore` | multipart：`file` 为 ZIP，可选表单 `title`。恢复成一本新小说，不覆盖原书 |
| GET | `/api/novels/{id}/chapters` | 章节列表（不含正文） |
| GET | `/api/novels/{id}/chapters/{cid}` | 章节正文 |
| GET | `/api/novels/{id}/chapters/{cid}/versions` | 版本链 |
| POST | `/api/novels/{id}/chapters/{cid}/revise` | `{ content, commit_to_knowledge }` |
| POST | `/api/novels/{id}/chapters/{cid}/critic-select-revise` | 按勾选问题修稿：`{ content, issues[], confirm?, commit_to_knowledge? }` → `{ base_content, revised_content, consistency, changed, version_id?, task_id? }`；`confirm=false` 仅预览不落库 |

`role` 缺省为 `manuscript`。`origin` 缺省为 `import`。参考本可以抽取 Story Bible 与文风，但章节不作为续写来源：`POST /api/novels/{id}/generate` 返回 409；`GET .../generate/stream` 只发出 SSE `error`，不改状态、不写章节。

从零开书（`origin=scratch`）没有原稿：`POST /ingest` 返回 409。播种设定后走原有大纲生成、确认和批量开篇；开篇提示会带上前提和文风。

### 作品 ZIP 备份

`GET /api/novels/{id}/backup` 返回 `application/zip`。`manifest.json` 的 `format` 为 `mythweaver-novel-backup`，`version` 为 `1`。`rows/*.json` 每张表一个数组：小说、章节、版本、摘要、人物、世界观、伏笔、设定提案、大纲、大纲条目、文风样本、递归记忆。

不包含 `async_tasks` 和 `cost_logs`，也没有 WebDAV。章节向量在 `embedding_json` 里，恢复时按当前维度写回 sqlite-vec。`source_path` 只留在备份里，新书不写本地路径。状态为 `ingesting` 或 `generating` 时，新书改为 `ready`（没有章节则为 `imported`）。

`POST /api/novels/backup/restore` 校验路径、体积、外键和版本链后分配新主键。可选 `title` 覆盖书名。包不合法返回 400，超过 80MB 返回 413，下载不存在的小说返回 404。

## Story Bible

前缀：`/api/novels/{id}/bible`

- `GET /` 完整 Bible
- `POST|PATCH|DELETE /characters[/{cid}]`
- `POST|PATCH|DELETE /world-settings[/{wid}]`
- `POST|PATCH|DELETE /plot-threads[/{tid}]`

## 大纲

前缀：`/api/novels/{id}/outlines`

- `GET /` 列表
- `POST /generate` `{ chapter_count, guidance?, start_from_chapter? }`
- `GET|PUT /{oid}`
- `POST /{oid}/confirm`

条目除原有 `order`、`title`、`summary`、`key_points`、`status` 外，增加章节蓝图字段。旧库缺列时启动自动补齐，读出来为空，已有标题与概要保持不变。

| 字段 | 类型 | 含义 |
|------|------|------|
| `purpose` | string | 主角小目标 |
| `conflict` | string | 冲突与转折 |
| `suspense_hook` | string | 章末悬念钩子 |
| `characters` | string[] | 出场人物 |

`PUT` 未带某个蓝图字段（或传 `null`）时保留库内原值；传空字符串或空数组会清空。生成大纲时模型会填写这些字段。确认后的条目进入续写：检索查询和章节生成提示都会带上小目标、冲突与转折、悬念钩子和出场人物。

## 续写（SSE）

- `GET /api/novels/{id}/generate/stream?outline_item_id=&run_critic=&max_critic_rounds=`
- `POST /api/novels/{id}/generate` body 同上，响应同为 SSE
- `POST /api/novels/{id}/generate/batch` 连续生成已确认大纲中的一段：`{ outline_id, from_order, count≤10, run_critic, spot_check? }` → `{ task_id, status }`。按序号逐章调用同一条生成路径。进度在 `GET /api/tasks/{tid}` 的 `result.items`。`spot_check=true` 时完整 Critic 只跑首章、末章和每隔 3 章。篇幅偏离目标 ±20%，章末没落到大纲悬念钩子，或 Critic 出现 `severity=error` 时暂停。warning（文风漂移、伏笔提醒、套话）记在该章 `message` / `quality_hints` 上，后续继续。生成抛错同样停下。参考本与单章续写一样返回 409。
- `GET /api/novels/{id}/open-threads?chapter_index=` 写作台未回收伏笔。`due` 为 `approaching` | `due` | `overdue`，没有计划回收章时为 null。
- `GET /api/novels/{id}/chapters/{cid}/quality` 对照已保存文风样本、计划回收章、篇幅和章末钩子。不调用模型。

伏笔 `planned_resolve_chapter` 可空。空表示尚未安排回收；临近 2 章内、本章、或已逾期才会在质量提示里出现。

SSE `done` 增加 `quality`：`{ chapter_index, critical, hints[] }`。

取消用现有 `POST /api/tasks/{tid}/cancel`。正在写的一章会写完，下一章不再开始。

事件 JSON：

```json
{"event":"status","message":"..."}
{"event":"delta","text":"..."}
{"event":"done","chapter_id":1,"version_id":1,"content":"...","consistency":{}}
{"event":"error","message":"..."}
```

## 任务 / 成本

- `GET /api/tasks?novel_id=` 列表。`recoverable: true` 表示失败或已取消、且可以重试
- `GET /api/tasks/{tid}`
- `POST /api/tasks/{tid}/cancel` 取消排队中或执行中的任务。已结束返回 409；重复取消返回当前任务
- `POST /api/tasks/{tid}/retry` 重试可恢复任务。入库会重新调用入库；返回新任务
- `GET /api/tasks/{tid}/events` SSE 进度（终态含 completed / failed / cancelled）
- `GET /api/costs?novel_id=` → 汇总成本；含 `by_purpose` 与 `by_purpose_tokens`（各用途 in/out/cost）

## 一致性报告结构

```json
{
  "ok": false,
  "issues": [{"type":"alias","severity":"warning","message":"...","detail":null}],
  "critic_rounds": 1
}
```
