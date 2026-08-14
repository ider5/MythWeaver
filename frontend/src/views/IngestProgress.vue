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
</script>

<template>
  <div class="max-w-xl mx-auto panel p-6">
    <h1 class="page-title text-2xl mb-1">入库进度</h1>
    <p class="page-desc mb-5">摘要 → 实体抽取 → 向量化，可断点续传</p>

    <ProgressBar :value="task?.progress || 0" :failed="!!error" />
    <div class="text-sm mt-3 tabular">
      {{ Math.round(task?.progress || 0) }}% · {{ task?.status || '连接中' }}
    </div>
    <div class="meta mt-1">{{ task?.message }}</div>
    <p v-if="error" class="text-sm mt-3" style="color: var(--danger)">{{ error }}</p>
  </div>
</template>
