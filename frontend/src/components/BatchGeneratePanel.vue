<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { generationApi, tasksApi, type Outline, type Task } from '@/api'
import ProgressBar from '@/components/ProgressBar.vue'

interface BatchRow {
  order: number
  outline_item_id?: number
  title?: string
  chapter_index?: number
  status: string
  message?: string
  consistency_ok?: boolean | null
}

const props = defineProps<{
  novelId: number
  outline: Outline | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  running: [value: boolean]
  finished: []
}>()

const count = ref(2)
const fromOrder = ref(1)
const runCritic = ref(true)
const running = ref(false)
const stopping = ref(false)
const activeTaskId = ref<number | null>(null)
const failed = ref(false)
const paused = ref(false)
const progress = ref(0)
const message = ref('')
const errorText = ref('')
const rows = ref<BatchRow[]>([])

let es: EventSource | null = null

const sortedItems = computed(() =>
  [...(props.outline?.items || [])].sort((a, b) => a.order - b.order),
)

const chapterCount = computed(() => Math.min(10, Math.max(1, Number(count.value) || 1)))

const preview = computed(() => {
  const start = Math.max(1, Number(fromOrder.value) || 1)
  const base = props.outline?.start_from_chapter || 1
  return Array.from({ length: chapterCount.value }, (_, index) => {
    const order = start + index
    const item = sortedItems.value.find((row) => row.order === order)
    return {
      order,
      title: item?.title || '',
      chapterIndex: base + order - 1,
      missing: !item,
      done: item?.status === 'done',
    }
  })
})

const missingOrders = computed(() => preview.value.filter((row) => row.missing).map((row) => row.order))
const confirmed = computed(() => props.outline?.status === 'confirmed')
const canStart = computed(
  () =>
    !!props.outline &&
    confirmed.value &&
    missingOrders.value.length === 0 &&
    !running.value &&
    !props.disabled,
)

const displayRows = computed(() => {
  if (rows.value.length) return rows.value
  return preview.value.map((row) => ({
    order: row.order,
    title: row.title,
    chapter_index: row.chapterIndex,
    status: row.missing ? 'missing' : 'queued',
    message: row.missing ? '大纲里没有这一序' : row.done ? '已有正文，将覆盖重写' : '',
  }))
})

watch(
  () => props.outline?.id,
  () => {
    if (running.value) return
    const next = sortedItems.value.find((item) => item.status !== 'done') || sortedItems.value[0]
    fromOrder.value = next?.order || 1
    rows.value = []
    message.value = ''
    errorText.value = ''
    failed.value = false
    paused.value = false
    progress.value = 0
  },
  { immediate: true },
)

watch(running, (value, previous) => {
  emit('running', value)
  if (previous && !value) emit('finished')
})

function closeEs() {
  es?.close()
  es = null
}

function rowLabel(status: string) {
  if (status === 'done') return '已完成'
  if (status === 'running') return '生成中'
  if (status === 'paused') return '已暂停'
  if (status === 'failed') return '失败'
  if (status === 'blocked') return '未写'
  if (status === 'missing') return '缺失'
  return '排队'
}

function rowClass(status: string) {
  if (status === 'done') return 'status-pill--ok'
  if (status === 'running') return 'status-pill--busy'
  if (status === 'paused' || status === 'failed' || status === 'missing') return 'status-pill--danger'
  return 'status-pill--idle'
}

function applyTask(task: Task) {
  progress.value = Number(task.progress) || 0
  const result = (task.result || {}) as {
    items?: BatchRow[]
    summary?: string
    paused?: boolean
  }
  if (Array.isArray(result.items) && result.items.length) rows.value = result.items
  if (result.summary) message.value = result.summary
  else if (task.message) message.value = task.message

  if (task.status === 'failed') {
    running.value = false
    failed.value = true
    paused.value = false
    errorText.value = task.error || result.summary || '生成失败'
    message.value = errorText.value
    return
  }
  if (task.status === 'completed' || task.status === 'cancelled') {
    running.value = false
    failed.value = false
    paused.value = Boolean(result.paused)
    if (task.status === 'cancelled') message.value = '已取消'
  }
}

function watchTask(taskId: number) {
  closeEs()
  es = new EventSource(`/api/tasks/${taskId}/events`)
  es.onmessage = (ev) => {
    try {
      applyTask(JSON.parse(ev.data))
      const status = JSON.parse(ev.data).status
      if (status === 'completed' || status === 'failed' || status === 'cancelled') closeEs()
    } catch {
      /* ignore malformed events */
    }
  }
  es.onerror = async () => {
    try {
      const { data } = await tasksApi.get(taskId)
      applyTask(data)
      if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
        closeEs()
      }
    } catch (err: any) {
      running.value = false
      failed.value = true
      errorText.value = err?.message || '进度连接中断'
      closeEs()
    }
  }
}

async function stop() {
  if (!activeTaskId.value || stopping.value) return
  stopping.value = true
  try {
    const { data } = await tasksApi.cancel(activeTaskId.value)
    applyTask(data)
  } catch (err: any) {
    errorText.value = err?.response?.data?.detail || err?.message || '取消失败'
  } finally {
    stopping.value = false
  }
}

async function start() {
  if (!canStart.value || !props.outline) return
  running.value = true
  failed.value = false
  paused.value = false
  errorText.value = ''
  progress.value = 2
  message.value = '连续生成排队中…'
  rows.value = preview.value.map((row) => ({
    order: row.order,
    title: row.title,
    chapter_index: row.chapterIndex,
    status: 'queued',
    message: '',
  }))
  try {
    const { data } = await generationApi.batch(props.novelId, {
      outline_id: props.outline.id,
      from_order: Math.max(1, Number(fromOrder.value) || 1),
      count: chapterCount.value,
      run_critic: runCritic.value,
    })
    activeTaskId.value = data.task_id
    watchTask(data.task_id)
  } catch (err: any) {
    running.value = false
    failed.value = true
    errorText.value = err?.response?.data?.detail || err?.message || '无法开始连续生成'
    message.value = errorText.value
  }
}

onUnmounted(() => closeEs())
</script>

<template>
  <section class="panel director">
    <div class="director__head">
      <div>
        <div class="kicker">导演</div>
        <h2 class="director__title">连续生成</h2>
      </div>
      <p class="meta director__hint">
        从已确认大纲的某一序起，按顺序写 N 章。Critic 未通过、生成失败或停止时，下一章不再写。正在写的这一章会写完。
      </p>
    </div>

    <div class="director__controls">
      <label class="field">
        <span class="label">从序号</span>
        <input v-model.number="fromOrder" class="input" type="number" min="1" :disabled="running" />
      </label>
      <label class="field">
        <span class="label">章数</span>
        <input v-model.number="count" class="input" type="number" min="1" max="10" :disabled="running" />
      </label>
      <label class="check">
        <input v-model="runCritic" type="checkbox" :disabled="running" />
        <span>生成后做 Critic</span>
      </label>
      <button class="btn" :disabled="!canStart" @click="start">
        {{ running ? '生成中…' : `连续生成 ${chapterCount} 章` }}
      </button>
      <button v-if="running" class="btn-ghost" type="button" :disabled="stopping" @click="stop">
        {{ stopping ? '正在停下…' : '停止' }}
      </button>
    </div>

    <p v-if="!outline" class="meta">先选定一份大纲。</p>
    <p v-else-if="!confirmed" class="meta">这份大纲还是草稿。确认之后才能连续生成。</p>
    <p v-else-if="missingOrders.length" class="alert alert--danger">
      序号 {{ missingOrders.join('、') }} 不在这份大纲里。
    </p>

    <div v-if="running || failed || paused || progress > 0" class="director__progress">
      <ProgressBar :value="progress" :failed="failed" />
      <p v-if="message && !paused && !failed" class="meta">{{ message }}</p>
    </div>
    <p v-if="errorText" class="alert alert--danger">{{ errorText }}</p>
    <p v-else-if="paused" class="alert alert--warn">{{ message }}</p>

    <ul v-if="outline && displayRows.length" class="director__list">
      <li v-for="row in displayRows" :key="row.order">
        <span class="chapter-index">第{{ row.chapter_index || row.order }}章</span>
        <span class="director__name">{{ row.title || `序号 ${row.order}` }}</span>
        <span class="status-pill" :class="rowClass(row.status)">{{ rowLabel(row.status) }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.director {
  padding: 1.1rem 1.15rem 1rem;
  border-left: 3px solid var(--accent);
  background:
    linear-gradient(90deg, var(--accent-soft), transparent 7rem),
    var(--panel);
}

.director__head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-end;
}

.director__title {
  margin: 0.15rem 0 0;
  font-family: var(--font-prose);
  font-size: 1.35rem;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.director__hint {
  max-width: 28rem;
  margin: 0;
  text-align: right;
}

.director__controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1rem;
  align-items: flex-end;
  margin-top: 0.9rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.field .input {
  width: 5.5rem;
}

.check {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 2.4rem;
  font-size: 0.9rem;
}

.director__progress {
  margin-top: 0.9rem;
}

.director__list {
  list-style: none;
  margin: 0.85rem 0 0;
  padding: 0;
  display: grid;
  gap: 0.35rem;
}

.director__list li {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  min-height: 2rem;
}

.director__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alert--warn {
  margin-top: 0.75rem;
  color: var(--warn);
  background: var(--warn-soft);
}

@media (max-width: 720px) {
  .director__head {
    flex-direction: column;
    align-items: flex-start;
  }

  .director__hint {
    text-align: left;
  }
}
</style>
