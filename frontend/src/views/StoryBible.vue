<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  bibleApi,
  type Character,
  type PlotThread,
  type WorldSetting,
} from '@/api'
import EmptyState from '@/components/EmptyState.vue'
import RelationGraph from '@/components/RelationGraph.vue'
import ThreadTimeline from '@/components/ThreadTimeline.vue'
import WritebackReview from '@/components/WritebackReview.vue'
import {
  formatRelationshipInput,
  parseChapterField,
  parseRelationshipInput,
  threadSpan,
} from '@/lib/bibleViz'

type BibleTab = 'characters' | 'world' | 'threads'

interface EditTarget {
  type: BibleTab
  id: number | null
}

interface BibleForm {
  name: string
  aliases: string
  role: string
  status: string
  personality: string
  speech_style: string
  category: string
  title: string
  content: string
  do_not_violate: string
  description: string
  thread_type: string
  introduced_chapter: string
  resolved_chapter: string
}

interface RelRow {
  key: number
  name: string
  relation: string
}

const WORLD_PRESETS = ['力量体系', '地理', '组织', '规则']
const THREAD_TYPES = ['伏笔', '主线', '支线']
const THREAD_STATUSES = ['未回收', '已回收']

const route = useRoute()
const novelId = Number(route.params.id)
const tab = ref<BibleTab>('characters')
const characters = ref<Character[]>([])
const worlds = ref<WorldSetting[]>([])
const threads = ref<PlotThread[]>([])
const editing = ref<EditTarget | null>(null)
const form = ref<BibleForm>(emptyForm())
const formError = ref('')
const loadError = ref('')
const ready = ref(false)
const busy = ref(false)
const query = ref('')
const activeCharacterId = ref<number | null>(null)
const activeWorldId = ref<number | null>(null)
const activeThreadId = ref<number | null>(null)
const relMode = ref<'rows' | 'raw'>('rows')
const relRows = ref<RelRow[]>([])
const relRaw = ref('')
let relSeq = 0

const listCount = computed(() =>
  tab.value === 'characters'
    ? characters.value.length
    : tab.value === 'world'
      ? worlds.value.length
      : threads.value.length,
)
const isEmpty = computed(() => listCount.value === 0)
const showFind = computed(() => listCount.value >= 6 || query.value.trim().length > 0)
const createLabel = computed(() =>
  tab.value === 'characters' ? '新人物' : tab.value === 'world' ? '新设定' : '新伏笔',
)
const railLabel = computed(() =>
  tab.value === 'characters' ? '人物' : tab.value === 'world' ? '设定' : '伏笔',
)
const findPlaceholder = computed(() =>
  tab.value === 'characters' ? '筛选姓名或身份' : tab.value === 'world' ? '筛选标题' : '筛选伏笔',
)
const countLabel = computed(() => {
  const q = query.value.trim()
  const shown =
    tab.value === 'characters'
      ? shownCharacters.value.length
      : tab.value === 'world'
        ? shownWorlds.value.length
        : shownThreads.value.length
  if (q) return `${shown}/${listCount.value}`
  return String(listCount.value)
})
const sheetKicker = computed(() => (editing.value?.id ? '正在编辑' : '新建'))
const sheetHeading = computed(() => {
  const mode = editing.value
  if (!mode) return ''
  if (!mode.id) {
    if (mode.type === 'characters') return '人物'
    if (mode.type === 'world') return '世界观'
    return '伏笔线'
  }
  if (mode.type === 'characters') return form.value.name.trim() || '未命名'
  return form.value.title.trim() || '未命名'
})
const worldChoices = computed(() => choices(WORLD_PRESETS, form.value.category))
const threadTypeChoices = computed(() => choices(THREAD_TYPES, form.value.thread_type))
const threadStatusChoices = computed(() => choices(THREAD_STATUSES, form.value.status))
const graphActiveId = computed(() =>
  editing.value?.type === 'characters' && editing.value.id == null ? null : activeCharacterId.value,
)
const timelineActiveId = computed(() =>
  editing.value?.type === 'threads' && editing.value.id == null ? null : activeThreadId.value,
)

const shownCharacters = computed(() => filterRows(characters.value, (row) => [row.name, row.role, row.status, ...(row.aliases || [])]))
const shownWorlds = computed(() => filterRows(worlds.value, (row) => [row.title, row.category, row.content]))
const shownThreads = computed(() => filterRows(threads.value, (row) => [row.title, row.thread_type, row.status, row.description]))

const selectedCharacter = computed(
  () => characters.value.find((row) => row.id === activeCharacterId.value) || null,
)
const selectedWorld = computed(() => worlds.value.find((row) => row.id === activeWorldId.value) || null)
const selectedThread = computed(() => threads.value.find((row) => row.id === activeThreadId.value) || null)
const selectedPairs = computed(() =>
  selectedCharacter.value ? pairList(selectedCharacter.value.relationships) : [],
)

const emptyCopy = computed(() => {
  if (tab.value === 'characters') {
    return {
      title: '还没有人物',
      body: '入库后会抽到这里。也可以先写一张人物卡，能对上的关系会画进旁边的图。',
    }
  }
  if (tab.value === 'world') {
    return {
      title: '还没有设定',
      body: '力量、地理、组织和不能打破的规则，都记在这里。',
    }
  }
  return {
    title: '还没有伏笔线',
    body: '写上出现章节或回收章节后，下面会按章排成时间线。',
  }
})

function emptyForm(): BibleForm {
  return {
    name: '',
    aliases: '',
    role: '',
    status: '',
    personality: '',
    speech_style: '',
    category: '规则',
    title: '',
    content: '',
    do_not_violate: '',
    description: '',
    thread_type: '伏笔',
    introduced_chapter: '',
    resolved_chapter: '',
  }
}

function choices(presets: string[], current: string) {
  const value = current.trim()
  return value && !presets.includes(value) ? [value, ...presets] : presets
}

function filterRows<T>(rows: T[], parts: (row: T) => Array<string | null | undefined>) {
  const q = query.value.trim().toLowerCase()
  if (!q) return rows
  return rows.filter((row) =>
    parts(row)
      .filter((part) => part && String(part).trim())
      .join('\n')
      .toLowerCase()
      .includes(q),
  )
}

function canUseRows(text: string) {
  const raw = text.trim()
  if (!raw) return true
  if (raw.startsWith('{') || raw.startsWith('[')) return false
  return parseRelationshipInput(raw).ok
}

function textToRows(text: string): RelRow[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.search(/[:：]/)
      return {
        key: ++relSeq,
        name: line.slice(0, idx).trim(),
        relation: line.slice(idx + 1).trim(),
      }
    })
}

function loadRel(rel: unknown) {
  const text = formatRelationshipInput(rel)
  relRaw.value = text
  if (canUseRows(text)) {
    relMode.value = 'rows'
    relRows.value = textToRows(text)
  } else {
    relMode.value = 'raw'
    relRows.value = []
  }
}

function relationshipsPayloadText() {
  if (relMode.value === 'raw') return relRaw.value
  return relRows.value
    .map((row) => ({ name: row.name.trim(), relation: row.relation.trim() }))
    .filter((row) => row.name || row.relation)
    .map((row) => `${row.name}：${row.relation}`)
    .join('\n')
}

function pairList(rel: unknown): { name: string; relation: string }[] | null {
  const text = formatRelationshipInput(rel).trim()
  if (!text) return []
  if (!canUseRows(text)) return null
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.search(/[:：]/)
      return { name: line.slice(0, idx).trim(), relation: line.slice(idx + 1).trim() }
    })
}

function characterMeta(row: Character) {
  const parts: string[] = []
  if (row.role) parts.push(row.role)
  if (row.status) parts.push(row.status)
  const aliases = (row.aliases || []).filter(Boolean)
  if (aliases.length) parts.push(`别称 ${aliases.join('、')}`)
  if (row.last_appear_chapter) parts.push(`最近出现在第 ${row.last_appear_chapter} 章`)
  return parts.join(' · ')
}

function hasCharacterBody(row: Character) {
  return Boolean(row.personality || row.speech_style || formatRelationshipInput(row.relationships).trim())
}

function threadMeta(row: PlotThread) {
  const span = threadSpan(row)
  return [row.thread_type, row.status, span].filter(Boolean).join(' · ')
}

function splitAliases(raw: unknown) {
  return String(raw || '')
    .split(/[、,，]/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function errorText(err: unknown) {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string }
  const detail = e.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((item) =>
        item && typeof item === 'object' && 'msg' in item ? String((item as { msg: unknown }).msg) : '',
      )
      .filter(Boolean)
    if (msgs.length) return msgs.join('；')
  }
  return e.message || '保存失败'
}

function createdId(data: unknown) {
  if (data && typeof data === 'object' && 'id' in data && typeof (data as { id: unknown }).id === 'number') {
    return (data as { id: number }).id
  }
  return null
}

function reveal(id?: string) {
  nextTick(() => {
    if (id) document.getElementById(id)?.focus()
    document.getElementById('bible-form-error')?.scrollIntoView({ block: 'nearest' })
  })
}

function focusFirst() {
  nextTick(() => {
    const root = document.getElementById('bible-sheet')
    root?.querySelector<HTMLElement>('input, textarea, select')?.focus()
    root?.scrollIntoView({ block: 'nearest' })
  })
}

function guardSwitch(type: BibleTab, id: number | null) {
  const current = editing.value
  if (!current) return true
  if (current.type === type && current.id === id) return true
  formError.value = '先保存或取消当前编辑'
  reveal()
  return false
}

function ensureSelection() {
  if (tab.value === 'characters') {
    if (!characters.value.some((row) => row.id === activeCharacterId.value)) {
      activeCharacterId.value = characters.value[0]?.id ?? null
    }
  } else if (tab.value === 'world') {
    if (!worlds.value.some((row) => row.id === activeWorldId.value)) {
      activeWorldId.value = worlds.value[0]?.id ?? null
    }
  } else if (!threads.value.some((row) => row.id === activeThreadId.value)) {
    activeThreadId.value = threads.value[0]?.id ?? null
  }
}

async function load() {
  try {
    const { data } = await bibleApi.get(novelId)
    characters.value = data.characters
    worlds.value = data.world_settings
    threads.value = data.plot_threads
    loadError.value = ''
    ensureSelection()
  } catch (err) {
    loadError.value = errorText(err)
  } finally {
    ready.value = true
  }
}

function setTab(next: BibleTab) {
  if (tab.value === next) return
  if (!guardSwitch(next, null)) return
  tab.value = next
  query.value = ''
  formError.value = ''
  ensureSelection()
}

function cancelEdit() {
  if (busy.value) return
  editing.value = null
  formError.value = ''
}

function startCreate() {
  if (editing.value) {
    formError.value = '先保存或取消当前编辑'
    reveal()
    return
  }
  formError.value = ''
  editing.value = { type: tab.value, id: null }
  form.value = emptyForm()
  if (tab.value === 'characters') loadRel(null)
  focusFirst()
}

function startEditCharacter(row: Character) {
  if (!guardSwitch('characters', row.id)) return
  activeCharacterId.value = row.id
  formError.value = ''
  editing.value = { type: 'characters', id: row.id }
  form.value = {
    ...emptyForm(),
    name: row.name || '',
    aliases: Array.isArray(row.aliases) ? row.aliases.join('、') : '',
    role: row.role || '',
    status: row.status || '',
    personality: row.personality || '',
    speech_style: row.speech_style || '',
  }
  loadRel(row.relationships)
  focusFirst()
}

function startEditWorld(row: WorldSetting) {
  if (!guardSwitch('world', row.id)) return
  activeWorldId.value = row.id
  formError.value = ''
  editing.value = { type: 'world', id: row.id }
  form.value = {
    ...emptyForm(),
    category: row.category || '规则',
    title: row.title || '',
    content: row.content || '',
    do_not_violate: row.do_not_violate || '',
  }
  focusFirst()
}

function startEditThread(row: PlotThread) {
  if (!guardSwitch('threads', row.id)) return
  activeThreadId.value = row.id
  formError.value = ''
  editing.value = { type: 'threads', id: row.id }
  form.value = {
    ...emptyForm(),
    title: row.title || '',
    description: row.description || '',
    thread_type: row.thread_type || '伏笔',
    status: row.status || '未回收',
    introduced_chapter: row.introduced_chapter == null ? '' : String(row.introduced_chapter),
    resolved_chapter: row.resolved_chapter == null ? '' : String(row.resolved_chapter),
  }
  focusFirst()
}

function toggleRelMode() {
  if (relMode.value === 'rows') {
    relRaw.value = relationshipsPayloadText()
    relMode.value = 'raw'
    formError.value = ''
    return
  }
  if (!canUseRows(relRaw.value)) {
    formError.value = '原文不是逐条的「姓名：关系」。改成一行一条，或继续用原文保存。'
    reveal()
    return
  }
  relRows.value = textToRows(relRaw.value)
  relMode.value = 'rows'
  formError.value = ''
}

function addRel() {
  relRows.value = [...relRows.value, { key: ++relSeq, name: '', relation: '' }]
}

function removeRel(key: number) {
  relRows.value = relRows.value.filter((row) => row.key !== key)
}

function isCurrent(type: BibleTab, id: number) {
  const current = editing.value
  if (current?.type === type && current.id == null) return false
  if (current?.type === type && current.id != null) return current.id === id
  if (current) return false
  if (type === 'characters') return activeCharacterId.value === id
  if (type === 'world') return activeWorldId.value === id
  return activeThreadId.value === id
}

function focusCharacter(id: number) {
  if (!guardSwitch('characters', id)) return
  activeCharacterId.value = id
  formError.value = ''
  if (!document.getElementById(`bible-char-${id}`)) query.value = ''
  nextTick(() => document.getElementById(`bible-char-${id}`)?.scrollIntoView({ block: 'nearest' }))
}

function focusWorld(id: number) {
  if (!guardSwitch('world', id)) return
  activeWorldId.value = id
  formError.value = ''
}

function focusThread(id: number) {
  if (!guardSwitch('threads', id)) return
  activeThreadId.value = id
  formError.value = ''
  if (!document.getElementById(`bible-thread-${id}`)) query.value = ''
  nextTick(() => document.getElementById(`bible-thread-${id}`)?.scrollIntoView({ block: 'nearest' }))
}

async function save() {
  if (!editing.value || busy.value) return
  formError.value = ''
  const mode = editing.value
  busy.value = true
  try {
    let focusId = mode.id
    if (mode.type === 'characters') {
      const name = form.value.name.trim()
      if (!name) {
        formError.value = '请填写姓名'
        reveal('bible-name')
        return
      }
      const parsed = parseRelationshipInput(relationshipsPayloadText())
      if (!parsed.ok) {
        formError.value = parsed.error
        reveal()
        return
      }
      const body: Partial<Character> = {
        name,
        aliases: splitAliases(form.value.aliases),
        role: form.value.role.trim(),
        status: form.value.status.trim(),
        personality: form.value.personality.trim(),
        speech_style: form.value.speech_style.trim(),
        relationships: parsed.value,
      }
      if (focusId) await bibleApi.updateCharacter(novelId, focusId, body)
      else focusId = createdId((await bibleApi.createCharacter(novelId, body)).data)
    } else if (mode.type === 'world') {
      const title = form.value.title.trim()
      const content = form.value.content.trim()
      if (!title) {
        formError.value = '请填写标题'
        reveal('bible-title')
        return
      }
      if (!content) {
        formError.value = '请填写内容'
        reveal('bible-content')
        return
      }
      const body: Partial<WorldSetting> = {
        category: form.value.category.trim() || '规则',
        title,
        content,
        do_not_violate: form.value.do_not_violate.trim(),
      }
      if (focusId) await bibleApi.updateWorld(novelId, focusId, body)
      else focusId = createdId((await bibleApi.createWorld(novelId, body)).data)
    } else {
      const title = form.value.title.trim()
      if (!title) {
        formError.value = '请填写标题'
        reveal('bible-thread-title')
        return
      }
      const intro = parseChapterField(form.value.introduced_chapter)
      const resolved = parseChapterField(form.value.resolved_chapter)
      if (!intro.ok) {
        formError.value = intro.error
        reveal('bible-introduced')
        return
      }
      if (!resolved.ok) {
        formError.value = resolved.error
        reveal('bible-resolved')
        return
      }
      const body: Partial<PlotThread> = {
        title,
        description: form.value.description.trim(),
        thread_type: form.value.thread_type || '伏笔',
        status: form.value.status || '未回收',
        introduced_chapter: intro.value,
        resolved_chapter: resolved.value,
      }
      if (focusId) await bibleApi.updateThread(novelId, focusId, body)
      else focusId = createdId((await bibleApi.createThread(novelId, body)).data)
    }
    editing.value = null
    await load()
    if (mode.type === 'characters') activeCharacterId.value = focusId
    else if (mode.type === 'world') activeWorldId.value = focusId
    else activeThreadId.value = focusId
    ensureSelection()
  } catch (err) {
    formError.value = errorText(err)
    reveal()
  } finally {
    busy.value = false
  }
}

async function remove(type: BibleTab, id: number) {
  if (busy.value) return
  busy.value = true
  formError.value = ''
  try {
    if (type === 'characters') await bibleApi.deleteCharacter(novelId, id)
    else if (type === 'world') await bibleApi.deleteWorld(novelId, id)
    else await bibleApi.deleteThread(novelId, id)
    if (editing.value?.type === type && editing.value.id === id) editing.value = null
    if (type === 'characters' && activeCharacterId.value === id) activeCharacterId.value = null
    if (type === 'world' && activeWorldId.value === id) activeWorldId.value = null
    if (type === 'threads' && activeThreadId.value === id) activeThreadId.value = null
    await load()
  } catch (err) {
    formError.value = errorText(err)
    reveal()
  } finally {
    busy.value = false
  }
}

function onKey(event: KeyboardEvent) {
  if (event.key !== 'Escape' || busy.value || !editing.value) return
  event.preventDefault()
  cancelEdit()
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="bible">
    <WritebackReview :novel-id="novelId" mode="pending" @applied="load" />
    <div class="bible-bar">
      <div class="ws-tabs" role="tablist" aria-label="设定分类">
        <button
          type="button"
          class="ws-tab"
          role="tab"
          :aria-selected="tab === 'characters'"
          :class="tab === 'characters' && 'ws-tab--active'"
          @click="setTab('characters')"
        >
          人物
        </button>
        <button
          type="button"
          class="ws-tab"
          role="tab"
          :aria-selected="tab === 'world'"
          :class="tab === 'world' && 'ws-tab--active'"
          @click="setTab('world')"
        >
          世界观
        </button>
        <button
          type="button"
          class="ws-tab"
          role="tab"
          :aria-selected="tab === 'threads'"
          :class="tab === 'threads' && 'ws-tab--active'"
          @click="setTab('threads')"
        >
          伏笔线
        </button>
      </div>
      <button class="btn bible-bar__add" type="button" @click="startCreate">{{ createLabel }}</button>
    </div>

    <p v-if="!ready" class="meta">正在读取设定…</p>
    <p v-if="loadError" class="alert alert--danger bible-alert">
      <span>{{ loadError }}</span>
      <button class="btn-ghost btn-sm" type="button" @click="load">重试</button>
    </p>

    <EmptyState
      v-if="ready && !loadError && isEmpty && !editing"
      :title="emptyCopy.title"
      :body="emptyCopy.body"
      :primary="createLabel"
      @primary="startCreate"
    />

    <template v-else-if="ready && (!isEmpty || editing)">
      <RelationGraph
        v-if="tab === 'characters' && characters.length"
        :characters="characters"
        :active-id="graphActiveId"
        @select="focusCharacter"
      />
      <ThreadTimeline
        v-if="tab === 'threads' && threads.length"
        :threads="threads"
        :active-id="timelineActiveId"
        @select="focusThread"
      />

      <div class="wb-write">
      <aside class="wb-rail" :aria-label="railLabel">
        <div class="wb-rail__head">
          <span>{{ railLabel }}</span>
          <span class="tabular">{{ countLabel }}</span>
        </div>
        <label v-if="showFind" class="bible-find">
          <span class="sr-only">筛选当前列表</span>
          <input v-model="query" class="input" type="search" :placeholder="findPlaceholder" />
        </label>

        <template v-if="tab === 'characters'">
          <button
            v-for="row in shownCharacters"
            :id="`bible-char-${row.id}`"
            :key="row.id"
            type="button"
            class="wb-rail__item"
            :class="{ 'is-active': isCurrent('characters', row.id) }"
            :aria-current="isCurrent('characters', row.id) ? 'true' : undefined"
            @click="focusCharacter(row.id)"
          >
            <span class="wb-rail__ord">{{ (row.name || '·').slice(0, 1) }}</span>
            <span class="wb-rail__name">{{ row.name }}</span>
            <span v-if="row.role || row.status" class="wb-rail__state">{{ row.role || row.status }}</span>
          </button>
          <p v-if="!characters.length" class="wb-rail__empty">还没有人物。</p>
          <p v-else-if="!shownCharacters.length" class="wb-rail__empty">没有匹配的人物。</p>
        </template>

        <template v-else-if="tab === 'world'">
          <button
            v-for="row in shownWorlds"
            :key="row.id"
            type="button"
            class="wb-rail__item"
            :class="{ 'is-active': isCurrent('world', row.id) }"
            :aria-current="isCurrent('world', row.id) ? 'true' : undefined"
            @click="focusWorld(row.id)"
          >
            <span class="wb-rail__ord">{{ (row.category || '设').slice(0, 1) }}</span>
            <span class="wb-rail__name">{{ row.title || '未命名' }}</span>
            <span class="wb-rail__state">{{ row.do_not_violate ? `${row.category} · 有禁区` : row.category }}</span>
          </button>
          <p v-if="!worlds.length" class="wb-rail__empty">还没有设定。</p>
          <p v-else-if="!shownWorlds.length" class="wb-rail__empty">没有匹配的设定。</p>
        </template>

        <template v-else>
          <button
            v-for="row in shownThreads"
            :id="`bible-thread-${row.id}`"
            :key="row.id"
            type="button"
            class="wb-rail__item"
            :class="{ 'is-active': isCurrent('threads', row.id) }"
            :aria-current="isCurrent('threads', row.id) ? 'true' : undefined"
            @click="focusThread(row.id)"
          >
            <span class="wb-rail__ord">{{ (row.thread_type || '线').slice(0, 1) }}</span>
            <span class="wb-rail__name">{{ row.title }}</span>
            <span class="wb-rail__state" :data-status="row.status === '已回收' ? 'done' : undefined">
              {{ row.status }}
            </span>
          </button>
          <p v-if="!threads.length" class="wb-rail__empty">还没有伏笔。</p>
          <p v-else-if="!shownThreads.length" class="wb-rail__empty">没有匹配的伏笔。</p>
        </template>
      </aside>

      <section class="wb-stage">
        <article id="bible-sheet" class="wb-sheet">
          <form v-if="editing" class="bible-form" novalidate @submit.prevent="save">
            <header class="wb-sheet__head">
              <div class="min-w-0">
                <p class="wb-kicker">{{ sheetKicker }}</p>
                <h2 class="wb-title">{{ sheetHeading }}</h2>
              </div>
              <div class="wb-actions">
                <button class="btn-ghost" type="button" :disabled="busy" @click="cancelEdit">取消</button>
                <details v-if="editing.id" class="wb-more">
                  <summary class="wb-more__sum">删除</summary>
                  <div class="wb-more__panel">
                    <button
                      class="btn-danger btn-sm"
                      type="button"
                      :disabled="busy"
                      @click="remove(editing.type, editing.id)"
                    >
                      {{ busy ? '删除中…' : '确认删除' }}
                    </button>
                  </div>
                </details>
              </div>
            </header>

            <div class="bible-body">
              <p v-if="formError" id="bible-form-error" class="alert alert--danger">{{ formError }}</p>

              <template v-if="editing.type === 'characters'">
                <section class="bible-section">
                  <h3>身份</h3>
                  <div class="bible-grid">
                    <label class="bible-field">
                      <span class="label">姓名 <span class="bible-req">必填</span></span>
                      <input id="bible-name" v-model="form.name" class="input" autocomplete="off" />
                    </label>
                    <label class="bible-field">
                      <span class="label">别称</span>
                      <input v-model="form.aliases" class="input" autocomplete="off" placeholder="顿号或逗号分隔" />
                    </label>
                    <label class="bible-field">
                      <span class="label">身份</span>
                      <input v-model="form.role" class="input" list="bible-roles" autocomplete="off" placeholder="主角、反派、师尊" />
                    </label>
                    <label class="bible-field">
                      <span class="label">近况</span>
                      <input v-model="form.status" class="input" list="bible-statuses" autocomplete="off" placeholder="在场、身故、失踪" />
                    </label>
                  </div>
                  <datalist id="bible-roles">
                    <option value="主角" />
                    <option value="配角" />
                    <option value="反派" />
                    <option value="盟友" />
                  </datalist>
                  <datalist id="bible-statuses">
                    <option value="在场" />
                    <option value="身故" />
                    <option value="失踪" />
                    <option value="隐退" />
                  </datalist>
                </section>

                <section class="bible-section">
                  <h3>性格与语气</h3>
                  <div class="bible-stack">
                    <label class="bible-field">
                      <span class="label">性格</span>
                      <textarea v-model="form.personality" class="textarea textarea-sm" />
                    </label>
                    <label class="bible-field">
                      <span class="label">说话方式</span>
                      <textarea v-model="form.speech_style" class="textarea textarea-sm" placeholder="口头禅、句式、称呼" />
                    </label>
                  </div>
                </section>

                <section class="bible-section">
                  <div class="bible-sectionhead">
                    <h3>关系</h3>
                    <button class="bible-link" type="button" @click="toggleRelMode">
                      {{ relMode === 'rows' ? '改用原文' : '改回逐条' }}
                    </button>
                  </div>
                  <template v-if="relMode === 'rows'">
                    <div v-if="relRows.length" class="bible-rel__head">
                      <span>对方</span>
                      <span>关系</span>
                      <span></span>
                    </div>
                    <p v-else class="meta">还没有关系。加上之后，能对上姓名或别称的人会连到同一张卡。</p>
                    <div v-for="row in relRows" :key="row.key" class="bible-rel__line">
                      <input
                        v-model="row.name"
                        class="input"
                        autocomplete="off"
                        placeholder="对方姓名"
                        :aria-label="`关系 ${row.key} 对方`"
                      />
                      <input
                        v-model="row.relation"
                        class="input"
                        autocomplete="off"
                        placeholder="例如青梅竹马"
                        :aria-label="`关系 ${row.key} 内容`"
                      />
                      <button class="bible-link" type="button" @click="removeRel(row.key)">移除</button>
                    </div>
                    <button class="btn-ghost btn-sm" type="button" @click="addRel">添加一条</button>
                  </template>
                  <template v-else>
                    <textarea
                      v-model="relRaw"
                      class="textarea textarea-sm"
                      placeholder="一行一条，例如&#10;苏婉：青梅竹马&#10;也可以粘贴 JSON"
                    />
                    <p class="meta">姓名要和人物卡或别称一致，图上才会连到同一个人。</p>
                  </template>
                </section>
              </template>

              <template v-else-if="editing.type === 'world'">
                <section class="bible-section">
                  <h3>分类</h3>
                  <div class="bible-choice" role="radiogroup" aria-label="分类">
                    <button
                      v-for="item in worldChoices"
                      :key="item"
                      type="button"
                      role="radio"
                      :aria-checked="form.category === item"
                      :class="{ 'is-on': form.category === item }"
                      @click="form.category = item"
                    >
                      {{ item }}
                    </button>
                  </div>
                </section>
                <label class="bible-field">
                  <span class="label">标题 <span class="bible-req">必填</span></span>
                  <input id="bible-title" v-model="form.title" class="input" autocomplete="off" />
                </label>
                <label class="bible-field">
                  <span class="label">内容 <span class="bible-req">必填</span></span>
                  <textarea id="bible-content" v-model="form.content" class="textarea" />
                </label>
                <label class="bible-field">
                  <span class="label">不可违反</span>
                  <textarea
                    v-model="form.do_not_violate"
                    class="textarea textarea-sm"
                    placeholder="续写时不能突破的规则"
                  />
                </label>
              </template>

              <template v-else>
                <label class="bible-field">
                  <span class="label">标题 <span class="bible-req">必填</span></span>
                  <input id="bible-thread-title" v-model="form.title" class="input" autocomplete="off" />
                </label>
                <section class="bible-section">
                  <h3>类型</h3>
                  <div class="bible-choice" role="radiogroup" aria-label="类型">
                    <button
                      v-for="item in threadTypeChoices"
                      :key="item"
                      type="button"
                      role="radio"
                      :aria-checked="form.thread_type === item"
                      :class="{ 'is-on': form.thread_type === item }"
                      @click="form.thread_type = item"
                    >
                      {{ item }}
                    </button>
                  </div>
                </section>
                <section class="bible-section">
                  <h3>状态</h3>
                  <div class="bible-choice" role="radiogroup" aria-label="状态">
                    <button
                      v-for="item in threadStatusChoices"
                      :key="item"
                      type="button"
                      role="radio"
                      :aria-checked="form.status === item"
                      :class="{ 'is-on': form.status === item }"
                      @click="form.status = item"
                    >
                      {{ item }}
                    </button>
                  </div>
                </section>
                <div class="bible-grid">
                  <label class="bible-field">
                    <span class="label">出现章节</span>
                    <input
                      id="bible-introduced"
                      v-model="form.introduced_chapter"
                      class="input"
                      inputmode="numeric"
                      autocomplete="off"
                      placeholder="例如 12"
                    />
                  </label>
                  <label class="bible-field">
                    <span class="label">回收章节</span>
                    <input
                      id="bible-resolved"
                      v-model="form.resolved_chapter"
                      class="input"
                      inputmode="numeric"
                      autocomplete="off"
                      placeholder="留空表示未回收"
                    />
                  </label>
                </div>
                <p class="meta">留空表示还不知道。只填出现章节时，时间线上会显示为尚未回收。</p>
                <label class="bible-field">
                  <span class="label">描述</span>
                  <textarea v-model="form.description" class="textarea textarea-sm" placeholder="这条线现在知道什么" />
                </label>
              </template>

              <div class="bible-save">
                <button class="btn" type="submit" :disabled="busy">{{ busy ? '保存中…' : '保存' }}</button>
              </div>
            </div>
          </form>

          <template v-else-if="tab === 'characters' && selectedCharacter">
            <header class="wb-sheet__head">
              <div class="min-w-0">
                <p class="wb-kicker">人物</p>
                <h2 class="wb-title">{{ selectedCharacter.name }}</h2>
                <p v-if="characterMeta(selectedCharacter)" class="wb-lede">{{ characterMeta(selectedCharacter) }}</p>
              </div>
              <div class="wb-actions">
                <button class="btn" type="button" @click="startEditCharacter(selectedCharacter)">编辑</button>
                <details class="wb-more">
                  <summary class="wb-more__sum">删除</summary>
                  <div class="wb-more__panel">
                    <button
                      class="btn-danger btn-sm"
                      type="button"
                      :disabled="busy"
                      @click="remove('characters', selectedCharacter.id)"
                    >
                      {{ busy ? '删除中…' : '确认删除' }}
                    </button>
                  </div>
                </details>
              </div>
            </header>
            <div class="bible-body">
              <p v-if="formError" id="bible-form-error" class="alert alert--danger">{{ formError }}</p>
              <p v-if="!hasCharacterBody(selectedCharacter)" class="meta">还没有性格、语气或关系。</p>
              <section v-if="selectedCharacter.personality" class="bible-block">
                <h3>性格</h3>
                <p class="bible-copy">{{ selectedCharacter.personality }}</p>
              </section>
              <section v-if="selectedCharacter.speech_style" class="bible-block">
                <h3>说话方式</h3>
                <p class="bible-copy">{{ selectedCharacter.speech_style }}</p>
              </section>
              <section v-if="selectedPairs === null" class="bible-block">
                <h3>关系</h3>
                <pre class="bible-raw">{{ formatRelationshipInput(selectedCharacter.relationships) }}</pre>
              </section>
              <section v-else-if="selectedPairs.length" class="bible-block">
                <h3>关系</h3>
                <dl class="bible-pairs">
                  <template v-for="pair in selectedPairs" :key="pair.name">
                    <dt>{{ pair.name }}</dt>
                    <dd>{{ pair.relation }}</dd>
                  </template>
                </dl>
              </section>
            </div>
          </template>

          <template v-else-if="tab === 'world' && selectedWorld">
            <header class="wb-sheet__head">
              <div class="min-w-0">
                <p class="wb-kicker">{{ selectedWorld.category }}</p>
                <h2 class="wb-title">{{ selectedWorld.title || '未命名' }}</h2>
              </div>
              <div class="wb-actions">
                <button class="btn" type="button" @click="startEditWorld(selectedWorld)">编辑</button>
                <details class="wb-more">
                  <summary class="wb-more__sum">删除</summary>
                  <div class="wb-more__panel">
                    <button
                      class="btn-danger btn-sm"
                      type="button"
                      :disabled="busy"
                      @click="remove('world', selectedWorld.id)"
                    >
                      {{ busy ? '删除中…' : '确认删除' }}
                    </button>
                  </div>
                </details>
              </div>
            </header>
            <div class="bible-body">
              <p v-if="formError" id="bible-form-error" class="alert alert--danger">{{ formError }}</p>
              <p class="bible-copy">{{ selectedWorld.content }}</p>
              <p v-if="selectedWorld.do_not_violate" class="bible-forbid">
                <span>不可违反</span>
                {{ selectedWorld.do_not_violate }}
              </p>
            </div>
          </template>

          <template v-else-if="tab === 'threads' && selectedThread">
            <header class="wb-sheet__head">
              <div class="min-w-0">
                <p class="wb-kicker">伏笔线</p>
                <h2 class="wb-title">{{ selectedThread.title }}</h2>
                <p class="wb-lede">{{ threadMeta(selectedThread) }}</p>
              </div>
              <div class="wb-actions">
                <button class="btn" type="button" @click="startEditThread(selectedThread)">编辑</button>
                <details class="wb-more">
                  <summary class="wb-more__sum">删除</summary>
                  <div class="wb-more__panel">
                    <button
                      class="btn-danger btn-sm"
                      type="button"
                      :disabled="busy"
                      @click="remove('threads', selectedThread.id)"
                    >
                      {{ busy ? '删除中…' : '确认删除' }}
                    </button>
                  </div>
                </details>
              </div>
            </header>
            <div class="bible-body">
              <p v-if="formError" id="bible-form-error" class="alert alert--danger">{{ formError }}</p>
              <p v-if="selectedThread.description" class="bible-copy">{{ selectedThread.description }}</p>
              <p v-else class="meta">还没有描述。</p>
            </div>
          </template>

          <div v-else class="bible-body">
            <p class="meta">从左边选一条。</p>
          </div>
        </article>
      </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.bible-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem 1rem;
  margin-bottom: 1rem;
}

.bible-bar__add {
  margin-left: auto;
}

.bible-alert {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  margin: 0 0 1rem;
}

.bible-find {
  display: block;
  margin: 0 0.35rem 0.55rem;
}

.bible-body {
  display: grid;
  gap: 0.9rem;
  padding: 0.35rem 1.15rem 1.15rem;
}

.bible-section h3,
.bible-block h3,
.bible-sectionhead h3 {
  margin: 0;
  font-size: 0.82rem;
  font-weight: 650;
}

.bible-block h3 {
  color: var(--ink-muted);
}

.bible-sectionhead {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.55rem;
}

.bible-section h3 {
  margin-bottom: 0.55rem;
}

.bible-sectionhead h3 {
  margin-bottom: 0;
}

.bible-grid,
.bible-stack {
  display: grid;
  gap: 0.75rem;
}

.bible-grid {
  grid-template-columns: 1fr 1fr;
}

.bible-rel__head,
.bible-rel__line {
  display: grid;
  grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr) auto;
  gap: 0.45rem;
  align-items: center;
}

.bible-rel__head {
  margin-bottom: 0.3rem;
  font-size: 0.75rem;
  font-weight: 650;
  color: var(--ink-muted);
}

.bible-rel__line + .bible-rel__line {
  margin-top: 0.45rem;
}

.bible-link {
  border: 0;
  padding: 0.35rem 0.1rem;
  background: none;
  color: var(--ink-muted);
  font: inherit;
  font-size: 0.8125rem;
  cursor: pointer;
}

.bible-link:hover {
  color: var(--accent);
}

.bible-rel__line .bible-link:hover {
  color: var(--danger);
}

.bible-choice {
  display: flex;
  flex-wrap: wrap;
  gap: 0.15rem;
  padding: 0.15rem;
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg-deep) 78%, transparent);
}

.bible-choice button {
  flex: 1 1 4.5rem;
  border: 0;
  border-radius: 8px;
  padding: 0.42rem 0.55rem;
  background: transparent;
  color: var(--ink-muted);
  font: inherit;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
}

.bible-choice button.is-on {
  background: var(--paper);
  color: var(--accent);
  box-shadow: var(--shadow-sm);
}

.bible-choice button:focus-visible,
.bible-link:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.bible-req {
  font-weight: 550;
  color: var(--ink-muted);
}

.bible-copy {
  margin: 0.25rem 0 0;
  line-height: 1.65;
  white-space: pre-wrap;
}

.bible-pairs {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 0.4rem 1rem;
  margin: 0.35rem 0 0;
}

.bible-pairs dt {
  font-weight: 650;
}

.bible-pairs dd {
  margin: 0;
  color: var(--ink-muted);
}

.bible-forbid {
  margin: 0.2rem 0 0;
  padding-left: 0.75rem;
  border-left: 2px solid var(--danger);
  line-height: 1.6;
}

.bible-forbid span {
  display: block;
  margin-bottom: 0.15rem;
  font-size: 0.75rem;
  font-weight: 650;
  color: var(--danger);
}

.bible-raw {
  margin: 0.35rem 0 0;
  padding: 0.7rem 0.8rem;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.78rem;
  line-height: 1.5;
  white-space: pre-wrap;
  background: color-mix(in srgb, var(--bg-deep) 45%, transparent);
  border-radius: var(--radius-sm);
}

.bible-save {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

@media (max-width: 640px) {
  .bible-grid,
  .bible-rel__line {
    grid-template-columns: 1fr;
  }

  .bible-rel__head {
    display: none;
  }
}
</style>
