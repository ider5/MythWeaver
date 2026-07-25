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

onMounted(load)
</script>

<template>
  <div>
    <div class="flex items-end justify-between mb-6">
      <div>
        <h1 class="font-display text-3xl mb-1">小说工作台</h1>
        <p class="text-sm" style="color: var(--ink-muted)">导入原文 → 入库 → 大纲 → 逐章续写</p>
      </div>
      <button class="btn" @click="router.push('/import')">导入小说</button>
    </div>

    <p v-if="loading" class="text-sm" style="color: var(--ink-muted)">加载中…</p>
    <p v-else-if="error" class="text-sm" style="color: var(--danger)">{{ error }}</p>
    <p v-else-if="!novels.length" class="text-sm" style="color: var(--ink-muted)">
      还没有小说，先
      <button class="underline" @click="router.push('/import')">导入一部</button>
    </p>

    <ul v-else class="space-y-3">
      <li
        v-for="n in novels"
        :key="n.id"
        class="panel px-4 py-3 flex items-center justify-between gap-4 cursor-pointer"
        @click="router.push(`/novels/${n.id}/bible`)"
      >
        <div>
          <div class="font-display text-xl">{{ n.title }}</div>
          <div class="text-xs mt-1" style="color: var(--ink-muted)">
            {{ n.genre }} · {{ n.chapter_count }} 章 · {{ n.total_chars }} 字 · {{ n.status }}
            <span v-if="n.author"> · {{ n.author }}</span>
          </div>
        </div>
        <div class="flex gap-2" @click.stop>
          <button class="btn-ghost" @click="router.push(`/novels/${n.id}/write`)">续写</button>
          <button class="btn-ghost" @click="remove(n)">删除</button>
        </div>
      </li>
    </ul>
  </div>
</template>
