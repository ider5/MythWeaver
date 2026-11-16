<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { tasksApi, type Task } from '@/api'
import ProgressBar from '@/components/ProgressBar.vue'

const route = useRoute()
const novelId = Number(route.params.id)
const tasks = ref<Task[]>([])
const loaded = ref(false)
const actionError = ref('')
const busyId = ref(0)
let timer = 0

const summary = computed(() => {
  const active = tasks.value.filter((t) => t.status === 'pending' || t.status === 'running').length
  const retryable = tasks.value.filter((t) => t.recoverable).length
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
  if (t.status === 'cancelled') return 'status-pill--idle'
  return 'status-pill--busy'
}

function rowClass(status: string) {
  if (status === 'failed') return 'task-row--fail'
  if (status === 'completed') return 'task-row--ok'
  if (status === 'cancelled') return 'task-row--stop'
  return 'task-row--run'
}

function typeLabel(s: string) {
  if (s === 'ingest') return '入库'
  if (s === 'outline_generate') return '大纲'
  if (s === 'revise_commit') return '修订'
  return s
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
  busyId.value = t.id
  try {
    const { data } = await tasksApi.cancel(t.id)
    upsert(data)
  } catch (e: any) {
    actionError.value = detailOf(e, '取消失败')
  } finally {
    busyId.value = 0
  }
}

async function onRetry(t: Task) {
  actionError.value = ''
  busyId.value = t.id
  try {
    await tasksApi.retry(t.id)
    await load()
  } catch (e: any) {
    actionError.value = detailOf(e, '重试失败')
  } finally {
    busyId.value = 0
  }
}

onMounted(async () => {
  try {
    await load()
  } catch (e: any) {
    actionError.value = detailOf(e, '任务加载失败')
  } finally {
    loaded.value = true
  }
  timer = window.setInterval(() => {
    if (document.visibilityState === 'hidden') return
    load().catch(() => {})
  }, 2000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="panel-head flex items-center justify-between gap-3">
      <span>任务</span>
      <span v-if="summary" class="meta font-normal">{{ summary }}</span>
    </div>
    <p v-if="actionError" class="alert alert--danger mx-4 mt-3 mb-0">{{ actionError }}</p>
    <ul class="list-divide">
      <li v-for="t in tasks" :key="t.id" class="task-row" :class="rowClass(t.status)">
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-2 min-w-0">
            <span class="font-medium truncate">{{ typeLabel(t.task_type) }}</span>
            <span class="status-pill shrink-0" :class="tone(t)">{{ statusLabel(t) }}</span>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span class="meta tabular">{{ Math.round(t.progress) }}%</span>
            <button
              v-if="canCancel(t)"
              type="button"
              class="btn-danger btn-sm"
              :disabled="busyId === t.id"
              @click="onCancel(t)"
            >
              取消
            </button>
            <button
              v-else-if="t.recoverable"
              type="button"
              class="btn btn-sm"
              :disabled="busyId === t.id"
              @click="onRetry(t)"
            >
              重试
            </button>
          </div>
        </div>
        <ProgressBar class="mt-2.5" :value="t.progress" :failed="t.status === 'failed'" />
        <div class="mt-1.5 flex items-baseline justify-between gap-3">
          <div class="meta min-w-0 truncate">{{ t.message }}</div>
          <div v-if="t.created_at" class="meta tabular shrink-0">{{ timeLabel(t.created_at) }}</div>
        </div>
        <div v-if="t.error" class="task-row__error" :title="t.error">{{ t.error }}</div>
      </li>
      <li v-if="loaded && !tasks.length" class="px-5 py-8 empty">暂无任务</li>
    </ul>
  </div>
</template>
