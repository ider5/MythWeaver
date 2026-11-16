<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { tasksApi, type Task } from '@/api'
import ProgressBar from '@/components/ProgressBar.vue'

defineOptions({ name: 'TaskHistory' })

const route = useRoute()
const novelId = Number(route.params.id)
const tasks = ref<Task[]>([])
const loaded = ref(false)
const actionError = ref('')
const actionNote = ref('')
const busyId = ref(0)
const expandedId = ref<number | null>(null)
const liveDetail = ref<Record<string, unknown> | null>(null)
let timer = 0
let es: EventSource | null = null

function closeEs() {
  es?.close()
  es = null
}

function openEs(taskId: number) {
  closeEs()
  liveDetail.value = null
  es = new EventSource(tasksApi.eventsUrl(taskId))
  es.onmessage = (ev) => {
    try {
      const payload = JSON.parse(ev.data) as Task & Record<string, unknown>
      liveDetail.value = payload
      upsert(payload as Task)
      if (['completed', 'failed', 'cancelled'].includes(String(payload.status))) {
        closeEs()
      }
    } catch {
      /* ignore malformed */
    }
  }
  es.onerror = () => {
    /* 浏览器会自动重连；结束态由 onmessage 关闭 */
  }
}

function toggleExpand(t: Task) {
  if (expandedId.value === t.id) {
    expandedId.value = null
    liveDetail.value = null
    closeEs()
    return
  }
  expandedId.value = t.id
  if (t.status === 'pending' || t.status === 'running') openEs(t.id)
  else {
    closeEs()
    liveDetail.value = { ...t }
  }
}

watch(expandedId, (id) => {
  if (id == null) {
    closeEs()
    liveDetail.value = null
  }
})

const counts = computed(() => {
  let active = 0
  let retryable = 0
  let done = 0
  for (const t of tasks.value) {
    if (t.status === 'pending' || t.status === 'running') active += 1
    if (t.recoverable) retryable += 1
    if (t.status === 'completed') done += 1
  }
  return { active, retryable, done }
})

const summary = computed(() => {
  const { active, retryable } = counts.value
  if (!tasks.value.length) return ''
  if (!active && !retryable) return '全部完成'
  const parts: string[] = []
  if (active) parts.push(`${active} 进行中`)
  if (retryable) parts.push(`${retryable} 可重试`)
  return parts.join(' · ')
})

function cancelling(t: Task) {
  return (t.status === 'pending' || t.status === 'running') && t.message === '正在取消'
}

function canCancel(t: Task) {
  return (t.status === 'pending' || t.status === 'running') && !cancelling(t)
}

function isLive(t: Task) {
  return t.status === 'running' && !cancelling(t)
}

function statusLabel(t: Task) {
  if (cancelling(t)) return '取消中'
  if (t.status === 'completed') return '完成'
  if (t.status === 'failed') return '失败'
  if (t.status === 'running') return '进行中'
  if (t.status === 'pending') return '排队'
  if (t.status === 'cancelled') return '已取消'
  return t.status
}

function tone(t: Task) {
  if (t.status === 'failed') return 'status-pill--danger'
  if (t.status === 'completed') return 'status-pill--ok'
  if (t.status === 'cancelled' || t.status === 'pending') return 'status-pill--idle'
  return 'status-pill--busy'
}

function rowClass(t: Task) {
  if (cancelling(t) || t.status === 'cancelled') return 'hub-row--stop'
  if (t.status === 'failed') return 'hub-row--fail'
  if (t.status === 'completed') return 'hub-row--ok'
  if (t.status === 'pending') return 'hub-row--queue'
  return 'hub-row--run'
}

function meterClass(t: Task) {
  if (t.status === 'failed') return ''
  if (isLive(t)) return 'hub-meter--live'
  if (t.status === 'pending' || t.status === 'cancelled' || cancelling(t)) return 'hub-meter--muted'
  return ''
}

function typeLabel(s: string) {
  if (s === 'ingest') return '入库'
  if (s === 'outline_generate') return '大纲'
  if (s === 'revise_commit') return '修订'
  if (s === 'batch_generate') return '连续生成'
  return s
}

function percent(t: Task) {
  const n = Number(t.progress)
  if (!Number.isFinite(n)) return 0
  return Math.round(Math.min(100, Math.max(0, n)))
}

function messageOf(t: Task) {
  if (t.message) return t.message
  if (t.status === 'pending') return '排队等待'
  if (t.status === 'running') return '正在执行'
  if (t.status === 'completed') return '完成'
  if (t.status === 'cancelled') return '已取消'
  if (t.status === 'failed') return '失败'
  return ''
}

function stamp(t: Task) {
  return t.updated_at || t.created_at || ''
}

function timeLabel(iso?: string) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`
}

function detailOf(e: any, fallback: string) {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

function upsert(task: Task) {
  const i = tasks.value.findIndex((item) => item.id === task.id)
  if (i >= 0) tasks.value[i] = task
  else tasks.value.unshift(task)
}

async function load() {
  const { data } = await tasksApi.list(novelId)
  tasks.value = data
}

async function onCancel(t: Task) {
  actionError.value = ''
  actionNote.value = ''
  busyId.value = t.id
  try {
    const { data } = await tasksApi.cancel(t.id)
    upsert(data)
    actionNote.value = data.status === 'cancelled' ? '任务已取消' : '已请求取消，当前步骤结束后停止'
  } catch (e: any) {
    actionError.value = detailOf(e, '取消失败')
  } finally {
    busyId.value = 0
  }
}

async function onRetry(t: Task) {
  actionError.value = ''
  actionNote.value = ''
  busyId.value = t.id
  try {
    await tasksApi.retry(t.id)
    await load()
    actionNote.value = '已重新入队'
  } catch (e: any) {
    actionError.value = detailOf(e, '重试失败')
  } finally {
    busyId.value = 0
  }
}

function startPolling() {
  if (timer) window.clearInterval(timer)
  timer = window.setInterval(() => {
    if (document.visibilityState === 'hidden') return
    load().catch(() => {})
  }, 2000)
}

onMounted(async () => {
  try {
    await load()
  } catch (e: any) {
    actionError.value = detailOf(e, '任务加载失败')
  } finally {
    loaded.value = true
  }
  startPolling()
})

onActivated(() => {
  load().catch(() => {})
  startPolling()
  if (expandedId.value != null) {
    const t = tasks.value.find((x) => x.id === expandedId.value)
    if (t && (t.status === 'pending' || t.status === 'running')) openEs(t.id)
  }
})

onDeactivated(() => {
  if (timer) window.clearInterval(timer)
  timer = 0
  closeEs()
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
  closeEs()
})
</script>

<template>
  <section class="hub" aria-labelledby="task-hub-title">
    <header class="hub-head">
      <div class="hub-head__lead">
        <h2 id="task-hub-title" class="hub-title">任务</h2>
        <p v-if="summary" class="hub-sr" role="status">{{ summary }}</p>
      </div>
      <ul v-if="tasks.length" class="hub-stats" aria-label="任务概况">
        <li class="hub-stat" :class="{ 'hub-stat--on': counts.active > 0 }">
          <span class="hub-stat__n">{{ counts.active }}</span>
          <span class="hub-stat__l">进行中</span>
        </li>
        <li class="hub-stat" :class="{ 'hub-stat--alert': counts.retryable > 0 }">
          <span class="hub-stat__n">{{ counts.retryable }}</span>
          <span class="hub-stat__l">可重试</span>
        </li>
        <li class="hub-stat">
          <span class="hub-stat__n">{{ counts.done }}</span>
          <span class="hub-stat__l">已完成</span>
        </li>
      </ul>
    </header>

    <p v-if="actionError" class="alert alert--danger hub-alert" role="alert">{{ actionError }}</p>
    <p v-else-if="actionNote" class="alert alert--ok hub-alert" role="status">{{ actionNote }}</p>

    <ul v-if="tasks.length" class="hub-list">
      <li
        v-for="(t, index) in tasks"
        :key="t.id"
        class="hub-row"
        :class="rowClass(t)"
        :style="{ '--i': Math.min(index, 8) }"
      >
        <div class="hub-row__main">
          <div class="hub-id">
            <span class="hub-type">{{ typeLabel(t.task_type) }}</span>
            <span
              class="status-pill"
              :class="[tone(t), { 'hub-pill--live': isLive(t) }]"
            >
              {{ statusLabel(t) }}
            </span>
            <button type="button" class="hub-detail-btn" @click="toggleExpand(t)">
              {{ expandedId === t.id ? '收起进度' : '详细进度' }}
            </button>
          </div>
          <p class="hub-msg" :title="messageOf(t)">{{ messageOf(t) }}</p>
          <div class="hub-meter" :class="meterClass(t)">
            <ProgressBar :value="t.progress" :failed="t.status === 'failed'" />
            <span class="hub-pct" aria-hidden="true">{{ percent(t) }}%</span>
          </div>
          <p v-if="t.error && t.error !== t.message" class="hub-error" :title="t.error">{{ t.error }}</p>
          <div v-if="expandedId === t.id" class="hub-live" aria-live="polite">
            <p class="hub-live__title">实时详情 #{{ t.id }}</p>
            <p class="hub-live__line">
              {{ (liveDetail?.message as string) || messageOf(t) }} ·
              {{ Math.round(Number(liveDetail?.progress ?? t.progress) || 0) }}%
            </p>
            <pre v-if="liveDetail?.result" class="hub-live__json">{{
              JSON.stringify(liveDetail.result, null, 2)
            }}</pre>
            <p v-if="liveDetail?.error" class="hub-error">{{ liveDetail.error }}</p>
          </div>
        </div>
        <div class="hub-row__side">
          <time
            v-if="stamp(t)"
            class="hub-time"
            :datetime="stamp(t)"
            :title="t.updated_at ? '最近更新' : '创建时间'"
          >
            {{ timeLabel(stamp(t)) }}
          </time>
          <button
            v-if="canCancel(t)"
            type="button"
            class="hub-act hub-act--stop"
            :disabled="busyId === t.id"
            :aria-label="busyId === t.id ? `正在取消${typeLabel(t.task_type)}` : `取消${typeLabel(t.task_type)}`"
            @click="onCancel(t)"
          >
            <svg class="hub-act__icon" viewBox="0 0 16 16" aria-hidden="true">
              <rect x="4" y="4" width="8" height="8" rx="1.25" fill="currentColor" />
            </svg>
            {{ busyId === t.id ? '取消中' : '取消' }}
          </button>
          <button
            v-else-if="t.recoverable"
            type="button"
            class="hub-act hub-act--retry"
            :disabled="busyId === t.id"
            :aria-label="busyId === t.id ? `正在重试${typeLabel(t.task_type)}` : `重试${typeLabel(t.task_type)}`"
            @click="onRetry(t)"
          >
            <svg class="hub-act__icon" viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="M13 8.2a5 5 0 1 1-1.35-3.4"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
              />
              <path
                d="M11.4 2.6v2.8H8.6"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            {{ busyId === t.id ? '重试中' : '重试' }}
          </button>
          <span v-else-if="cancelling(t)" class="hub-wait">取消中</span>
        </div>
      </li>
    </ul>

    <div v-else-if="!loaded" class="hub-empty">
      <p class="hub-empty__title">正在读取任务</p>
    </div>
    <div v-else-if="!actionError" class="hub-empty">
      <p class="hub-empty__title">还没有任务</p>
      <p>入库、大纲、修订和连续生成会出现在这里。进行中的可以取消，能重试的旁边有重试。</p>
    </div>
  </section>
</template>

<style scoped>
.hub {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.hub-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem 1.25rem;
  padding: 0.9rem 1.1rem;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--paper) 72%, transparent);
}

.hub-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.hub-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.hub-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.hub-stat {
  min-width: 4.7rem;
  padding: 0.4rem 0.7rem 0.45rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--paper);
}

.hub-stat__n {
  display: block;
  font-family: var(--font-prose);
  font-size: 1.35rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em;
  line-height: 1.05;
  color: var(--ink);
}

.hub-stat__l {
  display: block;
  margin-top: 0.12rem;
  font-size: 0.72rem;
  color: var(--ink-muted);
}

.hub-stat--on .hub-stat__n {
  color: var(--warn);
}

.hub-stat--alert .hub-stat__n {
  color: var(--danger);
}

.hub-alert {
  margin: 0.85rem 1rem 0;
}

.hub-list {
  margin: 0;
  padding: 0;
  list-style: none;
  background: var(--paper);
}

.hub-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.85rem 1rem;
  align-items: center;
  padding: 0.9rem 1.1rem 1rem;
  box-shadow: inset 3px 0 0 transparent;
  transition: background-color 160ms ease;
}

.hub-row + .hub-row {
  border-top: 1px solid var(--line);
}

.hub-row:hover {
  background: color-mix(in srgb, var(--bg-deep) 42%, var(--paper));
}

.hub-row--run {
  box-shadow: inset 3px 0 0 var(--warn);
}

.hub-row--queue {
  box-shadow: inset 3px 0 0 var(--line-strong);
}

.hub-row--ok {
  box-shadow: inset 3px 0 0 color-mix(in srgb, var(--accent) 55%, transparent);
}

.hub-row--fail {
  box-shadow: inset 3px 0 0 var(--danger);
  background: var(--danger-soft);
}

.hub-row--fail:hover {
  background: color-mix(in srgb, var(--danger) 12%, var(--paper));
}

.hub-row--stop {
  box-shadow: inset 3px 0 0 var(--line-strong);
}

.hub-id {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
}

.hub-type {
  min-width: 0;
  overflow: hidden;
  font-weight: 650;
  letter-spacing: -0.02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hub-pill--live::before {
  transform-origin: center;
  animation: hub-beat 1.35s ease-in-out infinite;
}

.hub-msg {
  margin: 0.35rem 0 0;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  font-size: 0.875rem;
  line-height: 1.45;
  color: var(--ink);
}

.hub-meter {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 3.1rem;
  gap: 0.6rem;
  align-items: center;
  margin-top: 0.55rem;
}

.hub-pct {
  font-size: 0.78rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  text-align: right;
  color: var(--ink);
}

.hub-row--fail .hub-pct {
  color: var(--danger);
}

.hub :deep(.progress) {
  height: 8px;
  background: color-mix(in srgb, var(--ink) 8%, var(--paper));
}

.hub :deep(.progress__bar) {
  background: var(--accent);
  transition: transform 480ms cubic-bezier(0.22, 0.8, 0.28, 1);
}

.hub-meter--live :deep(.progress__bar) {
  background: var(--warn);
}

.hub-meter--muted :deep(.progress__bar) {
  background: color-mix(in srgb, var(--ink) 32%, transparent);
}

.hub :deep(.progress__bar--failed) {
  background: var(--danger);
}

.hub-error {
  margin: 0.4rem 0 0;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  font-size: 0.75rem;
  line-height: 1.4;
  color: var(--danger);
}

.hub-row__side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.55rem;
  min-width: 6.4rem;
}

.hub-time {
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
  color: var(--ink-muted);
}

.hub-act {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  min-width: 5.75rem;
  height: 2rem;
  padding: 0 0.7rem;
  border-radius: var(--radius-sm);
  font-family: inherit;
  font-size: 0.8125rem;
  font-weight: 650;
  line-height: 1;
  letter-spacing: -0.01em;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease, transform 140ms ease;
}

.hub-act__icon {
  width: 0.85rem;
  height: 0.85rem;
  flex-shrink: 0;
}

.hub-act--stop {
  border: 1px solid color-mix(in srgb, var(--danger) 36%, var(--line));
  background: var(--paper);
  color: var(--danger);
}

.hub-act--stop:hover:not(:disabled) {
  background: var(--danger-soft);
}

.hub-act--retry {
  border: 1px solid transparent;
  background: var(--accent);
  color: #f4f8fa;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16);
}

.hub-act--retry:hover:not(:disabled) {
  background: var(--accent-hover);
}

.hub-act:active:not(:disabled) {
  transform: translateY(1px);
}

.hub-act:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.hub-act:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.hub-wait {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 5.75rem;
  height: 2rem;
  padding: 0 0.7rem;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--ink) 6%, var(--paper));
  color: var(--ink-muted);
  font-size: 0.8125rem;
  font-weight: 650;
}

.hub-empty {
  padding: 2.2rem 1.35rem 2.35rem;
  background: var(--paper);
}

.hub-empty__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.hub-empty p + p {
  margin: 0.35rem 0 0;
  max-width: 36rem;
  font-size: 0.875rem;
  line-height: 1.5;
  color: var(--ink-muted);
}

@keyframes hub-beat {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.28;
    transform: scale(0.68);
  }
}

@media (max-width: 640px) {
  .hub-head {
    flex-direction: column;
    align-items: stretch;
  }

  .hub-stat {
    flex: 1;
  }

  .hub-row {
    grid-template-columns: 1fr;
  }

  .hub-row__side {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    min-width: 0;
  }
}

.hub-detail-btn {
  margin-left: 0.5rem;
  border: 0;
  background: transparent;
  color: var(--accent);
  font: inherit;
  font-size: 0.8rem;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 0.15em;
}

.hub-live {
  margin-top: 0.75rem;
  padding: 0.75rem 0.85rem;
  border-radius: calc(var(--radius) - 2px);
  background: color-mix(in srgb, var(--bg) 70%, transparent);
  border: 1px solid var(--line);
}

.hub-live__title {
  margin: 0 0 0.35rem;
  font-size: 0.75rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
}

.hub-live__line {
  margin: 0;
  font-size: 0.9rem;
}

.hub-live__json {
  margin: 0.5rem 0 0;
  max-height: 12rem;
  overflow: auto;
  font-size: 0.75rem;
  white-space: pre-wrap;
}

@media (prefers-reduced-motion: reduce) {
  .hub-pill--live::before {
    animation: none;
  }

  .hub :deep(.progress__bar),
  .hub-act,
  .hub-row {
    transition: none;
  }
}
</style>
