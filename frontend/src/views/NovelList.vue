<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { novelsApi, type Novel } from '@/api'
import BlankNovelForm from '@/components/BlankNovelForm.vue'
import EmptyState from '@/components/EmptyState.vue'

const novels = ref<Novel[]>([])
const loading = ref(true)
const error = ref('')
const filter = ref<'manuscript' | 'reference' | 'all'>('manuscript')
const showCreate = ref(false)
const router = useRouter()

function isReference(n: Novel) {
  return n.role === 'reference'
}

const manuscriptCount = computed(() => novels.value.filter((n) => !isReference(n)).length)
const referenceCount = computed(() => novels.value.filter((n) => isReference(n)).length)
const manuscriptNovels = computed(() => novels.value.filter((n) => !isReference(n)))
const visible = computed(() => {
  if (filter.value === 'all') return novels.value
  if (filter.value === 'reference') return novels.value.filter((n) => isReference(n))
  return manuscriptNovels.value
})

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

function openNovel(n: Novel) {
  if (isReference(n)) {
    router.push(`/novels/${n.id}/bible`)
    return
  }
  router.push(`/novels/${n.id}/write`)
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
  <div class="home">
    <section class="home-hero" aria-labelledby="home-brand">
      <p id="home-brand" class="home-brand">MythWeaver</p>
      <h1 class="home-headline">长篇续写，压进一条清晰路径</h1>
      <span class="home-rule" aria-hidden="true"></span>
      <p class="home-lede">导入原稿或参考，入库压缩后确认大纲，再流式续写。界面只留必要动作。</p>
      <div class="home-cta">
        <button class="btn" type="button" @click="router.push('/import')">导入续写</button>
        <button
          v-if="manuscriptNovels.length"
          class="btn-ghost"
          type="button"
          @click="openNovel(manuscriptNovels[0])"
        >
          打开最近原稿
        </button>
      </div>
    </section>

    <section class="home-shelf" aria-labelledby="shelf-title">
      <div class="home-shelf__head">
        <h2 id="shelf-title" class="home-shelf__title">作品</h2>
        <button class="btn-ghost btn-sm" type="button" @click="router.push('/import')">导入</button>
      </div>

      <div class="flex flex-wrap gap-2 mb-5" role="tablist" aria-label="按用途筛选">
        <button
          class="chip"
          type="button"
          role="tab"
          :aria-selected="filter === 'manuscript'"
          :class="filter === 'manuscript' && 'chip--active'"
          @click="filter = 'manuscript'"
        >
          原稿 {{ manuscriptCount }}
        </button>
        <button
          class="chip"
          type="button"
          role="tab"
          :aria-selected="filter === 'reference'"
          :class="filter === 'reference' && 'chip--active'"
          @click="filter = 'reference'"
        >
          参考 {{ referenceCount }}
        </button>
        <button
          class="chip"
          type="button"
          role="tab"
          :aria-selected="filter === 'all'"
          :class="filter === 'all' && 'chip--active'"
          @click="filter = 'all'"
        >
          全部
        </button>
      </div>

      <div v-if="loading" class="space-y-3" aria-busy="true" aria-live="polite">
        <span class="sr-only">加载中…</span>
        <div v-for="i in 3" :key="i" class="skeleton h-[4.75rem]" />
      </div>
      <p v-else-if="error" class="alert alert--danger">{{ error }}</p>
      <EmptyState
        v-else-if="!novels.length"
        title="书架还是空的"
        body="导入一部原文就能续写。也可以先建一本空白原稿，从大纲写起。"
        primary="导入小说"
        primary-to="/import"
        secondary="新建原稿"
        @secondary="showCreate = true"
      >
        <BlankNovelForm v-if="showCreate" />
      </EmptyState>
      <EmptyState
        v-else-if="!visible.length && filter === 'manuscript'"
        title="默认续写里没有原稿"
        body="参考小说只拆文风，不会出现在这里。导入一部原稿，或新建空白书开始写。"
        primary="导入原稿"
        primary-to="/import?role=manuscript"
        secondary="新建原稿"
        @secondary="showCreate = true"
      >
        <BlankNovelForm v-if="showCreate" />
      </EmptyState>
      <EmptyState
        v-else-if="!visible.length"
        title="还没有参考小说"
        body="导入时选「参考」，只拆结构与文风，不会变成可续写正文。"
        primary="导入参考"
        primary-to="/import?role=reference"
      />

      <ul v-else :key="filter" class="space-y-3">
        <li
          v-for="(n, index) in visible"
          :key="n.id"
          class="panel panel-hover home-row px-5 py-4 flex items-center justify-between gap-4 cursor-pointer"
          :style="{ '--i': Math.min(index, 8) }"
          @click="openNovel(n)"
        >
          <div class="min-w-0">
            <div class="flex items-center gap-2 min-w-0">
              <div class="font-display text-lg leading-snug truncate">{{ n.title }}</div>
              <span class="badge shrink-0" :class="isReference(n) ? 'badge--warn' : 'badge--ok'">
                {{ isReference(n) ? '参考' : '原稿' }}
              </span>
              <span class="status-pill shrink-0" :class="statusTone(n.status)">{{
                statusLabel(n.status)
              }}</span>
            </div>
            <div class="stat-row meta tabular">
              <span>{{ n.genre }}</span>
              <span>{{ fmtNum(n.chapter_count) }} 章</span>
              <span>{{ fmtNum(n.total_chars) }} 字</span>
              <span v-if="n.author">{{ n.author }}</span>
            </div>
          </div>
          <div class="flex gap-2 shrink-0" @click.stop>
            <button
              v-if="!isReference(n)"
              class="btn"
              type="button"
              @click="openNovel(n)"
            >
              续写
            </button>
            <button v-else class="btn-ghost" type="button" @click="openNovel(n)">拆解</button>
            <button
              v-if="!isReference(n)"
              class="btn-ghost"
              type="button"
              title="导出为 TXT"
              @click="exportNovel(n, 'txt')"
            >
              导出
            </button>
            <button class="btn-danger" type="button" @click="remove(n)">删除</button>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
