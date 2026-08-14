<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { novelsApi, type Novel } from '@/api'

const route = useRoute()
const novel = ref<Novel | null>(null)
const id = computed(() => Number(route.params.id))

const tabs = [
  { name: 'bible', label: 'Story Bible', path: 'bible' },
  { name: 'outline', label: '大纲', path: 'outline' },
  { name: 'write', label: '续写', path: 'write' },
  { name: 'costs', label: '成本', path: 'costs' },
  { name: 'tasks', label: '任务', path: 'tasks' },
]

function exportNovel(format: 'txt' | 'md' = 'txt') {
  window.open(novelsApi.exportUrl(id.value, format), '_blank')
}

onMounted(async () => {
  const { data } = await novelsApi.get(id.value)
  novel.value = data
})
</script>

<template>
  <div>
    <div class="mb-4 flex items-end justify-between gap-4">
      <div class="min-w-0">
        <div class="page-title truncate">{{ novel?.title || '…' }}</div>
        <div class="page-desc tabular">
          {{ novel?.genre }} · {{ novel?.chapter_count }} 章 · {{ novel?.status }}
        </div>
      </div>
      <div class="flex gap-2 shrink-0">
        <button class="btn-ghost" title="导出为 TXT" @click="exportNovel('txt')">导出 TXT</button>
        <button class="btn-ghost" title="导出为 Markdown" @click="exportNovel('md')">导出 MD</button>
      </div>
    </div>
    <nav class="ws-tabs mb-5">
      <RouterLink
        v-for="t in tabs"
        :key="t.name"
        :to="`/novels/${id}/${t.path}`"
        class="ws-tab"
      >
        {{ t.label }}
      </RouterLink>
    </nav>
    <RouterView />
  </div>
</template>
