<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { tasksApi, type Task } from '@/api'

const route = useRoute()
const novelId = Number(route.params.id)
const tasks = ref<Task[]>([])

onMounted(async () => {
  const { data } = await tasksApi.list(novelId)
  tasks.value = data
})
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="px-4 py-2 text-sm border-b font-medium" style="border-color: var(--line)">任务历史</div>
    <ul class="divide-y" style="border-color: var(--line)">
      <li v-for="t in tasks" :key="t.id" class="px-4 py-3 text-sm">
        <div class="flex justify-between gap-3">
          <div>
            <span class="font-medium">#{{ t.id }} {{ t.task_type }}</span>
            <span class="ml-2 text-xs" style="color: var(--ink-muted)">{{ t.status }}</span>
          </div>
          <div class="text-xs" style="color: var(--ink-muted)">{{ Math.round(t.progress) }}%</div>
        </div>
        <div class="text-xs mt-1" style="color: var(--ink-muted)">{{ t.message }}</div>
        <div v-if="t.error" class="text-xs mt-1" style="color: var(--danger)">{{ t.error }}</div>
      </li>
      <li v-if="!tasks.length" class="px-4 py-6 text-sm" style="color: var(--ink-muted)">暂无任务</li>
    </ul>
  </div>
</template>
