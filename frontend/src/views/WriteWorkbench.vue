<script setup lang="ts">
import { computed, nextTick, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  novelsApi,
  outlineApi,
  tasksApi,
  type Novel,
  type OpenThread,
  type Outline,
  type OutlineItem,
  type QualityHint,
} from '@/api'
import EmptyState from '@/components/EmptyState.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import WritebackReview from '@/components/WritebackReview.vue'
import { useRafText } from '@/composables/useRafText'
import { useWorkspaceUiStore } from '@/stores/workspaceUi'

defineOptions({ name: 'WriteWorkbench' })

/** 超过此时长无任何 SSE 事件（含 ping）则判定卡死；应 > 2× 后端心跳间隔 */
const IDLE_TIMEOUT_MS = 45_000

const route = useRoute()
const novelId = Number(route.params.id)
const ui = useWorkspaceUiStore()
const bootstrapped = ref(false)
const outlines = ref<Outline[]>([])
const outline = ref<Outline | null>(null)
const selected = ref<OutlineItem | null>(null)
const streaming = ref(false)
const status = ref('')
const content = ref('')
const consistency = ref<any>(null)
const openThreads = ref<OpenThread[]>([])
const qualityHints = ref<QualityHint[]>([])
const dismissedHints = ref<Set<string>>(new Set())
const DISMISS_KEY = 'mythweaver.quality.dismissed.v1'
const chapterId = ref<number | null>(null)
const writebackToken = ref(0)
const writebackReload = ref(0)
const versions = ref<any[]>([])
const activeVersionId = ref<number | null>(null)
const compareOpen = ref(false)
const compareA = ref<number | null>(null)
const compareB = ref<number | null>(null)
const error = ref('')
const deleting = ref(false)
const deletingChapter = ref(false)
/** 修订入库进度 */
const revising = ref(false)
const reviseProgress = ref(0)
const reviseMessage = ref('')
const reviseError = ref('')
const reviseFailed = ref(false)
/** 勾选问题 → 修稿预览 → 确认写入 */
const selectedIssueKeys = ref<Set<string>>(new Set())
const previewBase = ref('')
const previewRevised = ref('')
const previewBusy = ref(false)
const confirmBusy = ref(false)
const previewError = ref('')
/** 一致性检验 / Critic：默认开启 + 2 轮（与后端 Query 默认一致） */
const runCritic = ref(true)
const maxCriticRounds = ref(2)
const novelMeta = ref<Novel | null>(null)
const novelLoaded = ref(false)
const planReady = ref(false)
const isReference = computed(() => novelMeta.value?.role === 'reference')
const isScratch = computed(() => novelMeta.value?.origin === 'scratch')
const hasWritePlan = computed(() => (outline.value?.items?.length || 0) > 0)
const noChapters = computed(() => (novelMeta.value?.chapter_count || 0) === 0)
/** 用户可覆盖的本章目标字数 */
const targetChars = ref(3000)
const targetTouched = ref(false)
const SEGMENT_HINT = 4500
let es: EventSource | null = null
let reviseEs: EventSource | null = null
let lastEventId = 0
let idleTimer: ReturnType<typeof setTimeout> | null = null
/** 避免快速切换条目时旧请求覆盖新选择 */
let loadSeq = 0
/** 使进行中的章节加载 / 过期 SSE 回调失效，避免修订写到错误章节 */
let streamEpoch = 0

function invalidateLoadsAndStreams() {
  loadSeq += 1
  streamEpoch += 1
}

const streamEl = ref<HTMLElement | null>(null)
const stream = useRafText(streamEl, streamEl)

const pendingItems = computed(() =>
  (outline.value?.items || []).filter((i) => i.status !== 'done'),
)

/** 当前选中版本无报告时展示友好提示（避免沿用上一份报告） */
const showNoReportHint = computed(
  () => !!chapterId.value && activeVersionId.value != null && !consistency.value && !streaming.value,
)

const reviseBusy = computed(() => revising.value || previewBusy.value || confirmBusy.value)

const issueRows = computed(() => {
  const issues = consistency.value?.issues || []
  return issues.map((iss: any, i: number) => ({
    key: `${i}:${iss.type}:${iss.message}`,
    iss,
  }))
})

const selectedIssueCount = computed(() => selectedIssueKeys.value.size)
const shownThreads = computed(() => openThreads.value.slice(0, 8))
const hiddenThreadCount = computed(() => Math.max(0, openThreads.value.length - shownThreads.value.length))
const deskHints = computed(() =>
  qualityHints.value.filter((hint) => {
    if (hint.kind === 'thread') return false
    if (hint.severity === 'error') return true
    return !dismissedHints.value.has(`${novelId}:${chapterId.value}:${hint.id}`)
  }),
)

function loadDismissed() {
  try {
    const raw = localStorage.getItem(DISMISS_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    dismissedHints.value = new Set(Array.isArray(parsed) ? parsed.filter((item) => typeof item === 'string') : [])
  } catch {
    dismissedHints.value = new Set()
  }
}

function dismissHint(hint: QualityHint) {
  if (hint.severity === 'error' || chapterId.value == null) return
  const next = new Set(dismissedHints.value)
  next.add(`${novelId}:${chapterId.value}:${hint.id}`)
  dismissedHints.value = next
  localStorage.setItem(DISMISS_KEY, JSON.stringify([...next]))
}

async function loadOpenThreads(index: number | null) {
  if (index == null) {
    openThreads.value = []
    return
  }
  try {
    const { data } = await novelsApi.openThreads(novelId, index)
    if (index !== chapterIndex.value) return
    openThreads.value = data.threads || []
  } catch {
    openThreads.value = []
  }
}

async function loadQuality(cid: number, seq?: number) {
  try {
    const { data } = await novelsApi.chapterQuality(novelId, cid)
    if (seq != null && seq !== loadSeq) return
    qualityHints.value = data.hints || []
  } catch {
    if (seq == null || seq === loadSeq) qualityHints.value = []
  }
}

function issueKey(i: number, iss: { type?: string; message?: string }) {
  return `${i}:${iss.type || ''}:${iss.message || ''}`
}

function syncIssueSelection(issues: any[] | undefined) {
  const next = new Set<string>()
  ;(issues || []).forEach((iss, i) => {
    if ((iss.severity || '').toLowerCase() === 'info') return
    next.add(issueKey(i, iss))
  })
  selectedIssueKeys.value = next
}

function toggleIssue(key: string, on: boolean) {
  const next = new Set(selectedIssueKeys.value)
  if (on) next.add(key)
  else next.delete(key)
  selectedIssueKeys.value = next
}

function selectAllIssues() {
  selectedIssueKeys.value = new Set(issueRows.value.map((r: { key: string }) => r.key))
}

function clearIssueSelection() {
  selectedIssueKeys.value = new Set()
}

function clearPreview() {
  previewBase.value = ''
  previewRevised.value = ''
  previewError.value = ''
}

const originalAvgChars = computed(() => {
  const n = novelMeta.value
  if (!n) return 0
  return Number(n.median_chapter_chars || n.avg_chapter_chars || 0)
})

const willSegment = computed(() => Number(targetChars.value) > SEGMENT_HINT)

const tuneSummary = computed(() => {
  const n = Number(targetChars.value)
  const length = Number.isFinite(n) && n > 0 ? `${Math.round(n)} 字` : '字数未设'
  if (!runCritic.value) return `${length} · 不检验`
  if (willSegment.value || Number(maxCriticRounds.value) === 0) return `${length} · 只审查`
  return `${length} · ${maxCriticRounds.value} 轮`
})

const displayChars = computed(() => (streaming.value ? stream.length.value : content.value.length))

const chapterIndex = computed(() => {
  if (!selected.value || !outline.value) return null
  return (outline.value.start_from_chapter || 1) + selected.value.order - 1
})

const doneCount = computed(
  () => (outline.value?.items || []).filter((item) => item.status === 'done').length,
)

const hasBrief = computed(() => {
  const item = selected.value
  if (!item) return false
  return Boolean(
    item.purpose ||
      item.conflict ||
      item.suspense_hook ||
      (item.characters || []).length ||
      (item.key_points || []).length,
  )
})

const committed = computed(
  () => !revising.value && !reviseFailed.value && reviseProgress.value >= 100,
)

const writePhase = computed(() => {
  if (revising.value || reviseFailed.value || committed.value) return 3
  if (consistency.value || previewRevised.value || showNoReportHint.value) return 2
  if (streaming.value || chapterId.value) return 1
  return 0
})

function onTargetCharsInput() {
  targetTouched.value = true
}

function itemStatusLabel(s: string) {
  if (s === 'done') return '已完成'
  if (s === 'generating') return '生成中'
  if (s === 'pending') return '待写'
  return s
}

function versionLabel(t: string) {
  if (t === 'generated') return '草稿'
  if (t === 'segment') return '已写段'
  if (t === 'critic_revised') return 'Critic'
  if (t === 'user_edited') return '修订'
  return t
}

function versionTime(iso?: string | null) {
  if (!iso) return ''
  const raw = String(iso).trim()
  if (!raw) return ''
  const normalized = raw.includes('T') ? raw : raw.replace(' ', 'T')
  const d = new Date(normalized)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const hm = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(d)
  if (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  ) {
    return hm
  }
  const sameYear = d.getFullYear() === now.getFullYear()
  const date = new Intl.DateTimeFormat(
    'zh-CN',
    sameYear
      ? { month: 'numeric', day: 'numeric' }
      : { year: 'numeric', month: 'numeric', day: 'numeric' },
  ).format(d)
  return `${date} ${hm}`
}

function versionStamp(v: { version_type?: string; created_at?: string | null }) {
  const type = versionLabel(String(v?.version_type || ''))
  const time = versionTime(v?.created_at)
  return time ? `${type} · ${time}` : type
}

function versionById(id: number | null) {
  if (id == null) return null
  return versions.value.find((v) => v.id === id) || null
}

/** 简易按行 diff（Myers 子集：LCS 回溯），足够章节对照。 */
function lineDiff(aText: string, bText: string) {
  const a = (aText || '').split('\n')
  const b = (bText || '').split('\n')
  const n = a.length
  const m = b.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const rows: { type: 'same' | 'del' | 'add'; text: string }[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ type: 'same', text: a[i] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: 'del', text: a[i++] })
    } else {
      rows.push({ type: 'add', text: b[j++] })
    }
  }
  while (i < n) rows.push({ type: 'del', text: a[i++] })
  while (j < m) rows.push({ type: 'add', text: b[j++] })
  return rows
}

const compareRows = computed(() => {
  const left = versionById(compareA.value)
  const right = versionById(compareB.value)
  if (!left || !right) return []
  return lineDiff(String(left.content || ''), String(right.content || ''))
})

function openCompare() {
  if (versions.value.length < 2) return
  compareOpen.value = true
  const ids = versions.value.map((v) => v.id as number)
  compareA.value = activeVersionId.value && ids.includes(activeVersionId.value)
    ? activeVersionId.value
    : ids[0]
  compareB.value = ids.find((id) => id !== compareA.value) ?? ids[ids.length - 1]
}

function severityClass(s: string) {
  const v = (s || '').toLowerCase()
  if (v === 'error' || v === 'high' || v === 'critical') return 'sev sev--error'
  if (v === 'warning' || v === 'warn' || v === 'medium') return 'sev sev--warn'
  return 'sev sev--info'
}

function severityLabel(s: string) {
  const v = (s || '').toLowerCase()
  if (v === 'error' || v === 'high' || v === 'critical') return '严重'
  if (v === 'warning' || v === 'warn' || v === 'medium') return '警告'
  return '提示'
}

function clearIdleWatch() {
  if (idleTimer != null) {
    clearTimeout(idleTimer)
    idleTimer = null
  }
}

function streamUrl(attach: boolean) {
  if (!selected.value) return ''
  const params = new URLSearchParams({
    outline_item_id: String(selected.value.id),
    run_critic: String(runCritic.value),
    max_critic_rounds: String(runCritic.value ? (willSegment.value ? 0 : maxCriticRounds.value) : 0),
  })
  const n = Number(targetChars.value)
  if (Number.isFinite(n) && n >= 500) params.set('target_chars', String(Math.round(n)))
  if (attach) {
    params.set('attach', '1')
    if (lastEventId > 0) params.set('after', String(lastEventId))
  }
  return `/api/novels/${novelId}/generate/stream?${params}`
}

function armIdleWatch() {
  clearIdleWatch()
  idleTimer = setTimeout(() => {
    if (!streaming.value) return
    // 服务端还在写。关掉编辑器会让用户改到一半的稿被后写的正文盖掉。
    status.value = '连接断了，正在接上已写的内容'
    openGenerateStream(streamEpoch, true)
  }, IDLE_TIMEOUT_MS)
}

function openGenerateStream(epoch: number, attach: boolean) {
  const url = streamUrl(attach)
  if (!url) return
  es?.close()
  const source = new EventSource(url)
  es = source
  armIdleWatch()
  source.onmessage = async (ev) => {
    if (epoch !== streamEpoch || source !== es) return
    const id = Number(ev.lastEventId)
    if (Number.isFinite(id) && id > lastEventId) lastEventId = id
    armIdleWatch()
    let data: any
    try {
      data = JSON.parse(ev.data)
    } catch {
      return
    }
    if (data.event === 'ping') return
    if (data.event === 'status' || data.event === 'segment') {
      status.value = data.message || status.value
      if (data.chapter_id) chapterId.value = data.chapter_id
      if (data.event === 'segment') return
    }
    if (data.event === 'delta') stream.append(data.text || '')
    if (data.event === 'error' && data.draft_saved) {
      clearIdleWatch()
      streaming.value = false
      source.close()
      if (es === source) es = null
      const note = data.message || '已写完的段落还在，可以接着改。'
      if (selected.value) await loadChapterForItem(selected.value)
      if (epoch !== streamEpoch) return
      status.value = note
      error.value = ''
      return
    }
    if (data.event === 'error') {
      const raw = data.message || '生成失败'
      const friendly =
        /UNIQUE constraint failed:\s*chapters\.novel_id,\s*chapters\.index/i.test(raw)
          ? '这一章已经有正文。刷新后再生成，会盖掉现有草稿。'
          : raw
      stopStream(friendly)
      return
    }
    if (data.event === 'done') {
      clearIdleWatch()
      stream.sync()
      content.value = data.content || stream.read()
      stream.clearDom()
      consistency.value = data.consistency
      qualityHints.value = data.quality?.hints || []
      syncIssueSelection(data.consistency?.issues)
      clearPreview()
      chapterId.value = data.chapter_id
      activeVersionId.value = data.version_id ?? null
      streaming.value = false
      writebackToken.value += 1
      status.value = data.overwritten ? '完成（已覆盖已有章节）' : '完成'
      source.close()
      if (es === source) es = null
      await load()
      if (epoch !== streamEpoch) return
      if (chapterId.value) {
        const { data: vers } = await novelsApi.versions(novelId, chapterId.value)
        if (epoch !== streamEpoch) return
        applyLatestVersion(vers)
        if (data.content) content.value = data.content
      }
    }
  }
  source.onerror = () => {
    // 正常结束也会触发 error。还在写就交给浏览器按 Last-Event-ID 接上，不把断线当成失败。
    if (epoch !== streamEpoch || source !== es) return
    if (!streaming.value) {
      clearIdleWatch()
      source.close()
      es = null
      return
    }
    status.value = '连接断了，正在接上已写的内容'
    armIdleWatch()
  }
}

function stopStream(msg?: string) {
  invalidateLoadsAndStreams()
  clearIdleWatch()
  stream.sync()
  content.value = stream.read()
  streaming.value = false
  if (msg) {
    error.value = msg
    status.value = '已中断'
  }
  es?.close()
  es = null
}

function closeReviseEs() {
  reviseEs?.close()
  reviseEs = null
}

function clearEditor() {
  content.value = ''
  stream.reset('')
  stream.clearDom()
  consistency.value = null
  qualityHints.value = []
  chapterId.value = null
  writebackToken.value = 0
  versions.value = []
  activeVersionId.value = null
  reviseProgress.value = 0
  reviseMessage.value = ''
  reviseError.value = ''
  reviseFailed.value = false
  selectedIssueKeys.value = new Set()
  clearPreview()
}

function applyVersion(v: any) {
  content.value = v?.content ?? ''
  consistency.value = v?.consistency_report ?? null
  syncIssueSelection(consistency.value?.issues)
  clearPreview()
  activeVersionId.value = v?.id ?? null
}

function applyLatestVersion(vers: any[]) {
  versions.value = vers
  if (!vers.length) {
    consistency.value = null
    activeVersionId.value = null
    selectedIssueKeys.value = new Set()
    clearPreview()
    return
  }
  applyVersion(vers[vers.length - 1])
}

async function previewSelectedRevise() {
  if (!chapterId.value || previewBusy.value || confirmBusy.value) return
  const issues = issueRows.value
    .filter((r: { key: string }) => selectedIssueKeys.value.has(r.key))
    .map((r: { iss: any }) => r.iss)
  if (!issues.length) {
    previewError.value = '请先勾选要处理的问题'
    return
  }
  previewBusy.value = true
  previewError.value = ''
  try {
    const { data } = await novelsApi.criticSelectRevise(novelId, chapterId.value, {
      content: content.value,
      issues,
      confirm: false,
    })
    previewBase.value = data.base_content
    previewRevised.value = data.revised_content
    if (!data.changed) previewError.value = '正文没有改。这一章可能太长，没有整章重写。'
  } catch (e: any) {
    previewError.value = apiErrorDetail(e, '预览修稿失败')
  } finally {
    previewBusy.value = false
  }
}

async function confirmSelectedRevise() {
  if (!chapterId.value || !previewRevised.value || confirmBusy.value) return
  const issues = issueRows.value
    .filter((r: { key: string }) => selectedIssueKeys.value.has(r.key))
    .map((r: { iss: any }) => r.iss)
  if (!issues.length) return
  confirmBusy.value = true
  previewError.value = ''
  try {
    const { data } = await novelsApi.criticSelectRevise(novelId, chapterId.value, {
      content: previewBase.value || content.value,
      issues,
      confirm: true,
      commit_to_knowledge: false,
    })
    content.value = data.revised_content
    if (data.consistency) consistency.value = data.consistency
    syncIssueSelection(consistency.value?.issues)
    clearPreview()
    status.value = '修改已写入这一版，还没入库。要入库再点「保存修订并入库」。'
    const { data: vers } = await novelsApi.versions(novelId, chapterId.value)
    applyLatestVersion(vers)
    if (data.revised_content) content.value = data.revised_content
  } catch (e: any) {
    previewError.value = apiErrorDetail(e, '写入修改失败')
  } finally {
    confirmBusy.value = false
  }
}

function apiErrorDetail(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d: any) => (typeof d === 'string' ? d : d?.msg || JSON.stringify(d)))
      .join('；')
  }
  if (detail != null && typeof detail === 'object') {
    try {
      return JSON.stringify(detail)
    } catch {
      /* ignore */
    }
  }
  return e?.message || fallback
}

async function loadChapterForItem(item: OutlineItem | null) {
  if (!item || streaming.value) return
  const seq = ++loadSeq
  clearEditor()
  status.value = '加载已有章节…'
  error.value = ''
  try {
    const { data: ch } = await novelsApi.chapterByOutlineItem(novelId, item.id)
    if (seq !== loadSeq) return
    content.value = ch.content || ''
    chapterId.value = ch.id
    status.value = `已加载第 ${ch.index} 章`
    const { data: vers } = await novelsApi.versions(novelId, ch.id)
    if (seq !== loadSeq) return
    // 正文以章节表为准；报告取最新版本（不跨版本沿用旧报告）
    applyLatestVersion(vers)
    content.value = ch.content || ''
    await loadQuality(ch.id, seq)
  } catch (e: any) {
    if (seq !== loadSeq) return
    // 404：该条目尚未生成 — 正常空编辑器，不算错误
    const code = e?.response?.status
    if (code === 404) {
      status.value = ''
      return
    }
    error.value = apiErrorDetail(e, '加载已有章节失败')
    status.value = ''
  }
}

async function selectItem(item: OutlineItem) {
  if (streaming.value) return
  writebackToken.value = 0
  selected.value = item
  ui.setSelectedItem(novelId, item.id)
  await loadChapterForItem(item)
}

async function loadNovelMeta() {
  try {
    const { data } = await novelsApi.get(novelId)
    novelMeta.value = data
    const med = Number(data.median_chapter_chars || data.avg_chapter_chars || 0)
    if (!targetTouched.value && med > 0) {
      targetChars.value = med
    }
  } catch {
    /* 均长展示失败不阻断续写 */
  } finally {
    novelLoaded.value = true
  }
}

async function load() {
  await loadNovelMeta()
  if (isReference.value) return
  try {
    const { data } = await outlineApi.list(novelId)
    outlines.value = data
    const remembered = ui.getSelectedItem(novelId)
    const prevItemId = selected.value?.id ?? remembered
    outline.value = data.find((o) => o.status === 'confirmed') || data[0] || null
    const items = outline.value?.items || []
    selected.value =
      items.find((i) => i.id === prevItemId) || pendingItems.value[0] || items[0] || null
    if (selected.value) ui.setSelectedItem(novelId, selected.value.id)
    // keep-alive 再进入时：若已有正文/流式内容且选中未变，不要清空编辑器
    const keepLocal =
      bootstrapped.value &&
      !!selected.value &&
      selected.value.id === prevItemId &&
      (!!content.value || streaming.value)
    if (!keepLocal) await loadChapterForItem(selected.value)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '大纲加载失败'
  } finally {
    planReady.value = true
    bootstrapped.value = true
  }
}

async function startGenerate() {
  if (isReference.value || !selected.value) return
  invalidateLoadsAndStreams()
  const epoch = streamEpoch
  streaming.value = true
  status.value = '连接中…'
  content.value = ''
  consistency.value = null
  qualityHints.value = []
  writebackToken.value = 0
  chapterId.value = null
  versions.value = []
  activeVersionId.value = null
  error.value = ''
  lastEventId = 0
  es?.close()
  await nextTick()
  stream.reset('')
  openGenerateStream(epoch, false)
}

async function saveRevise() {
  if (!chapterId.value || revising.value || streaming.value) return
  revising.value = true
  reviseFailed.value = false
  reviseError.value = ''
  reviseProgress.value = 2
  reviseMessage.value = '保存修订…'
  error.value = ''
  status.value = '正在保存修订…'
  try {
    const { data } = await novelsApi.revise(novelId, chapterId.value, content.value, true)
    const { data: vers } = await novelsApi.versions(novelId, chapterId.value)
    applyLatestVersion(vers)
    if (data.task_id) {
      reviseMessage.value = '修订已保存，开始入库…'
      reviseProgress.value = 5
      watchReviseTask(data.task_id)
    } else {
      revising.value = false
      reviseProgress.value = 100
      reviseMessage.value = '已保存修订'
      status.value = '已保存修订'
    }
  } catch (e: any) {
    revising.value = false
    reviseFailed.value = true
    reviseError.value = e?.response?.data?.detail || e?.message || '保存修订失败'
    status.value = '保存失败'
  }
}

/** 入库失败后仅重新入队知识库更新，不重复创建 user_edited 版本 */
async function retryCommitKnowledge() {
  if (!chapterId.value || revising.value || streaming.value) return
  revising.value = true
  reviseFailed.value = false
  reviseError.value = ''
  reviseProgress.value = 2
  reviseMessage.value = '重新入队入库…'
  error.value = ''
  status.value = '正在重试入库…'
  try {
    const { data } = await novelsApi.commitKnowledge(novelId, chapterId.value)
    reviseMessage.value = '已重新入队，开始入库…'
    reviseProgress.value = 5
    watchReviseTask(data.task_id)
  } catch (e: any) {
    revising.value = false
    reviseFailed.value = true
    reviseError.value = e?.response?.data?.detail || e?.message || '重试入库失败'
    status.value = '入库失败'
  }
}

function watchReviseTask(taskId: number) {
  closeReviseEs()
  reviseEs = new EventSource(`/api/tasks/${taskId}/events`)
  reviseEs.onmessage = (ev) => {
    try {
      const task = JSON.parse(ev.data)
      reviseProgress.value = Number(task.progress) || 0
      reviseMessage.value = task.message || ''
      if (task.status === 'completed') {
        revising.value = false
        reviseFailed.value = false
        reviseProgress.value = 100
        reviseMessage.value = '入库完成'
        status.value = '已入库并更新知识库'
        writebackReload.value += 1
        closeReviseEs()
        return
      }
      if (task.status === 'failed') {
        revising.value = false
        reviseFailed.value = true
        reviseError.value = task.error || '入库失败'
        status.value = '入库失败'
        closeReviseEs()
      }
    } catch {
      /* ignore parse errors */
    }
  }
  reviseEs.onerror = async () => {
    try {
      const { data: task } = await tasksApi.get(taskId)
      reviseProgress.value = Number(task.progress) || 0
      reviseMessage.value = task.message || ''
      if (task.status === 'completed') {
        revising.value = false
        reviseFailed.value = false
        reviseProgress.value = 100
        reviseMessage.value = '入库完成'
        status.value = '已入库并更新知识库'
        writebackReload.value += 1
        closeReviseEs()
        return
      }
      if (task.status === 'failed') {
        revising.value = false
        reviseFailed.value = true
        reviseError.value = task.error || '入库失败'
        status.value = '入库失败'
        closeReviseEs()
        return
      }
      // 仍在运行：保持 SSE，等待后续事件；避免静默挂起
      if (!revising.value) {
        revising.value = true
      }
    } catch (e: any) {
      revising.value = false
      reviseFailed.value = true
      reviseError.value = e?.message || '入库进度连接中断，请重试'
      status.value = '入库失败'
      closeReviseEs()
    }
  }
}

function loadVersion(v: any) {
  applyVersion(v)
  status.value = `已切换到${versionStamp(v)}`
}

async function deleteCurrentVersion() {
  if (!chapterId.value || activeVersionId.value == null || streaming.value || deleting.value) return
  const ok = window.confirm(
    '确定删除当前选中版本？若该版本是正文所对应的版本，将回退到剩余最新一版；若已是最后一版，将清除整章并可重新生成。',
  )
  if (!ok) return
  deleting.value = true
  error.value = ''
  try {
    const { data } = await novelsApi.removeChapterVersion(
      novelId,
      chapterId.value,
      activeVersionId.value,
    )
    if (data.chapter_deleted) {
      clearEditor()
      status.value = '已删除最后一版，章节已清除'
      await load()
      return
    }
    const { data: vers } = await novelsApi.versions(novelId, chapterId.value)
    applyLatestVersion(vers)
    if (data.content_rolled_back && data.active_content != null) {
      content.value = data.active_content
    }
    status.value = data.message || '版本已删除'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '删除版本失败'
  } finally {
    deleting.value = false
  }
}

async function deleteWholeChapter() {
  if (!chapterId.value || streaming.value || deletingChapter.value) return
  const ok = window.confirm(
    '确定删除整章及全部版本？将清除版本链、摘要与向量，大纲条目会保留并可重新生成。此操作不可恢复。Story Bible 不会回滚。',
  )
  if (!ok) return
  deletingChapter.value = true
  error.value = ''
  try {
    await novelsApi.removeChapter(novelId, chapterId.value)
    clearEditor()
    status.value = '本章及全部版本已删除'
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '删除失败'
  } finally {
    deletingChapter.value = false
  }
}

watch(chapterIndex, (index) => {
  void loadOpenThreads(index)
})
onMounted(() => {
  loadDismissed()
  void load()
})
onActivated(() => {
  if (streaming.value) {
    armIdleWatch()
    return
  }
  // 切回续写：刷新大纲状态，但尽量保留当前编辑区内容
  if (bootstrapped.value) void load()
})
onDeactivated(() => {
  // KeepAlive：离开标签时不断开生成 SSE。停掉空闲计时，避免后台误判超时。
  clearIdleWatch()
  closeReviseEs()
})
onUnmounted(() => {
  invalidateLoadsAndStreams()
  clearIdleWatch()
  es?.close()
  closeReviseEs()
})
</script>

<template>
  <div v-if="!novelLoaded || (!isReference && !planReady)" class="skeleton h-40" aria-busy="true" />
  <div v-else-if="isReference" class="panel p-8 max-w-xl">
    <div class="kicker mb-2">参考</div>
    <h2 class="font-display text-2xl">不会进入续写</h2>
    <p class="page-desc mt-2">
      这是参考小说。章节只用来拆文风和设定，不会变成可续写正文，也不能导出成书。
    </p>
    <RouterLink class="btn mt-5" :to="`/novels/${novelId}/bible`">查看拆解</RouterLink>
  </div>
  <div v-else-if="!hasWritePlan">
    <p v-if="error" class="alert alert--danger">{{ error }}</p>
    <EmptyState
      :title="isScratch ? '开篇还没写出来' : noChapters ? '还没有章节' : '还没有可写的下一章'"
      :body="
        isScratch
          ? '这是从零开书，不走导入。回到开书，用前提播种设定并写出开篇。'
          : noChapters
            ? '这本书还是空的。先生成大纲再写第一章；若已有原文，回到导入。'
            : '原文已经入库。生成并确认大纲后，才能从这里续写下一章。'
      "
      primary="去生成大纲"
      :primary-to="`/novels/${novelId}/outline`"
      :secondary="isScratch ? '回到开书' : noChapters ? '导入原文' : undefined"
      :secondary-to="isScratch ? `/create?novel=${novelId}` : '/import'"
    />
  </div>
  <div v-else class="wb-write">
    <aside class="wb-rail" aria-label="大纲条目">
      <div class="wb-rail__head">
        <span>章节</span>
        <span v-if="outline?.items?.length" class="tabular">{{ doneCount }}/{{ outline.items.length }}</span>
      </div>
      <button
        v-for="item in outline?.items || []"
        :key="item.id"
        type="button"
        class="wb-rail__item"
        :class="{ 'is-active': selected?.id === item.id }"
        :disabled="streaming || reviseBusy"
        @click="selectItem(item)"
      >
        <span class="wb-rail__ord tabular">{{ item.order }}</span>
        <span class="wb-rail__name">{{ item.title }}</span>
        <span class="wb-rail__state" :data-status="item.status">{{ itemStatusLabel(item.status) }}</span>
      </button>
      <p v-if="!outline" class="wb-rail__empty">请先在大纲页生成并确认。</p>
    </aside>

    <section class="wb-stage">
      <ol class="wb-steps" aria-label="续写流程">
        <li :class="{ 'is-current': writePhase === 0, 'is-done': writePhase > 0 }">选章</li>
        <li :class="{ 'is-current': writePhase === 1, 'is-done': writePhase > 1 }">生成</li>
        <li :class="{ 'is-current': writePhase === 2, 'is-done': writePhase > 2 }">审阅</li>
        <li :class="{ 'is-current': writePhase === 3 && !committed, 'is-done': committed }">入库</li>
      </ol>

      <header :key="selected?.id ?? 0" class="wb-stage__head">
        <div class="min-w-0">
          <p v-if="selected" class="wb-kicker">
            <span v-if="chapterIndex">第 {{ chapterIndex }} 章</span>
            <span aria-hidden="true"> · </span>
            {{ itemStatusLabel(selected.status) }}
          </p>
          <h2 class="wb-title">{{ selected?.title || '选择一章开始' }}</h2>
          <p v-if="selected?.summary" class="wb-lede">{{ selected.summary }}</p>
        </div>
        <p class="wb-count tabular">
          <strong>{{ displayChars || 0 }}</strong>
          <span>字</span>
          <span v-if="status" class="wb-count__status">{{ status }}</span>
        </p>
      </header>

      <section class="wb-memory" aria-label="未回收线索">
        <div class="wb-critic__head">
          <h3>未回收线索</h3>
          <RouterLink class="meta" :to="`/novels/${novelId}/bible`">在设定里改</RouterLink>
        </div>
        <ul v-if="shownThreads.length">
          <li v-for="thread in shownThreads" :key="thread.id" :data-due="thread.due || 'open'">
            <span class="wb-memory__title">{{ thread.title }}</span>
            <span class="meta">{{ thread.thread_type }}</span>
            <span class="wb-memory__note">{{ thread.note }}</span>
          </li>
        </ul>
        <p v-else class="meta">这条线上还没有未回收的伏笔。</p>
        <p v-if="hiddenThreadCount" class="meta">另有 {{ hiddenThreadCount }} 条</p>
      </section>

      <div class="wb-actions">
        <button class="btn" type="button" :disabled="!selected || streaming || reviseBusy" @click="startGenerate">
          {{ streaming ? '生成中…' : error ? '重试生成' : '生成本章' }}
        </button>
        <button
          class="btn-ghost"
          type="button"
          :disabled="!chapterId || streaming || reviseBusy"
          @click="reviseFailed ? retryCommitKnowledge() : saveRevise()"
        >
          {{ revising ? '入库中…' : reviseFailed ? '重试入库' : '保存修订并入库' }}
        </button>
        <details class="quiet-menu">
          <summary class="quiet-menu__sum">删除</summary>
          <div class="quiet-menu__panel">
            <button
              class="quiet-menu__item quiet-menu__item--danger"
              type="button"
              :disabled="!chapterId || activeVersionId == null || streaming || deleting || deletingChapter || reviseBusy"
              @click="deleteCurrentVersion"
            >
              {{ deleting ? '删除中…' : '删除当前版本' }}
            </button>
            <button
              class="quiet-menu__item quiet-menu__item--danger"
              type="button"
              :disabled="!chapterId || streaming || deleting || deletingChapter || reviseBusy"
              title="清除整章及全部版本，大纲条目会保留"
              @click="deleteWholeChapter"
            >
              {{ deletingChapter ? '删除中…' : '删除整章及全部版本' }}
            </button>
          </div>
        </details>
      </div>

      <details class="wb-tune">
        <summary class="wb-tune__sum">
          篇幅与审阅
          <span class="meta tabular">{{ tuneSummary }}</span>
        </summary>
        <div class="wb-tune__fields">
        <div>
          <label class="label" for="write-target-chars">本章目标字数</label>
          <input
            id="write-target-chars"
            v-model.number="targetChars"
            type="number"
            min="1500"
            max="30000"
            step="100"
            class="input wb-tune__num"
            :disabled="streaming || reviseBusy"
            @input="onTargetCharsInput"
          />
        </div>
        <p class="meta wb-tune__note">
          <template v-if="isScratch">开书默认约 3000 字</template>
          <template v-else>
            原作均长
            <span v-if="originalAvgChars">约 {{ originalAvgChars }} 字</span>
            <span v-else>尚未统计</span>
          </template>
          <span v-if="willSegment"> · 长章按要点分段，只审查不整章重写</span>
        </p>
        <label class="check">
          <input v-model="runCritic" type="checkbox" :disabled="streaming || reviseBusy" />
          一致性检验
        </label>
        <div v-if="runCritic">
          <label class="label" for="write-critic-rounds">Critic 轮数</label>
          <select
            id="write-critic-rounds"
            v-model.number="maxCriticRounds"
            class="input wb-tune__rounds"
            :disabled="streaming || reviseBusy || willSegment"
          >
            <option :value="0">0（仅审查）</option>
            <option :value="1">1</option>
            <option :value="2">2</option>
          </select>
        </div>
        </div>
      </details>

      <div v-if="revising || reviseFailed || reviseProgress > 0" class="wb-progress">
        <div class="wb-progress__row">
          <span>入库 · 摘要、抽取、向量、记忆</span>
          <span class="tabular">
            {{ Math.round(reviseProgress) }}%
            {{ reviseFailed ? '失败' : revising ? '进行中' : '完成' }}
          </span>
        </div>
        <ProgressBar :value="reviseProgress" :failed="reviseFailed" />
        <p v-if="reviseMessage" class="meta">{{ reviseMessage }}</p>
        <p v-if="reviseError" class="alert alert--danger">{{ reviseError }}</p>
      </div>

      <p v-if="error" class="alert alert--danger">{{ error }}</p>

      <div class="editor-frame wb-manuscript" :class="{ 'is-live': streaming }">
        <div class="editor-chrome">
          <span class="wb-manuscript__label">正文</span>
          <div v-if="versions.length" class="wb-versions" role="group" aria-label="版本">
            <button
              v-for="v in versions"
              :key="v.id"
              type="button"
              class="wb-version"
              :class="{ 'is-active': activeVersionId === v.id }"
              :aria-pressed="activeVersionId === v.id"
              :title="`版本 #${v.id} ${versionStamp(v)}`"
              :disabled="reviseBusy"
              @click="loadVersion(v)"
            >
              <span>{{ versionLabel(v.version_type) }}</span>
              <time
                v-if="versionTime(v.created_at)"
                class="wb-version__time"
                :datetime="v.created_at"
              >{{ versionTime(v.created_at) }}</time>
            </button>
            <button
              v-if="versions.length >= 2"
              type="button"
              class="btn-ghost btn-sm"
              :disabled="reviseBusy"
              @click="openCompare"
            >
              对照
            </button>
          </div>
          <span class="meta tabular">{{ displayChars ? `${displayChars} 字` : '还是空的' }}</span>
        </div>
        <div :key="selected?.id ?? 0" class="wb-manuscript__body">
          <div
            v-show="streaming"
            ref="streamEl"
            class="prose-body"
            aria-live="polite"
            aria-busy="true"
          />
          <textarea
            v-show="!streaming"
            v-model="content"
            class="prose-edit"
            placeholder="生成的正文会出现在这里，可以直接改。"
            :disabled="reviseBusy"
          />
        </div>
        <div v-if="compareOpen && versions.length >= 2" class="wb-diff" aria-label="版本对照">
          <div class="wb-diff__bar">
            <label class="wb-diff__pick">
              左
              <select v-model.number="compareA">
                <option v-for="v in versions" :key="`a-${v.id}`" :value="v.id">
                  #{{ v.id }} {{ versionStamp(v) }}
                </option>
              </select>
            </label>
            <label class="wb-diff__pick">
              右
              <select v-model.number="compareB">
                <option v-for="v in versions" :key="`b-${v.id}`" :value="v.id">
                  #{{ v.id }} {{ versionStamp(v) }}
                </option>
              </select>
            </label>
            <button type="button" class="btn-ghost btn-sm" @click="compareOpen = false">关闭</button>
          </div>
          <pre class="wb-diff__body" tabindex="0"><span
              v-for="(row, idx) in compareRows"
              :key="idx"
              class="wb-diff__line"
              :class="`wb-diff__line--${row.type}`"
            >{{ row.text || ' ' }}
</span></pre>
        </div>
      </div>

      <details v-if="selected && hasBrief" class="wb-brief">
        <summary>本章要点</summary>
        <dl>
          <div v-if="selected.purpose">
            <dt>目标</dt>
            <dd>{{ selected.purpose }}</dd>
          </div>
          <div v-if="selected.conflict">
            <dt>冲突</dt>
            <dd>{{ selected.conflict }}</dd>
          </div>
          <div v-if="selected.suspense_hook">
            <dt>悬念</dt>
            <dd>{{ selected.suspense_hook }}</dd>
          </div>
          <div v-if="(selected.characters || []).length">
            <dt>出场</dt>
            <dd>{{ (selected.characters || []).join('、') }}</dd>
          </div>
          <div v-if="(selected.key_points || []).length">
            <dt>要点</dt>
            <dd>
              <ol>
                <li v-for="(point, i) in selected.key_points || []" :key="i">{{ point }}</li>
              </ol>
            </dd>
          </div>
        </dl>
      </details>

      <WritebackReview
        v-if="chapterId && !streaming"
        :novel-id="novelId"
        :chapter-id="chapterId"
        :propose-token="writebackToken"
        :reload-token="writebackReload"
      />

      <section v-if="deskHints.length" class="wb-hints" aria-label="写作提示">
        <div class="wb-critic__head">
          <h3>写作提示</h3>
          <span class="meta">文风对照已保存的样本。篇幅和章末钩子会让连续生成停下。</span>
        </div>
        <ul>
          <li v-for="hint in deskHints" :key="hint.id">
            <span :class="severityClass(hint.severity)">{{ severityLabel(hint.severity) }}</span>
            <span>{{ hint.message }}</span>
            <button
              v-if="hint.severity !== 'error'"
              type="button"
              class="btn-ghost btn-sm"
              @click="dismissHint(hint)"
            >
              忽略
            </button>
          </li>
        </ul>
      </section>

      <section v-if="consistency" class="wb-critic" aria-label="一致性审阅">
        <div class="wb-critic__head">
          <h3>审阅</h3>
          <span class="badge" :class="consistency.ok ? 'badge--ok' : 'badge--danger'">
            {{ consistency.ok ? '通过' : '有问题' }}
          </span>
          <span class="meta">Critic {{ consistency.critic_rounds || 0 }} 轮 · 勾选后预览，确认才写入</span>
        </div>
        <div v-if="issueRows.length" class="wb-critic__tools">
          <button type="button" class="btn-ghost btn-sm" :disabled="reviseBusy" @click="selectAllIssues">
            全选
          </button>
          <button type="button" class="btn-ghost btn-sm" :disabled="reviseBusy" @click="clearIssueSelection">
            清空
          </button>
          <button
            type="button"
            class="btn btn-sm"
            :disabled="reviseBusy || !selectedIssueCount || !chapterId"
            @click="previewSelectedRevise"
          >
            {{ previewBusy ? '预览中…' : `预览修稿（${selectedIssueCount}）` }}
          </button>
        </div>
        <ul class="wb-issues">
          <li v-for="row in issueRows" :key="row.key">
            <input
              type="checkbox"
              :checked="selectedIssueKeys.has(row.key)"
              :disabled="reviseBusy"
              :aria-label="`${severityLabel(row.iss.severity)} ${row.iss.type}`"
              @change="toggleIssue(row.key, ($event.target as HTMLInputElement).checked)"
            />
            <span :class="severityClass(row.iss.severity)" :title="row.iss.severity">{{
              severityLabel(row.iss.severity)
            }}</span>
            <span>
              <span class="meta">{{ row.iss.type }}</span>
              — {{ row.iss.message }}
            </span>
          </li>
          <li v-if="!issueRows.length" class="empty">无问题</li>
        </ul>
        <p v-if="previewError" class="alert alert--danger">{{ previewError }}</p>
        <div v-if="previewRevised" class="wb-diff">
          <div>
            <div class="wb-diff__label">修稿前</div>
            <pre class="wb-diff__text">{{ previewBase }}</pre>
          </div>
          <div class="wb-diff__col--next">
            <div class="wb-diff__label">修稿后</div>
            <pre class="wb-diff__text">{{ previewRevised }}</pre>
          </div>
          <div class="wb-diff__actions">
            <button type="button" class="btn" :disabled="reviseBusy" @click="confirmSelectedRevise">
              {{ confirmBusy ? '写入中…' : '写入这版修改' }}
            </button>
            <button type="button" class="btn-ghost" :disabled="reviseBusy" @click="clearPreview">放弃预览</button>
          </div>
        </div>
      </section>
      <section v-else-if="showNoReportHint" class="wb-critic" aria-label="一致性审阅">
        <div class="wb-critic__head">
          <h3>审阅</h3>
        </div>
        <p class="empty">这一版没有检查报告</p>
        <p class="meta">生成时关了检查，或者报告在后面的修订版上。</p>
      </section>
    </section>
  </div>
</template>
