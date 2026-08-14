<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { novelsApi, outlineApi, tasksApi, type Novel, type Outline, type OutlineItem } from '@/api'
import ProgressBar from '@/components/ProgressBar.vue'
import { useRafText } from '@/composables/useRafText'

/** 超过此时长无任何 SSE 事件（含 ping）则判定卡死；应 > 2× 后端心跳间隔 */
const IDLE_TIMEOUT_MS = 45_000

const route = useRoute()
const novelId = Number(route.params.id)
const outlines = ref<Outline[]>([])
const outline = ref<Outline | null>(null)
const selected = ref<OutlineItem | null>(null)
const streaming = ref(false)
const status = ref('')
const content = ref('')
const consistency = ref<any>(null)
const chapterId = ref<number | null>(null)
const versions = ref<any[]>([])
const activeVersionId = ref<number | null>(null)
const error = ref('')
const deleting = ref(false)
const deletingChapter = ref(false)
/** 修订入库进度 */
const revising = ref(false)
const reviseProgress = ref(0)
const reviseMessage = ref('')
const reviseError = ref('')
const reviseFailed = ref(false)
/** 一致性检验 / Critic：默认开启 + 2 轮（与后端 Query 默认一致） */
const runCritic = ref(true)
const maxCriticRounds = ref(2)
const novelMeta = ref<Novel | null>(null)
/** 用户可覆盖的本章目标字数 */
const targetChars = ref(3000)
const targetTouched = ref(false)
const SEGMENT_HINT = 4500
let es: EventSource | null = null
let reviseEs: EventSource | null = null
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

const reviseBusy = computed(() => revising.value)

const originalAvgChars = computed(() => {
  const n = novelMeta.value
  if (!n) return 0
  return Number(n.median_chapter_chars || n.avg_chapter_chars || 0)
})

const willSegment = computed(() => Number(targetChars.value) > SEGMENT_HINT)

const displayChars = computed(() => (streaming.value ? stream.length.value : content.value.length))

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
  if (t === 'critic_revised') return 'Critic'
  if (t === 'user_edited') return '修订'
  return t
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

function armIdleWatch() {
  clearIdleWatch()
  idleTimer = setTimeout(() => {
    if (!streaming.value) return
    stopStream('生成超时：长时间无响应，连接可能已断开，请重试')
  }, IDLE_TIMEOUT_MS)
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
  chapterId.value = null
  versions.value = []
  activeVersionId.value = null
  reviseProgress.value = 0
  reviseMessage.value = ''
  reviseError.value = ''
  reviseFailed.value = false
}

function applyVersion(v: any) {
  content.value = v?.content ?? ''
  consistency.value = v?.consistency_report ?? null
  activeVersionId.value = v?.id ?? null
}

function applyLatestVersion(vers: any[]) {
  versions.value = vers
  if (!vers.length) {
    consistency.value = null
    activeVersionId.value = null
    return
  }
  applyVersion(vers[vers.length - 1])
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
  selected.value = item
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
  }
}

async function load() {
  await loadNovelMeta()
  const { data } = await outlineApi.list(novelId)
  outlines.value = data
  const prevItemId = selected.value?.id
  outline.value = data.find((o) => o.status === 'confirmed') || data[0] || null
  const items = outline.value?.items || []
  selected.value =
    items.find((i) => i.id === prevItemId) || pendingItems.value[0] || items[0] || null
  await loadChapterForItem(selected.value)
}

async function startGenerate() {
  if (!selected.value) return
  invalidateLoadsAndStreams()
  const epoch = streamEpoch
  streaming.value = true
  status.value = '连接中…'
  content.value = ''
  consistency.value = null
  chapterId.value = null
  versions.value = []
  activeVersionId.value = null
  error.value = ''
  es?.close()
  await nextTick()
  stream.reset('')
  const params = new URLSearchParams({
    outline_item_id: String(selected.value.id),
    run_critic: String(runCritic.value),
    max_critic_rounds: String(runCritic.value ? (willSegment.value ? 0 : maxCriticRounds.value) : 0),
  })
  const n = Number(targetChars.value)
  if (Number.isFinite(n) && n >= 500) {
    params.set('target_chars', String(Math.round(n)))
  }
  const url = `/api/novels/${novelId}/generate/stream?${params}`
  es = new EventSource(url)
  armIdleWatch()
  es.onmessage = async (ev) => {
    if (epoch !== streamEpoch) return
    armIdleWatch()
    let data: any
    try {
      data = JSON.parse(ev.data)
    } catch {
      return
    }
    if (data.event === 'ping') return
    if (data.event === 'status') status.value = data.message || ''
    if (data.event === 'delta') stream.append(data.text || '')
    if (data.event === 'error') {
      const raw = data.message || '生成失败'
      const friendly =
        /UNIQUE constraint failed:\s*chapters\.novel_id,\s*chapters\.index/i.test(raw)
          ? '该章节已存在。请刷新后重试生成（系统会覆盖已有草稿）。'
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
      chapterId.value = data.chapter_id
      activeVersionId.value = data.version_id ?? null
      streaming.value = false
      status.value = data.overwritten ? '完成（已覆盖已有章节）' : '完成'
      es?.close()
      es = null
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
  es.onerror = () => {
    // EventSource 在服务端正常结束后也可能触发；仅在仍 streaming 时视为异常
    if (streaming.value) {
      stopStream('SSE 连接中断，请重试')
    } else {
      clearIdleWatch()
      es?.close()
      es = null
    }
  }
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
  status.value = `已切换到版本 #${v.id}（${versionLabel(v.version_type)}）`
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

onMounted(load)
onUnmounted(() => {
  invalidateLoadsAndStreams()
  clearIdleWatch()
  es?.close()
  closeReviseEs()
})
</script>

<template>
  <div class="grid lg:grid-cols-[16.5rem_minmax(0,1fr)] gap-6">
    <aside class="panel p-2.5 space-y-0.5 max-h-[calc(100vh-7rem)] overflow-auto lg:sticky lg:top-[4.5rem]">
      <div class="px-2 py-2 flex items-center justify-between">
        <span class="meta">大纲条目</span>
        <span v-if="outline?.items?.length" class="meta tabular">{{ outline.items.length }}</span>
      </div>
      <button
        v-for="item in outline?.items || []"
        :key="item.id"
        class="rail-item cv-item"
        :class="{ 'rail-item--active': selected?.id === item.id }"
        :disabled="streaming || reviseBusy"
        @click="selectItem(item)"
      >
        <div class="font-medium leading-snug">{{ item.order }}. {{ item.title }}</div>
        <div class="mt-1">
          <span
            class="status-pill"
            :class="item.status === 'done' ? 'status-pill--ok' : item.status === 'generating' ? 'status-pill--busy' : 'status-pill--idle'"
          >
            {{ itemStatusLabel(item.status) }}
          </span>
        </div>
      </button>
      <p v-if="!outline" class="px-2 py-3 empty">请先在大纲页生成并确认。</p>
    </aside>

    <section class="space-y-4 min-w-0">
      <div class="panel toolbar toolbar--split">
        <div class="toolbar__actions">
          <button class="btn" :disabled="!selected || streaming || reviseBusy" @click="startGenerate">
            {{ streaming ? '生成中…' : error ? '重试生成' : '流式生成' }}
          </button>
          <button
            class="btn-ghost"
            :disabled="!chapterId || streaming || reviseBusy"
            @click="reviseFailed ? retryCommitKnowledge() : saveRevise()"
          >
            {{ revising ? '入库中…' : reviseFailed ? '重试入库' : '保存修订并入库' }}
          </button>
          <button
            class="btn-danger btn-sm"
            :disabled="!chapterId || activeVersionId == null || streaming || deleting || deletingChapter || reviseBusy"
            @click="deleteCurrentVersion"
          >
            {{ deleting ? '删除中…' : '删除当前版本' }}
          </button>
          <button
            class="btn-danger btn-sm"
            :disabled="!chapterId || streaming || deleting || deletingChapter || reviseBusy"
            @click="deleteWholeChapter"
            title="危险：清除整章及全部版本"
          >
            {{ deletingChapter ? '删除中…' : '删除整章及全部版本' }}
          </button>
        </div>
        <span class="text-sm tabular meta">
          {{ status }}
          <span v-if="displayChars" class="ml-2">{{ displayChars }} 字</span>
        </span>
      </div>

      <div v-if="revising || reviseFailed || reviseProgress > 0" class="panel p-5">
        <div class="text-sm mb-2 font-medium">入库进度</div>
        <ProgressBar :value="reviseProgress" :failed="reviseFailed" />
        <div class="text-sm mt-2 tabular">
          {{ Math.round(reviseProgress) }}%
          <span class="meta"> · {{ reviseFailed ? '失败' : revising ? '进行中' : '完成' }} </span>
        </div>
        <div class="meta mt-1">{{ reviseMessage }}</div>
        <p v-if="reviseError" class="alert alert--danger mt-3">{{ reviseError }}</p>
        <p class="meta mt-2">摘要 → 实体抽取 → 向量化 → 记忆更新</p>
      </div>

      <div class="panel p-5 grid gap-4 sm:grid-cols-2">
        <div class="flex flex-wrap gap-4 items-end">
          <div>
            <label class="label">本章目标字数</label>
            <input
              v-model.number="targetChars"
              type="number"
              min="1500"
              max="30000"
              step="100"
              class="input w-32"
              :disabled="streaming || reviseBusy"
              @input="onTargetCharsInput"
            />
          </div>
          <p class="meta flex-1 min-w-[180px]">
            原作均长
            <span v-if="originalAvgChars">约 {{ originalAvgChars }} 字</span>
            <span v-else>尚未统计（导入原作并入库后自动计算）</span>
            · 本章目标约 {{ targetChars || '—' }} 字
            <span v-if="willSegment">；长章将按大纲要点分段流式生成。</span>
          </p>
        </div>
        <div class="flex flex-wrap gap-4 items-end">
          <label class="check">
            <input v-model="runCritic" type="checkbox" :disabled="streaming || reviseBusy" />
            启用一致性检验
          </label>
          <div v-if="runCritic">
            <label class="label">Critic 轮数</label>
            <select
              v-model.number="maxCriticRounds"
              class="input w-28"
              :disabled="streaming || reviseBusy || willSegment"
            >
              <option :value="0">0（仅审查）</option>
              <option :value="1">1</option>
              <option :value="2">2</option>
            </select>
          </div>
          <p class="meta flex-1 min-w-[160px]">
            <template v-if="willSegment">
              长章仅审查、不整章重写。分段进度会显示「正在撰写第 i/n 段…」。
            </template>
            <template v-else> 关闭可加快生成；Critic 会整章重写，较慢。刷新后会自动回载已生成章节。 </template>
          </p>
        </div>
      </div>

      <p v-if="error" class="alert alert--danger">{{ error }}</p>

      <div v-if="selected" class="panel p-5 text-sm">
        <div class="font-medium">{{ selected.title }}</div>
        <div class="mt-1" style="color: var(--ink-muted)">{{ selected.summary }}</div>
        <ul v-if="(selected.key_points || []).length" class="mt-2 list-disc pl-5 meta space-y-0.5">
          <li v-for="(p, i) in selected.key_points || []" :key="i">{{ p }}</li>
        </ul>
      </div>

      <div class="editor-frame">
        <div class="editor-chrome">
          <span class="text-sm font-medium truncate">{{ selected?.title || '正文' }}</span>
          <span class="meta tabular">{{ displayChars ? `${displayChars} 字` : '空白稿纸' }}</span>
        </div>
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
          placeholder="生成内容将在此出现，可直接修订…"
          :disabled="reviseBusy"
        />
      </div>

      <div v-if="consistency" class="panel p-5">
        <div class="font-medium mb-2 flex flex-wrap items-baseline gap-2">
          一致性报告
          <span class="badge" :class="consistency.ok ? 'badge--ok' : 'badge--danger'">
            {{ consistency.ok ? '通过' : '有问题' }}
          </span>
          <span class="meta">Critic {{ consistency.critic_rounds || 0 }} 轮</span>
        </div>
        <ul class="space-y-1.5 text-sm">
          <li v-for="(iss, i) in consistency.issues || []" :key="i" class="flex gap-2">
            <span :class="severityClass(iss.severity)" :title="iss.severity">{{
              severityLabel(iss.severity)
            }}</span>
            <span>
              <span class="meta">{{ iss.type }}</span>
              — {{ iss.message }}
            </span>
          </li>
          <li v-if="!(consistency.issues || []).length" class="empty">无问题</li>
        </ul>
      </div>
      <div v-else-if="showNoReportHint" class="panel p-5">
        <div class="font-medium mb-1">一致性报告</div>
        <p class="empty">该版本无一致性报告</p>
        <p class="meta mt-1">
          常见原因：生成时关闭了一致性检验；或为更早的草稿（报告在后续 Critic 修订版上）。
        </p>
      </div>

      <div v-if="versions.length" class="panel p-5">
        <div class="text-sm mb-2 font-medium">版本链</div>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="v in versions"
            :key="v.id"
            class="chip"
            :class="{ 'chip--active': activeVersionId === v.id }"
            :disabled="reviseBusy"
            @click="loadVersion(v)"
          >
            #{{ v.id }} {{ versionLabel(v.version_type) }}
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
