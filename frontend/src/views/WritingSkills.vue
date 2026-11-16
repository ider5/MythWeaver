<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
  skillsApi,
  type SkillInstallResult,
  type SkillPreview,
  type WritingSkill,
  type WritingSkillCatalogItem,
  type WritingSkillStage,
} from '@/api'

const stages: { id: WritingSkillStage | 'all'; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'outline', label: '大纲' },
  { id: 'draft', label: '正文' },
  { id: 'critic', label: '审校' },
  { id: 'revise', label: '修稿' },
]

const skills = ref<WritingSkill[]>([])
const catalog = ref<WritingSkillCatalogItem[]>([])
const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const notice = ref('')
const stageFilter = ref<WritingSkillStage | 'all'>('all')
const mode = ref<'catalog' | 'paste'>('catalog')
const source = ref('')
const fileError = ref('')
const dragOver = ref(false)
const preview = ref<SkillPreview | null>(null)
const previewBasis = ref('')
const previewing = ref(false)
const installing = ref(false)
const busyId = ref<number | null>(null)
const confirmDeleteId = ref<number | null>(null)
const openBodyId = ref<number | null>(null)

const visible = computed(() => {
  const rows =
    stageFilter.value === 'all'
      ? skills.value
      : skills.value.filter((skill) => skill.stage === stageFilter.value)
  const order = ['outline', 'draft', 'critic', 'revise']
  return [...rows].sort((a, b) => order.indexOf(a.stage) - order.indexOf(b.stage) || a.id - b.id)
})

const canInstall = computed(() => {
  if (!preview.value?.ok || installing.value || previewing.value) return false
  if (preview.value.catalog_id) {
    return mode.value === 'catalog' && previewBasis.value === `catalog:${preview.value.catalog_id}`
  }
  return mode.value === 'paste' && previewBasis.value === `source:${source.value}`
})

const stalePreview = computed(
  () => Boolean(preview.value?.ok && previewBasis.value && !canInstall.value && !installing.value),
)

function apiError(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === 'string' ? item : (item as { msg?: string }).msg || ''))
      .filter(Boolean)
      .join('；')
  }
  if (typeof detail === 'string' && detail) return detail
  if (error instanceof Error && error.message) return error.message
  return '请求失败'
}

async function load() {
  loadError.value = ''
  try {
    const [installed, bundled] = await Promise.all([skillsApi.list(), skillsApi.catalog()])
    skills.value = installed.data
    catalog.value = bundled.data
  } catch (error: unknown) {
    loadError.value = apiError(error)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function clearPreview() {
  preview.value = null
  previewBasis.value = ''
}

function setMode(next: 'catalog' | 'paste') {
  if (mode.value === next) return
  mode.value = next
  clearPreview()
  fileError.value = ''
  actionError.value = ''
}

async function runPreview(body: { source?: string; catalog_id?: string }, basis: string) {
  previewing.value = true
  actionError.value = ''
  notice.value = ''
  fileError.value = ''
  try {
    const res = await skillsApi.preview(body)
    preview.value = res.data
    previewBasis.value = basis
  } catch (error: unknown) {
    preview.value = { ok: false, errors: [apiError(error)], already_installed: false }
    previewBasis.value = ''
  } finally {
    previewing.value = false
  }
}

function previewCatalog(id: string) {
  return runPreview({ catalog_id: id }, `catalog:${id}`)
}

function previewPaste() {
  const text = source.value
  if (!text.trim()) {
    fileError.value = '先粘贴或选择一份 SKILL.md。'
    return
  }
  return runPreview({ source: text }, `source:${text}`)
}

function readFile(file: File, extraCount = 0) {
  fileError.value = ''
  if (extraCount > 0) {
    fileError.value = '一次只读取一个文件，不会打开同目录的其他文件。'
    return
  }
  const name = file.name.toLowerCase()
  if (!name.endsWith('.md') && !name.endsWith('.markdown') && !name.endsWith('.txt')) {
    fileError.value = '只接受 SKILL.md 文本，不打开脚本。'
    return
  }
  if (file.size > 32768) {
    fileError.value = '文件超过 32KB，已拒绝。'
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    source.value = String(reader.result || '')
    mode.value = 'paste'
    clearPreview()
    fileError.value = ''
  }
  reader.onerror = () => {
    fileError.value = '没有读成文本。'
  }
  reader.readAsText(file, 'utf-8')
}

function onFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files
  if (!files?.length) return
  readFile(files[0], files.length - 1)
  input.value = ''
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  dragOver.value = false
  const files = event.dataTransfer?.files
  if (!files?.length) return
  readFile(files[0], files.length - 1)
}

async function install() {
  if (!canInstall.value || !preview.value?.ok) return
  installing.value = true
  actionError.value = ''
  notice.value = ''
  try {
    const replace = preview.value.already_installed
    const res = preview.value.catalog_id
      ? await skillsApi.install({ catalog_id: preview.value.catalog_id, replace })
      : await skillsApi.install({ source: source.value, replace })
    showInstalled(res.data)
    clearPreview()
    await load()
  } catch (error: unknown) {
    actionError.value = apiError(error)
  } finally {
    installing.value = false
  }
}

function showInstalled(row: SkillInstallResult) {
  notice.value = row.warning || (row.enabled ? `已安装「${row.description}」。` : `已保存「${row.description}」。`)
}

async function toggle(skill: WritingSkill) {
  busyId.value = skill.id
  actionError.value = ''
  notice.value = ''
  try {
    await skillsApi.update(skill.id, { enabled: !skill.enabled })
    await load()
  } catch (error: unknown) {
    actionError.value = apiError(error)
  } finally {
    busyId.value = null
  }
}

async function remove(skill: WritingSkill) {
  if (confirmDeleteId.value !== skill.id) {
    confirmDeleteId.value = skill.id
    return
  }
  busyId.value = skill.id
  actionError.value = ''
  try {
    await skillsApi.remove(skill.id)
    confirmDeleteId.value = null
    if (openBodyId.value === skill.id) openBodyId.value = null
    await load()
  } catch (error: unknown) {
    actionError.value = apiError(error)
  } finally {
    busyId.value = null
  }
}
</script>

<template>
  <div class="skills">
    <header class="skills__head">
      <p class="kicker">写法</p>
      <h1 class="page-title">阶段写法</h1>
      <p class="page-desc">
        一条写法只绑在大纲、正文、审校或修稿上。安装前先读完提示词。这里只保存文字，不运行脚本，也不打开同目录的其他文件。
        <RouterLink class="crumb" to="/settings/providers">模型在 LLM 设置。</RouterLink>
      </p>
    </header>

    <p v-if="notice" class="skills__notice" role="status">{{ notice }}</p>
    <p v-if="actionError" class="skills__notice skills__notice--bad" role="alert">{{ actionError }}</p>
    <p v-if="loadError" class="skills__notice skills__notice--bad" role="alert">{{ loadError }}</p>

    <div class="skills__grid">
      <section class="panel skills__installed" aria-labelledby="installed-skills">
        <div class="panel-head skills__bar">
          <h2 id="installed-skills">已安装</h2>
          <div class="skills__filters" role="tablist">
            <button
              v-for="item in stages"
              :key="item.id"
              type="button"
              class="chip"
              :class="{ 'chip--active': stageFilter === item.id }"
              :aria-pressed="stageFilter === item.id"
              @click="stageFilter = item.id"
            >
              {{ item.label }}
            </button>
          </div>
        </div>

        <div v-if="loading" class="skills__empty">正在读取已安装的写法…</div>
        <div v-else-if="!visible.length" class="skills__empty">
          还没有{{ stageFilter === 'all' ? '' : '这个阶段的' }}写法。右边先预览一条，确认文字后再安装。
        </div>
        <ul v-else class="skills__list">
          <li v-for="skill in visible" :key="skill.id" class="skill-card">
            <div class="skill-card__top">
              <div>
                <div class="skill-card__title">{{ skill.description }}</div>
                <div class="skill-card__meta">
                  <span class="badge" :class="skill.enabled ? 'badge--ok' : ''">{{ skill.stage_label }}</span>
                  <span class="skill-name">{{ skill.name }}</span>
                  <span v-if="skill.enabled && !skill.injected" class="badge badge--warn">超出篇幅，未写入提示</span>
                </div>
              </div>
              <button
                type="button"
                class="skill-switch"
                :aria-pressed="skill.enabled"
                :aria-label="skill.enabled ? '停用这条写法' : '启用这条写法'"
                :disabled="busyId === skill.id"
                @click="toggle(skill)"
              >
                <span aria-hidden="true" />
              </button>
            </div>
            <div class="skill-card__actions">
              <button type="button" class="btn-ghost btn-sm" @click="openBodyId = openBodyId === skill.id ? null : skill.id">
                {{ openBodyId === skill.id ? '收起提示词' : '查看提示词' }}
              </button>
              <button
                type="button"
                class="btn-danger btn-sm"
                :disabled="busyId === skill.id"
                @click="remove(skill)"
              >
                {{ confirmDeleteId === skill.id ? '确认删除' : '删除' }}
              </button>
            </div>
            <pre v-if="openBodyId === skill.id" class="skill-prose">{{ skill.body }}</pre>
          </li>
        </ul>
      </section>

      <section class="panel skills__install" aria-labelledby="install-skill">
        <div class="panel-head">
          <h2 id="install-skill">安装前先预览</h2>
        </div>
        <div class="skills__install-body">
          <div class="skills__filters" role="tablist">
            <button
              type="button"
              class="chip"
              :class="{ 'chip--active': mode === 'catalog' }"
              :aria-pressed="mode === 'catalog'"
              @click="setMode('catalog')"
            >
              示例
            </button>
            <button
              type="button"
              class="chip"
              :class="{ 'chip--active': mode === 'paste' }"
              :aria-pressed="mode === 'paste'"
              @click="setMode('paste')"
            >
              粘贴 SKILL.md
            </button>
          </div>

          <ul v-if="mode === 'catalog'" class="skills__catalog">
            <li v-for="item in catalog" :key="item.catalog_id" class="skill-card skill-card--compact">
              <div class="skill-card__title">{{ item.description }}</div>
              <div class="skill-card__meta">
                <span class="badge badge--ok">{{ item.stage_label }}</span>
                <span class="skill-name">{{ item.name }}</span>
                <span v-if="item.installed" class="badge">已安装</span>
              </div>
              <button
                type="button"
                class="btn-ghost btn-sm"
                :disabled="previewing"
                @click="previewCatalog(item.catalog_id)"
              >
                预览
              </button>
            </li>
          </ul>

          <div v-else class="skills__paste">
            <label class="skill-drop" :class="{ 'is-over': dragOver }" @dragover.prevent="dragOver = true" @dragleave="dragOver = false" @drop="onDrop">
              <span>把一个 .md 文件拖到这里，或点此选择。一次一个文件。</span>
              <input class="skill-file" type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" @change="onFileInput" />
            </label>
            <textarea
              v-model="source"
              class="textarea skill-source"
              spellcheck="false"
              placeholder="---&#10;name: chapter-hook&#10;description: 章末停在未完成的动作上&#10;stage: draft&#10;---&#10;提示词正文"
            />
            <button type="button" class="btn" :disabled="previewing || !source.trim()" @click="previewPaste">
              {{ previewing ? '正在读取…' : '预览这份文字' }}
            </button>
          </div>

          <p class="skills__fine">只保存提示词。不会运行脚本，也不会读取技能目录里的其他文件。预览不会调用模型。</p>
          <p v-if="fileError" class="skills__notice skills__notice--bad">{{ fileError }}</p>

          <div v-if="preview" class="skill-preview" :class="{ 'is-bad': !preview.ok }" aria-live="polite">
            <template v-if="preview.ok">
              <div class="skill-card__meta">
                <span class="badge badge--ok">{{ preview.stage_label }}</span>
                <span class="skill-name">{{ preview.name }}</span>
              </div>
              <div class="skill-card__title">{{ preview.description }}</div>
              <pre class="skill-prose">{{ preview.body }}</pre>
              <p v-if="preview.already_installed" class="skills__fine">
                已有同名写法。安装会覆盖提示词，阶段以这份文件为准。
              </p>
              <p v-if="stalePreview" class="skills__notice skills__notice--warn">文字已经改过，请重新预览后再安装。</p>
              <button type="button" class="btn" :disabled="!canInstall" @click="install">
                {{ installing ? '正在安装…' : preview.already_installed ? '覆盖安装' : '安装这条写法' }}
              </button>
            </template>
            <template v-else>
              <p class="skill-card__title">这份文件不能安装</p>
              <ul class="skills__errors">
                <li v-for="(err, index) in preview.errors" :key="index">{{ err }}</li>
              </ul>
            </template>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
