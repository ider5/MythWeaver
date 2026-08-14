<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { tasksApi, type Task } from '@/api'
import ProgressBar from '@/components/ProgressBar.vue'

const route = useRoute()
const router = useRouter()
const task = ref<Task | null>(null)
const error = ref('')
let es: EventSource | null = null

onMounted(() => {
  const taskId = Number(route.params.taskId)
  const novelId = Number(route.params.id)
  es = new EventSource(`/api/tasks/${taskId}/events`)
  es.onmessage = (ev) => {
    try {
      task.value = JSON.parse(ev.data)
      if (task.value?.status === 'completed') {
        es?.close()
        setTimeout(() => router.push(`/novels/${novelId}/bible`), 800)
      }
      if (task.value?.status === 'failed') {
        error.value = task.value.error || '入库失败'
        es?.close()
      }
    } catch {
      /* ignore */
    }
  }
  es.onerror = async () => {
    try {
      const { data } = await tasksApi.get(taskId)
      task.value = data
    } catch (e: any) {
      error.value = e?.message || '连接中断'
    }
  }
})

onUnmounted(() => es?.close())

function statusText(s?: string) {
  if (!s) return '连接中'
  if (s === 'completed') return '完成'
  if (s === 'failed') return '失败'
  if (s === 'running') return '进行中'
  if (s === 'pending') return '排队'
  return s
}

function statusTone(s?: string, failed?: boolean) {
  if (failed || s === 'failed') return 'status-pill--danger'
  if (s === 'completed') return 'status-pill--ok'
  if (s === 'running' || s === 'pending') return 'status-pill--busy'
  return 'status-pill--idle'
}
</script>

<template>
  <div class="max-w-xl mx-auto panel p-8">
    <div class="kicker mb-2">入库</div>
    <h1 class="page-title text-2xl mb-1">入库进度</h1>
    <p class="page-desc mb-6">摘要 → 实体抽取 → 向量化，可断点续传</p>

    <div class="progress-hero mb-4 tabular">{{ Math.round(task?.progress || 0) }}%</div>
    <ProgressBar :value="task?.progress || 0" :failed="!!error" />
    <div class="text-sm mt-4">
      <span
        class="status-pill"
        :class="statusTone(task?.status, !!error)"
      >
        {{ statusText(task?.status) }}
      </span>
    </div>
    <div class="meta mt-2">{{ task?.message }}</div>
    <p v-if="error" class="alert alert--danger mt-4">{{ error }}</p>
  </div>
</template>
