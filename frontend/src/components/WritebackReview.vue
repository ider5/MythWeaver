<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { bibleApi, type BibleProposal, type WritebackChange } from '@/api'

const props = withDefaults(
  defineProps<{
    novelId: number
    chapterId?: number | null
    proposeToken?: number
    reloadToken?: number
    mode?: 'chapter' | 'pending'
  }>(),
  {
    chapterId: null,
    proposeToken: 0,
    reloadToken: 0,
    mode: 'chapter',
  },
)

const emit = defineEmits<{ applied: [] }>()

const loading = ref(false)
const error = ref('')
const proposals = ref<BibleProposal[]>([])
const selected = ref<Record<number, string[]>>({})
const busy = ref(false)
let seq = 0
let handledToken = 0

const kindLabel: Record<string, string> = { character: '人物', world: '设定', thread: '伏笔' }
const opLabel: Record<string, string> = { create: '新增', update: '更新' }

const visible = computed(() => loading.value || !!error.value || proposals.value.length > 0)

function errorText(err: unknown) {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string }
  const detail = e.response?.data?.detail
  if (typeof detail === 'string') return detail
  return e.message || '设定对照失败'
}

function adopt(rows: BibleProposal[]) {
  const next: Record<number, string[]> = {}
  for (const row of rows) next[row.id] = row.changes.map((change) => change.id)
  selected.value = next
  proposals.value = rows
}

function isChecked(pid: number, id: string) {
  return (selected.value[pid] || []).includes(id)
}

function selectedCount(pid: number) {
  return (selected.value[pid] || []).length
}

function toggle(pid: number, id: string, on: boolean) {
  const current = new Set(selected.value[pid] || [])
  if (on) current.add(id)
  else current.delete(id)
  selected.value = { ...selected.value, [pid]: [...current] }
}

async function loadPending() {
  if (props.mode === 'chapter' && !props.chapterId) {
    adopt([])
    return
  }
  const my = ++seq
  try {
    const { data } = await bibleApi.listProposals(props.novelId, 'pending')
    if (my !== seq) return
    const rows =
      props.mode === 'chapter' ? data.filter((row) => row.chapter_id === props.chapterId) : data
    adopt(rows)
  } catch (err) {
    if (my !== seq) return
    error.value = errorText(err)
  }
}

async function propose() {
  if (!props.chapterId) return
  const my = ++seq
  loading.value = true
  error.value = ''
  try {
    const { data } = await bibleApi.proposeWriteback(props.novelId, props.chapterId)
    if (my !== seq) return
    adopt(data.status === 'pending' ? [data] : [])
  } catch (err) {
    if (my !== seq) return
    error.value = errorText(err)
  } finally {
    if (my === seq) loading.value = false
  }
}

async function apply(row: BibleProposal, all: boolean) {
  const ids = all ? undefined : [...(selected.value[row.id] || [])]
  if (!all && !ids?.length) return
  busy.value = true
  error.value = ''
  try {
    await bibleApi.applyProposal(props.novelId, row.id, ids)
    proposals.value = proposals.value.filter((item) => item.id !== row.id)
    emit('applied')
  } catch (err) {
    error.value = errorText(err)
  } finally {
    busy.value = false
  }
}

async function dismiss(row: BibleProposal) {
  busy.value = true
  error.value = ''
  try {
    await bibleApi.dismissProposal(props.novelId, row.id)
    proposals.value = proposals.value.filter((item) => item.id !== row.id)
  } catch (err) {
    error.value = errorText(err)
  } finally {
    busy.value = false
  }
}

function fieldText(change: WritebackChange) {
  return change.fields
}

watch(
  () => [props.mode, props.chapterId, props.proposeToken] as const,
  ([mode, id, token], prev) => {
    if (mode !== 'chapter') return
    if (!id) {
      adopt([])
      error.value = ''
      return
    }
    const tokenN = token || 0
    if (tokenN > handledToken) {
      handledToken = tokenN
      propose()
      return
    }
    if (!prev || id !== prev[1]) loadPending()
  },
  { immediate: true },
)

watch(
  () => props.reloadToken,
  (value, prev) => {
    if (props.mode !== 'chapter' || !value || value === prev || !props.chapterId) return
    loadPending()
  },
)

onMounted(() => {
  if (props.mode === 'pending') loadPending()
})
</script>

<template>
  <section
    v-if="visible"
    class="panel writeback"
    :class="{ 'writeback--gap': mode === 'pending' }"
    aria-label="设定变更"
  >
    <header class="writeback-head">
      <div>
        <h3>{{ mode === 'pending' ? '设定还没写入' : '本章设定变更' }}</h3>
        <p>
          {{
            mode === 'pending'
              ? '这些改动来自已经生成的章节，还没写进设定。'
              : '先对照现有 Story Bible。勾上的才写入，没勾的跳过。'
          }}
        </p>
      </div>
      <RouterLink v-if="mode === 'chapter'" class="writeback-link" :to="`/novels/${novelId}/bible`">
        打开设定
      </RouterLink>
    </header>

    <p v-if="loading" class="meta">正在对照这一章和 Story Bible…</p>
    <p v-if="error" class="alert alert--danger">
      {{ error }}
      <button v-if="mode === 'chapter'" type="button" class="btn-ghost btn-sm" :disabled="busy" @click="propose">
        重试
      </button>
    </p>

    <article v-for="row in proposals" :key="row.id" class="writeback-card">
      <p v-if="row.chapter_index" class="meta">
        第{{ row.chapter_index }}章<span v-if="row.chapter_title"> · {{ row.chapter_title }}</span>
      </p>
      <p v-if="!row.changes.length" class="empty">这一章没有新的人物、设定或伏笔。</p>
      <ul v-else class="writeback-list">
        <li v-for="change in row.changes" :key="change.id">
          <label class="writeback-check">
            <input
              type="checkbox"
              :checked="isChecked(row.id, change.id)"
              :disabled="busy"
              @change="toggle(row.id, change.id, ($event.target as HTMLInputElement).checked)"
            />
            <span>
              <span class="meta">{{ kindLabel[change.kind] || change.kind }} · {{ opLabel[change.op] || change.op }}</span>
              <span class="writeback-label">{{ change.label }}</span>
            </span>
          </label>
          <p class="writeback-summary">{{ change.summary }}</p>
          <div v-if="fieldText(change).length" class="writeback-fields">
            <div v-for="field in change.fields" :key="field.key" class="writeback-field">
              <span class="k">{{ field.label }}</span>
              <span v-if="field.before" class="before">{{ field.before }}</span>
              <span v-if="field.before" class="arrow">→</span>
              <span>{{ field.after || '—' }}</span>
            </div>
          </div>
        </li>
      </ul>
      <div class="writeback-actions">
        <template v-if="row.changes.length">
          <button
            type="button"
            class="btn btn-sm"
            :disabled="busy || !selectedCount(row.id)"
            @click="apply(row, false)"
          >
            写入已勾选（{{ selectedCount(row.id) }}）
          </button>
          <button type="button" class="btn-ghost btn-sm" :disabled="busy" @click="apply(row, true)">
            全部写入
          </button>
        </template>
        <button type="button" class="btn-ghost btn-sm" :disabled="busy" @click="dismiss(row)">
          {{ row.changes.length ? '跳过' : '知道了' }}
        </button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.writeback {
  padding: 1.15rem 1.25rem 1.25rem;
  border-left: 3px solid var(--accent);
}
.writeback--gap {
  margin-bottom: 1.25rem;
}
.writeback-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  margin-bottom: 0.85rem;
}
.writeback-head h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
}
.writeback-head p {
  margin: 0.25rem 0 0;
  color: var(--ink-muted);
  font-size: 0.8125rem;
}
.writeback-link {
  flex: none;
  color: var(--accent);
  font-size: 0.8125rem;
  font-weight: 650;
  text-decoration: none;
}
.writeback-link:hover {
  text-decoration: underline;
}
.writeback-card + .writeback-card {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--line);
}
.writeback-list {
  list-style: none;
  margin: 0.65rem 0 0;
  padding: 0;
}
.writeback-list li + li {
  margin-top: 0.85rem;
  padding-top: 0.85rem;
  border-top: 1px solid var(--line);
}
.writeback-check {
  display: flex;
  gap: 0.6rem;
  align-items: flex-start;
}
.writeback-label {
  display: block;
  font-weight: 650;
}
.writeback-summary {
  margin: 0.2rem 0 0 1.45rem;
  color: var(--ink-muted);
  font-size: 0.8125rem;
}
.writeback-fields {
  margin: 0.35rem 0 0 1.45rem;
  display: grid;
  gap: 0.2rem;
}
.writeback-field {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.45rem;
  align-items: baseline;
  font-size: 0.8125rem;
}
.writeback-field .k {
  min-width: 3.5rem;
  color: var(--ink-muted);
}
.writeback-field .before {
  color: var(--ink-muted);
  text-decoration: line-through;
}
.writeback-field .arrow {
  color: var(--ink-muted);
}
.writeback-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.9rem;
}
</style>
