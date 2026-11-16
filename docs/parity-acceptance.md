# MythWeaver 对标验收清单

对照 [peer-benchmark.md](./peer-benchmark.md)。  
更新：2026-11-17（Asia/Shanghai）  
证据锚点：`origin/master` `ba83b0c`

## 选定基准

- UX / 闭环：Pagekin
- 部署：show-me-the-story
- 能力上限参考：Biz Novel Studio（不全量追平）

同行格子没有在本轮重爬。新增能力只写 MythWeaver 仓库里能对上的行为。

## P0–P1（须 ●）

| 项 | 现状 | 证据 |
|----|------|------|
| CI | ● | [#3](https://github.com/ider5/MythWeaver/pull/3) |
| 一键部署 | ● Compose + packaging。无安装包、无单二进制 | [#4](https://github.com/ider5/MythWeaver/pull/4)、[#15](https://github.com/ider5/MythWeaver/pull/15) |
| 模型预设 / 连接测试 | ● | [#5](https://github.com/ider5/MythWeaver/pull/5) |
| 大纲蓝图字段 | ● | [#6](https://github.com/ider5/MythWeaver/pull/6) |
| Critic 勾选 + 修稿确认 | ● | [#8](https://github.com/ider5/MythWeaver/pull/8) |
| LangGraph Critic | ● | [#7](https://github.com/ider5/MythWeaver/pull/7) |

**结论：P0–P1 已达标。**

## Round 2 已合并（#16–#28）

[#19](https://github.com/ider5/MythWeaver/pull/19) 收到 #18。下表从那之后补到 `ba83b0c`。

| 项 | 现状 | 证据 |
|----|------|------|
| 视觉系统 | ● 首页与工作区色板、层级；系统「减少动态」时关掉动画 | [#16](https://github.com/ider5/MythWeaver/pull/16) |
| 导入与空状态 | ● 原稿 / 参考分流；空书架指向导入或开书 | [#17](https://github.com/ider5/MythWeaver/pull/17) |
| 写作 / 大纲台 | ● 大纲三步，续写四步 | [#18](https://github.com/ider5/MythWeaver/pull/18) |
| 任务中心 | ● 状态、进度、取消、重试。可重试类型没有扩大 | [#20](https://github.com/ider5/MythWeaver/pull/20) `frontend/src/views/TaskHistory.vue` |
| 生成章回写确认 | ● 勾选后写入，或放弃。入库仍自动合并 | [#21](https://github.com/ider5/MythWeaver/pull/21) `backend/tests/test_writeback.py` |
| 匿名 OpenAI 兼容端点 | ● `anonymous` / `none` / `no-key` / `nokey` 去掉 Authorization；OVH 预设。空密钥仍算未配置。无专用测试 | [#22](https://github.com/ider5/MythWeaver/pull/22) |
| 中英 README | ● `README.md` 与 `README.en.md`。界面仍中文 | [#23](https://github.com/ider5/MythWeaver/pull/23) |
| 从零开书 | ● `origin=scratch`：前提 → 播种 → 大纲 → 开篇。与导入续写分流。开篇复用连续生成 | [#24](https://github.com/ider5/MythWeaver/pull/24) `backend/tests/test_scratch_novel.py` |
| Story Bible 编辑 | ● 人物 / 世界观 / 伏笔可改。未保存会拦截切换。无新的后端模型 | [#25](https://github.com/ider5/MythWeaver/pull/25) `frontend/src/views/StoryBible.vue` |
| 外观偏好 | ● 本机主题、强调色、疏密。无应用内动效开关 | [#26](https://github.com/ider5/MythWeaver/pull/26) `frontend/src/composables/useUiPrefs.ts` |
| 导航保持与任务去重 | ● 会话内 KeepAlive + Pinia 草稿。同书同类型进行中任务 409。刷新不保留草稿 | [#27](https://github.com/ider5/MythWeaver/pull/27) `backend/tests/test_task_cancel.py` |
| 文案与提示词 | ● 界面和 `anti_ai.j2` 改成短约束。不是可编辑资产库 | [#28](https://github.com/ider5/MythWeaver/pull/28) |
| 原稿 EPUB | ● 工作台 TXT / MD / EPUB。EPUB 2，无第三方库。参考本 409。首页按钮仍只出 TXT | [#29](https://github.com/ider5/MythWeaver/pull/29) `backend/tests/test_export.py` |

更细的边界写在 [peer-benchmark.md](./peer-benchmark.md) §3.1。

## 更早的 P2–P3

| 项 | 证据 |
|----|------|
| 参考导入 | [#10](https://github.com/ider5/MythWeaver/pull/10) |
| 任务取消 / 重试 | [#11](https://github.com/ider5/MythWeaver/pull/11) |
| Bible 关系图 / 时间线 | [#12](https://github.com/ider5/MythWeaver/pull/12) |
| 半自动批量导演 | [#13](https://github.com/ider5/MythWeaver/pull/13) |
| 阶段路由与用量 | [#14](https://github.com/ider5/MythWeaver/pull/14) |

## 相对 Pagekin 可演示优势

| 优势 | 证据 |
|------|------|
| 超长文分层压缩续写 | README + `context_builder` / ingestion |
| 自动 Critic（≤2 轮） | consistency + agents + tests |
| 半自动批量导演 | #13 |

从零开书、回写确认、匿名端点和外观偏好是补齐闭环，不单列成优势。

## CI 与启动

| 检查 | 现状 |
|------|------|
| push / PR CI | ● 门禁在 [#3](https://github.com/ider5/MythWeaver/pull/3)。本清单不代替当前 HEAD 的 CI 结果 |
| `docker compose up` / `make` / `scripts/package.sh` | ● README + #15 |

## 仍敞开（不撤销「P0–P1 达到」）

写这份清单时没有未合并的 PR。下面是能力缺口。

- 可编辑写法 / 去 AI 资产库。#28 只改了模板措辞
- 安装包或单二进制
- 事实出处、项目 ZIP、版本历史、WebDAV、Skill 导入
- 界面多语言，以及产品内双语写作
- Round 2 运行录屏未入库。Round 1 录屏在项目 Context `media/mythweaver-running-demo.mp4`，不在本仓库
- 「超越」所需的同书样本对照

世界地图、全自动导演、漫画 / 短剧保持为不追的上限参考。
