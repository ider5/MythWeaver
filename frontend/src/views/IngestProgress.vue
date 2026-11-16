<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { tasksApi, type Task } from '@/api'
import ProgressBar from '@/components/ProgressBar.vue'
import { watchTaskEvents } from '@/composables/useTaskEvents'

const route = useRoute()
const router = useRouter()
const task = ref<Task | null>(null)
const error = ref('')
const actionError = ref('')
const linkState = ref<'live' | 'reconnecting' | 'off'>('off')
const busy = ref(false)
let stopWatch: (() => void) | null = null
let redirectTimer = 0

function detailOf(err: unknown, fallback: string) {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

function follow(taskId: number) {
  stopWatch?.()
  linkState.value = 'live'
  const novelId = Number(route.params.id)
  stopWatch = watchTaskEvents(
    taskId,
    (incoming) => {
      task.value = { ...(task.value || ({} as Task)), ...incoming }
      if (incoming.status === 'completed') {
        error.value = ''
        if (redirectTimer) window.clearTimeout(redirectTimer)
        redirectTimer = window.setTimeout(() => {
          void router.push(`/novels/${novelId}/bible`)
        }, 800)
        return
      }
      if (incoming.status === 'failed') {
        error.value = incoming.error || '入库失败'
        return
      }
      if (incoming.status !== 'cancelled') error.value = ''
    },
    (state) => {
      linkState.value = state
    },
  )
}

onMounted(() => follow(Number(route.params.taskId)))
watch(
  () => route.params.taskId,
  (id) => {
    if (id != null) follow(Number(id))
  },
)
onUnmounted(() => {
  stopWatch?.()
  if (redirectTimer) window.clearTimeout(redirectTimer)
})

const canCancel = computed(() => {
  const status = task.value?.status
  return (status === 'pending' || status === 'running') && task.value?.message !== '正在取消'
})

async function onCancel() {
  if (!task.value || busy.value) return
  busy.value = true
  actionError.value = ''
  try {
    const { data } = await tasksApi.cancel(task.value.id)
    task.value = { ...task.value, ...data }
  } catch (err) {
    actionError.value = detailOf(err, '取消失败')
  } finally {
    busy.value = false
  }
}

async function onRetry() {
  if (!task.value || busy.value) return
  busy.value = true
  actionError.value = ''
  error.value = ''
  try {
    const { data } = await tasksApi.retry(task.value.id)
    task.value = data
    if (data.id !== Number(route.params.taskId)) {
      await router.replace(`/novels/${route.params.id}/ingest/${data.id}`)
    } else {
      follow(data.id)
    }
  } catch (err) {
    actionError.value = detailOf(err, '重试失败')
  } finally {
    busy.value = false
  }
}

function statusText(s?: string) {
  if (linkState.value === 'reconnecting') return '重连中'
  if (!s) return '连接中'
  if (s === 'completed') return '完成'
  if (s === 'failed') return '失败'
  if (s === 'running') return '进行中'
  if (s === 'pending') return '排队'
  if (s === 'cancelled') return '已取消'
  return s
}

function statusTone(s?: string, failed?: boolean) {
  if (failed || s === 'failed') return 'status-pill--danger'
  if (s === 'completed') return 'status-pill--ok'
  if (s === 'running' || s === 'pending') return 'status-pill--busy'
  return 'status-pill--idle'
}

function retryLabel() {
  return task.value?.status === 'cancelled' ? '重新排队' : '重试'
}
</script>

<template>
  <div class="max-w-xl mx-auto panel p-8">
    <div class="kicker mb-2">入库</div>
    <h1 class="page-title text-2xl mb-1">入库进度</h1>
    <p class="page-desc mb-6">先做摘要，再抽人物和设定，最后做向量。已经做完的章会跳过。</p>

    <div class="progress-hero mb-4 tabular">{{ Math.round(task?.progress || 0) }}%</div>
    <ProgressBar :value="task?.progress || 0" :failed="task?.status === 'failed'" />
    <div class="mt-4 flex flex-wrap items-center gap-2">
      <span class="status-pill" :class="statusTone(task?.status, task?.status === 'failed')">
        {{ statusText(task?.status) }}
      </span>
      <button v-if="canCancel" type="button" class="btn-danger btn-sm" :disabled="busy" @click="onCancel">
        {{ busy ? '取消中' : '取消' }}
      </button>
      <button
        v-else-if="task?.recoverable"
        type="button"
        class="btn btn-sm"
        :disabled="busy"
        @click="onRetry"
      >
        {{ busy ? '排队中' : retryLabel() }}
      </button>
    </div>
    <div class="meta mt-2">{{ task?.message }}</div>
    <p v-if="task?.recoverable" class="meta mt-2">
      {{
        task.status === 'cancelled'
          ? '这次已经取消。重新排队会再跑一遍，做完的章会跳过。'
          : '按原来的参数再排一次。做完的章会跳过。'
      }}
    </p>
    <p v-if="linkState === 'reconnecting'" class="meta mt-3" role="status">进度连接断了，正在重连。</p>
    <p v-if="actionError" class="alert alert--danger mt-4">{{ actionError }}</p>
    <p v-else-if="error" class="alert alert--danger mt-4">{{ error }}</p>
  </div>
</template>
