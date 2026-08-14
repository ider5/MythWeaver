<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { tasksApi, type Task } from '@/api'
import ProgressBar from '@/components/ProgressBar.vue'

const route = useRoute()
const novelId = Number(route.params.id)
const tasks = ref<Task[]>([])

function statusClass(s: string) {
  if (s === 'failed') return 'sev sev--error'
  if (s === 'completed') return 'sev sev--info'
  return 'sev sev--warn'
}

function statusLabel(s: string) {
  if (s === 'completed') return '完成'
  if (s === 'failed') return '失败'
  if (s === 'running') return '进行中'
  if (s === 'pending') return '排队'
  return s
}

function typeLabel(s: string) {
  if (s === 'ingest') return '入库'
  if (s === 'outline_generate') return '生成大纲'
  if (s === 'revise_commit') return '修订入库'
  return s
}

onMounted(async () => {
  const { data } = await tasksApi.list(novelId)
  tasks.value = data
})
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="panel-head">任务历史</div>
    <ul class="list-divide">
      <li v-for="t in tasks" :key="t.id" class="cv-item px-5 py-4 text-sm">
        <div class="flex justify-between gap-3 items-start">
          <div class="min-w-0">
            <span class="font-medium">#{{ t.id }} {{ typeLabel(t.task_type) }}</span>
            <span class="ml-2" :class="statusClass(t.status)">{{ statusLabel(t.status) }}</span>
          </div>
          <div class="meta tabular shrink-0">{{ Math.round(t.progress) }}%</div>
        </div>
        <ProgressBar class="mt-2.5" :value="t.progress" :failed="t.status === 'failed'" />
        <div class="meta mt-1.5">{{ t.message }}</div>
        <div v-if="t.error" class="text-xs mt-1" style="color: var(--danger)">{{ t.error }}</div>
      </li>
      <li v-if="!tasks.length" class="px-5 py-8 empty">暂无任务</li>
    </ul>
  </div>
</template>
