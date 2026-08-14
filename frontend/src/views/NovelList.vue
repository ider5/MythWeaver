<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { novelsApi, type Novel } from '@/api'

const novels = ref<Novel[]>([])
const loading = ref(true)
const error = ref('')
const router = useRouter()

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await novelsApi.list()
    novels.value = data
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function remove(n: Novel) {
  if (!confirm(`删除《${n.title}》？`)) return
  await novelsApi.remove(n.id)
  await load()
}

function exportNovel(n: Novel, format: 'txt' | 'md' = 'txt') {
  window.open(novelsApi.exportUrl(n.id, format), '_blank')
}

function statusLabel(s: string) {
  if (s === 'ready') return '就绪'
  if (s === 'ingesting') return '入库中'
  if (s === 'generating') return '生成中'
  if (s === 'imported') return '已导入'
  return s
}

function statusTone(s: string) {
  if (s === 'ready') return 'status-pill--ok'
  if (s === 'ingesting' || s === 'generating') return 'status-pill--busy'
  return 'status-pill--idle'
}

function fmtNum(n: number) {
  return Number(n || 0).toLocaleString('zh-CN')
}

onMounted(load)
</script>

<template>
  <div>
    <div class="flex items-end justify-between gap-4 mb-8">
      <div>
        <div class="kicker mb-2">工作台</div>
        <h1 class="page-title">你的小说</h1>
        <p class="page-desc">导入原文 → 入库压缩 → 大纲 → 逐章续写</p>
      </div>
      <button class="btn" @click="router.push('/import')">导入小说</button>
    </div>

    <div v-if="loading" class="space-y-3" aria-busy="true" aria-live="polite">
      <span class="sr-only">加载中…</span>
      <div v-for="i in 3" :key="i" class="skeleton h-[4.75rem]" />
    </div>
    <p v-else-if="error" class="alert alert--danger">{{ error }}</p>
    <div v-else-if="!novels.length" class="empty-state">
      <div>
        <div class="font-display text-xl">还没有作品</div>
        <p class="page-desc">导入一部原文，即可开始摘要、Story Bible 与续写。</p>
      </div>
      <button class="btn" @click="router.push('/import')">导入一部</button>
    </div>

    <ul v-else class="space-y-3">
      <li
        v-for="n in novels"
        :key="n.id"
        class="panel panel-hover cv-item px-5 py-4 flex items-center justify-between gap-4 cursor-pointer"
        @click="router.push(`/novels/${n.id}/bible`)"
      >
        <div class="min-w-0">
          <div class="flex items-center gap-2 min-w-0">
            <div class="font-display text-lg leading-snug truncate">{{ n.title }}</div>
            <span class="status-pill shrink-0" :class="statusTone(n.status)">{{ statusLabel(n.status) }}</span>
          </div>
          <div class="stat-row meta tabular">
            <span>{{ n.genre }}</span>
            <span>{{ fmtNum(n.chapter_count) }} 章</span>
            <span>{{ fmtNum(n.total_chars) }} 字</span>
            <span v-if="n.author">{{ n.author }}</span>
          </div>
        </div>
        <div class="flex gap-2 shrink-0" @click.stop>
          <button class="btn-ghost" @click="router.push(`/novels/${n.id}/write`)">续写</button>
          <button class="btn-ghost" title="导出为 TXT" @click="exportNovel(n, 'txt')">导出</button>
          <button class="btn-danger" @click="remove(n)">删除</button>
        </div>
      </li>
    </ul>
  </div>
</template>
