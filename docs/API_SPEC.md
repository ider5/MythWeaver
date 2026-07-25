# MythWeaver API 规格

Base URL：`http://localhost:8000`（前端开发代理 `/api`）

## 健康检查

- `GET /api/health` → `{ status, app }`

## 配置

- `GET /api/config` → 模型与密钥是否配置（不返回明文 key）

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
