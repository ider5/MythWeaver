<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { novelsApi, type ImportPreview } from '@/api'
import ImportRoleChoice from '@/components/ImportRoleChoice.vue'

const router = useRouter()
const route = useRoute()
const step = ref<'upload' | 'preview'>('upload')
const mode = ref<'file' | 'dir'>('file')
const novelRole = ref<'manuscript' | 'reference'>('manuscript')
const roleQuery = route.query.role
if (roleQuery === 'manuscript' || roleQuery === 'reference') {
  novelRole.value = roleQuery
}
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
      role: novelRole.value,
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
  <div class="wizard max-w-3xl">
    <p class="kicker mb-2">MythWeaver</p>
    <h1 class="page-title mb-1">导入小说</h1>
    <p class="page-desc">
      先选用途。原稿可以接着写；参考只拆文风，不会变成正文。没有原稿？
      <RouterLink to="/create">从零开书</RouterLink>
    </p>

    <ImportRoleChoice v-model="novelRole" />

    <p class="wizard-phase">{{ step === 'upload' ? '1 / 2  选择文件' : '2 / 2  确认分章' }}</p>

    <div :key="step" class="wizard-pane">
      <div v-if="step === 'upload'" class="space-y-4">
        <div class="mode-line" role="group" aria-label="文件范围">
          <button
            type="button"
            :aria-pressed="mode === 'file'"
            :class="{ 'is-on': mode === 'file' }"
            @click="mode = 'file'"
          >
            单个文件
          </button>
          <button
            type="button"
            :aria-pressed="mode === 'dir'"
            :class="{ 'is-on': mode === 'dir' }"
            @click="mode = 'dir'"
          >
            文件夹
          </button>
        </div>
        <label class="dropzone cursor-pointer w-full">
          <span class="dropzone__icon" aria-hidden="true">文</span>
          <span class="font-medium">
            {{ mode === 'dir' ? '选择文件夹里的 txt / md' : '选择一个 txt / md 文件' }}
          </span>
          <span class="meta">点此选择。书名先用文件名，下一步再改。</span>
          <input
            type="file"
            class="dropzone__input"
            :multiple="mode === 'dir'"
            :webkitdirectory="mode === 'dir' ? true : undefined"
            accept=".txt,.md,.text"
            @change="onFileChange"
          />
        </label>
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
          <div class="panel-head">分章预览</div>
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
          <button class="btn-ghost" type="button" :disabled="busy" @click="step = 'upload'">返回</button>
          <button class="btn" type="button" :disabled="busy" @click="confirm">
            {{ busy ? '入库中…' : novelRole === 'reference' ? '作为参考入库' : '作为原稿入库' }}
          </button>
        </div>
        <p v-if="error" class="alert alert--danger">{{ error }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wizard-phase {
  margin: 0 0 0.85rem;
  font-size: 0.78rem;
  font-weight: 650;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
}

.mode-line {
  display: flex;
  gap: 1.25rem;
}

.mode-line button {
  padding: 0 0 0.2rem;
  border: 0;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--ink-muted);
  font: inherit;
  font-size: 0.875rem;
  font-weight: 650;
  cursor: pointer;
}

.mode-line button.is-on {
  color: var(--ink);
  border-bottom-color: var(--accent);
}

.mode-line button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}

.wizard-pane {
  animation: wizard-in 280ms ease;
}

@keyframes wizard-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
