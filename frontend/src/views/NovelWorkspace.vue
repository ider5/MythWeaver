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

function statusLabel(s?: string) {
  if (s === 'ready') return '就绪'
  if (s === 'ingesting') return '入库中'
  if (s === 'generating') return '生成中'
  if (s === 'imported') return '已导入'
  return s || ''
}

function statusTone(s?: string) {
  if (s === 'ready') return 'status-pill--ok'
  if (s === 'ingesting' || s === 'generating') return 'status-pill--busy'
  return 'status-pill--idle'
}

onMounted(async () => {
  const { data } = await novelsApi.get(id.value)
  novel.value = data
})
</script>

<template>
  <div>
    <div class="mb-5 flex items-end justify-between gap-4">
      <div class="min-w-0">
        <div class="mb-2">
          <RouterLink to="/" class="crumb">小说列表</RouterLink>
          <span class="crumb-sep">/</span>
          <span class="crumb">工作区</span>
        </div>
        <div class="page-title truncate">{{ novel?.title || '…' }}</div>
        <div class="page-desc tabular flex flex-wrap items-center gap-2">
          <span>{{ novel?.genre }} · {{ novel?.chapter_count }} 章</span>
          <span v-if="novel" class="status-pill" :class="statusTone(novel.status)">
            {{ statusLabel(novel.status) }}
          </span>
        </div>
      </div>
      <div class="flex gap-2 shrink-0">
        <button class="btn-ghost" title="导出为 TXT" @click="exportNovel('txt')">导出 TXT</button>
        <button class="btn-ghost" title="导出为 Markdown" @click="exportNovel('md')">导出 MD</button>
      </div>
    </div>
    <nav class="ws-tabs mb-6">
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
