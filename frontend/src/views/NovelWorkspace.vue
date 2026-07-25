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

onMounted(async () => {
  const { data } = await novelsApi.get(id.value)
  novel.value = data
})
</script>

<template>
  <div>
    <div class="mb-4">
      <div class="font-display text-3xl">{{ novel?.title || '…' }}</div>
      <div class="text-xs mt-1" style="color: var(--ink-muted)">
        {{ novel?.genre }} · {{ novel?.chapter_count }} 章 · {{ novel?.status }}
      </div>
    </div>
    <nav class="flex gap-1 mb-5 border-b" style="border-color: var(--line)">
      <RouterLink
        v-for="t in tabs"
        :key="t.name"
        :to="`/novels/${id}/${t.path}`"
        class="px-3 py-2 text-sm"
        :class="route.name === t.name ? 'border-b-2' : ''"
        :style="route.name === t.name ? { borderColor: 'var(--accent)', color: 'var(--accent)' } : { color: 'var(--ink-muted)' }"
      >
        {{ t.label }}
      </RouterLink>
    </nav>
    <RouterView />
  </div>
</template>
