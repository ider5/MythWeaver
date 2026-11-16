# MythWeaver API 规格

Base URL：`http://localhost:8000`（前端开发代理 `/api`）

## 健康检查

- `GET /api/health` → `{ status, app }`

## 配置

- `GET /api/config` → 模型与密钥是否配置（不返回明文 key）

## LLM 厂商预设

- `GET /api/providers` → `{ presets: [{ id, label, base_url, default_model, models, docs_url, notes }] }`
- `POST /api/providers/test` → body `{ vendor_id?, api_key, base_url?, model? }`；响应 `{ ok, error?, latency_ms?, reply?, base_url?, model? }`。密钥仅用于本次探测，不落库。

## 小说

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/novels` | 列表 |
| GET | `/api/novels/{id}` | 详情 |
| PATCH | `/api/novels/{id}` | 更新 |
| DELETE | `/api/novels/{id}` | 删除 |
| POST | `/api/novels/import/preview` | multipart：`file` 或 `files` + `title` |
| POST | `/api/novels/import/confirm` | `{ import_token, title?, author?, genre? }` |
| POST | `/api/novels/{id}/ingest` | 启动入库 → `{ task_id }` |
| GET | `/api/novels/{id}/chapters` | 章节列表（不含正文） |
| GET | `/api/novels/{id}/chapters/{cid}` | 章节正文 |
| GET | `/api/novels/{id}/chapters/{cid}/versions` | 版本链 |
| POST | `/api/novels/{id}/chapters/{cid}/revise` | `{ content, commit_to_knowledge }` |
| POST | `/api/novels/{id}/chapters/{cid}/critic-select-revise` | 按勾选问题修稿：`{ content, issues[], confirm?, commit_to_knowledge? }` → `{ base_content, revised_content, consistency, changed, version_id?, task_id? }`；`confirm=false` 仅预览不落库 |

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

事件 JSON：

```json
{"event":"status","message":"..."}
{"event":"delta","text":"..."}
{"event":"done","chapter_id":1,"version_id":1,"content":"...","consistency":{}}
{"event":"error","message":"..."}
```

## 任务 / 成本

- `GET /api/tasks?novel_id=`
- `GET /api/tasks/{tid}`
- `GET /api/tasks/{tid}/events` SSE 进度
- `GET /api/costs?novel_id=`

## 一致性报告结构

```json
{
  "ok": false,
  "issues": [{"type":"alias","severity":"warning","message":"...","detail":null}],
  "critic_rounds": 1
}
```
