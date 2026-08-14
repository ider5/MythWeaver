<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { novelsApi, type ImportPreview } from '@/api'

const router = useRouter()
const step = ref<'upload' | 'preview'>('upload')
const mode = ref<'file' | 'dir'>('file')
const title = ref('')
const author = ref('')
const genre = ref('玄幻')
const preview = ref<ImportPreview | null>(null)
const busy = ref(false)
const error = ref('')

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return
  busy.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('title', title.value || input.files[0].name.replace(/\.\w+$/, ''))
    if (mode.value === 'dir') {
      for (const f of Array.from(input.files)) {
        form.append('files', f)
      }
    } else {
      form.append('file', input.files[0])
    }
    const { data } = await novelsApi.previewImport(form)
    preview.value = data
    if (!title.value) title.value = data.title
    step.value = 'preview'
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || '预览失败'
  } finally {
    busy.value = false
  }
}

async function confirm() {
  if (!preview.value) return
  busy.value = true
  error.value = ''
  try {
    const { data: novel } = await novelsApi.confirmImport({
      import_token: preview.value.import_token,
      title: title.value,
      author: author.value || undefined,
      genre: genre.value,
    })
    const { data: task } = await novelsApi.ingest(novel.id)
    router.push(`/novels/${novel.id}/ingest/${task.task_id}`)
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || '确认失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="max-w-3xl">
    <div class="kicker mb-2">导入</div>
    <h1 class="page-title mb-1">导入向导</h1>
    <p class="page-desc mb-5">支持单文件全文，或目录多文件分章导入；确认后自动入库。</p>

    <ol class="steps" aria-label="导入步骤">
      <li class="steps__item" :class="step === 'upload' ? 'steps__item--active' : 'steps__item--done'">
        1 选择文件
      </li>
      <li class="steps__item" :class="step === 'preview' && 'steps__item--active'">2 确认分章</li>
    </ol>

    <div v-if="step === 'upload'" class="panel p-6 space-y-5">
      <div class="flex gap-2 text-sm">
        <label
          class="tab-btn cursor-pointer"
          :class="mode === 'file' && 'tab-btn--active'"
        >
          <input v-model="mode" type="radio" value="file" class="sr-only" /> 单文件
        </label>
        <label
          class="tab-btn cursor-pointer"
          :class="mode === 'dir' && 'tab-btn--active'"
        >
          <input v-model="mode" type="radio" value="dir" class="sr-only" /> 多文件/目录
        </label>
      </div>
      <div>
        <label class="label">标题（可选）</label>
        <input v-model="title" class="input" placeholder="自动取文件名" />
      </div>
      <div>
        <label class="label">选择文件</label>
        <label class="dropzone cursor-pointer w-full">
          <span class="dropzone__icon" aria-hidden="true">文</span>
          <span class="font-medium">{{ mode === 'dir' ? '选择文件夹中的 txt / md' : '选择一个 txt / md 文件' }}</span>
          <span class="meta">点击此区域选择 · 确认后进入分章预览</span>
          <input
            type="file"
            class="dropzone__input"
            :multiple="mode === 'dir'"
            :webkitdirectory="mode === 'dir' ? true : undefined"
            accept=".txt,.md,.text"
            @change="onFileChange"
          />
        </label>
      </div>
      <p v-if="busy" class="empty">解析分章中…</p>
      <p v-if="error" class="alert alert--danger">{{ error }}</p>
    </div>

    <div v-else-if="preview" class="space-y-4">
      <div class="panel p-5 grid gap-4 sm:grid-cols-2">
        <div>
          <label class="label">标题</label>
          <input v-model="title" class="input" />
        </div>
        <div>
          <label class="label">作者</label>
          <input v-model="author" class="input" />
        </div>
        <div>
          <label class="label">题材</label>
          <select v-model="genre" class="input">
            <option>玄幻</option>
            <option>都市</option>
            <option>言情</option>
          </select>
        </div>
        <div class="meta self-end tabular">共 {{ preview.chapter_count }} 章 · {{ preview.total_chars }} 字</div>
      </div>

      <div class="panel overflow-hidden">
        <div class="panel-head">分章预览（请确认标题是否正确）</div>
        <ul class="max-h-96 overflow-auto list-divide">
          <li v-for="c in preview.chapters" :key="c.index" class="cv-item px-4 py-3">
            <div class="text-sm font-medium">{{ c.index }}. {{ c.title }}</div>
            <div class="meta mt-1 tabular">
              <span v-if="c.volume">{{ c.volume }} · </span>{{ c.char_count }} 字
            </div>
            <div class="meta mt-1 line-clamp-2">{{ c.preview }}</div>
          </li>
        </ul>
      </div>

      <div class="flex gap-3">
        <button class="btn-ghost" :disabled="busy" @click="step = 'upload'">返回</button>
        <button class="btn" :disabled="busy" @click="confirm">确认并入库</button>
      </div>
      <p v-if="error" class="alert alert--danger">{{ error }}</p>
    </div>
  </div>
</template>
