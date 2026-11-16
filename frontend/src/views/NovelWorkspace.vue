<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { novelsApi, tasksApi, type Novel, type Task } from '@/api'

defineOptions({ name: 'NovelWorkspace' })

const route = useRoute()
const novel = ref<Novel | null>(null)
const id = computed(() => Number(route.params.id))
const activeTasks = ref<Task[]>([])
let taskPoll = 0

const activeSummary = computed(() => {
  const n = activeTasks.value.length
  if (!n) return ''
  const first = activeTasks.value[0]
  const label =
    first.task_type === 'ingest'
      ? '入库'
      : first.task_type === 'outline_generate'
        ? '大纲'
        : first.task_type === 'batch_generate'
          ? '连续生成'
          : first.task_type === 'revise_commit'
            ? '修订入库'
            : first.task_type
  const more = n > 1 ? ` 等 ${n} 项` : ''
  return `${label}${more}：${first.message || '进行中'} ${Math.round(Number(first.progress) || 0)}%`
})

async function refreshActiveTasks() {
  try {
    const { data } = await tasksApi.list(id.value)
    activeTasks.value = data.filter((t) => t.status === 'pending' || t.status === 'running')
  } catch {
    /* ignore poll errors */
  }
}

const allTabs = [
  { name: 'bible', label: '设定', path: 'bible' },
  { name: 'outline', label: '大纲', path: 'outline' },
  { name: 'write', label: '续写', path: 'write' },
  { name: 'costs', label: '用量', path: 'costs' },
  { name: 'tasks', label: '任务', path: 'tasks' },
]
const isReference = computed(() => novel.value?.role === 'reference')
const tabs = computed(() =>
  isReference.value ? allTabs.filter((t) => t.name !== 'write') : allTabs,
)

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
  await refreshActiveTasks()
  taskPoll = window.setInterval(() => {
    if (document.visibilityState === 'hidden') return
    refreshActiveTasks()
  }, 2500)
})

onUnmounted(() => {
  if (taskPoll) window.clearInterval(taskPoll)
})
</script>

<template>
  <div class="ws">
    <header class="ws-head ws-head--visual">
      <div class="min-w-0">
        <div class="mb-2">
          <RouterLink to="/" class="crumb">作品</RouterLink>
          <span class="crumb-sep">/</span>
          <span class="crumb">{{ isReference ? '参考拆解' : '续写工作台' }}</span>
        </div>
        <h1 class="page-title truncate">{{ novel?.title || '…' }}</h1>
        <div class="page-desc tabular flex flex-wrap items-center gap-2">
          <span>{{ novel?.genre }} · {{ novel?.chapter_count }} 章</span>
          <span v-if="novel" class="badge" :class="isReference ? 'badge--warn' : 'badge--ok'">
            {{ isReference ? '参考' : '原稿' }}
          </span>
          <span v-if="novel" class="status-pill" :class="statusTone(novel.status)">
            {{ statusLabel(novel.status) }}
          </span>
        </div>
        <p v-if="isReference" class="page-desc">
          参考小说只拆设定与文风，不会作为续写正文，也不能导出成书。
        </p>
      </div>
      <div v-if="novel && !isReference" class="flex gap-2 shrink-0">
        <button class="btn-ghost" type="button" title="导出为 TXT" @click="exportNovel('txt')">
          导出
        </button>
      </div>
    </header>
    <nav class="ws-tabs mb-6" aria-label="作品分区">
      <RouterLink
        v-for="t in tabs"
        :key="t.name"
        :to="`/novels/${id}/${t.path}`"
        class="ws-tab"
      >
        {{ t.label }}
      </RouterLink>
    </nav>
    <div v-if="activeSummary" class="ws-live panel px-4 py-3 mb-4 flex items-center justify-between gap-3">
      <p class="page-desc m-0 truncate" role="status">{{ activeSummary }}</p>
      <RouterLink class="btn-ghost shrink-0" :to="`/novels/${id}/tasks`">查看进度</RouterLink>
    </div>
    <RouterView v-slot="{ Component }">
      <Transition name="pane" mode="out-in">
        <KeepAlive :max="8">
          <component :is="Component" />
        </KeepAlive>
      </Transition>
    </RouterView>
  </div>
</template>
