# MythWeaver 对标验收清单

对照 [peer-benchmark.md](./peer-benchmark.md)。  
更新：2026-11-17（Asia/Shanghai）

## 选定基准

- UX/闭环：Pagekin  
- 部署：show-me-the-story  
- 能力上限参考：Biz Novel Studio（不全量追平）

## P0–P1（须 ●）

| 项 | 现状 | 证据 |
|----|------|------|
| CI | ● | [#3](https://github.com/ider5/MythWeaver/pull/3) |
| 一键部署 | ● Compose + packaging | [#4](https://github.com/ider5/MythWeaver/pull/4)、[#15](https://github.com/ider5/MythWeaver/pull/15) |
| 模型预设/连接测试 | ● | [#5](https://github.com/ider5/MythWeaver/pull/5) |
| 大纲蓝图字段 | ● | [#6](https://github.com/ider5/MythWeaver/pull/6) |
| Critic 勾选+修稿确认 | ● | [#8](https://github.com/ider5/MythWeaver/pull/8) |
| LangGraph Critic | ● | [#7](https://github.com/ider5/MythWeaver/pull/7) |

**结论：P0–P1 已达标。**

## P2–P3（已合）

| 项 | 证据 |
|----|------|
| 参考导入 | [#10](https://github.com/ider5/MythWeaver/pull/10) |
| 任务取消/恢复 | [#11](https://github.com/ider5/MythWeaver/pull/11) |
| Bible 关系图/时间线 | [#12](https://github.com/ider5/MythWeaver/pull/12) |
| 半自动批量导演 | [#13](https://github.com/ider5/MythWeaver/pull/13) |
| 阶段路由与用量 | [#14](https://github.com/ider5/MythWeaver/pull/14) |
| 视觉系统 / 导入空状态 / 工作台流程 | [#16](https://github.com/ider5/MythWeaver/pull/16)、[#17](https://github.com/ider5/MythWeaver/pull/17)、[#18](https://github.com/ider5/MythWeaver/pull/18) |

## 相对 Pagekin 可演示优势

| 优势 | 证据 |
|------|------|
| 超长文分层压缩续写 | README + `context_builder` / ingestion |
| 自动 Critic（≤2 轮） | consistency + agents + tests |
| 半自动批量导演 | #13 |

## CI 与启动

| 检查 | 现状 |
|------|------|
| push/PR CI | ● |
| `docker compose up` / `make` / `scripts/package.sh` | ● README + #15 |

## 进行中（不阻塞「达到」）

- 从零开书完整模式与续写分流
- 章后状态回写提案/确认
- 中英双语 README
- Bible 编辑与任务中心 UI 打磨
- Round 2 运行录屏

Round 1 录屏：项目 Context `media/mythweaver-running-demo.mp4`
