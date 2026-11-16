<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  bibleApi,
  type Character,
  type PlotThread,
  type WorldSetting,
} from '@/api'
import RelationGraph from '@/components/RelationGraph.vue'
import ThreadTimeline from '@/components/ThreadTimeline.vue'
import WritebackReview from '@/components/WritebackReview.vue'
import {
  formatRelationshipInput,
  indexRelationships,
  outgoingBrief,
  parseChapterField,
  parseRelationshipInput,
  threadSpan,
} from '@/lib/bibleViz'

const route = useRoute()
const novelId = Number(route.params.id)
const tab = ref<'characters' | 'world' | 'threads'>('characters')
const characters = ref<Character[]>([])
const worlds = ref<WorldSetting[]>([])
const threads = ref<PlotThread[]>([])
const editing = ref<any>(null)
const form = ref<Record<string, any>>({})
const formError = ref('')
const activeCharacterId = ref<number | null>(null)
const activeThreadId = ref<number | null>(null)

const relationIndex = computed(() => indexRelationships(characters.value))

function relationBrief(character: Character) {
  return outgoingBrief(relationIndex.value, character.id)
}

async function load() {
  const { data } = await bibleApi.get(novelId)
  characters.value = data.characters
  worlds.value = data.world_settings
  threads.value = data.plot_threads
}

function startCreate() {
  formError.value = ''
  editing.value = { type: tab.value, id: null }
  if (tab.value === 'characters') {
    form.value = {
      name: '',
      aliases: '',
      role: '',
      status: '',
      personality: '',
      speech_style: '',
      relationshipsText: '',
    }
  } else if (tab.value === 'world') {
    form.value = { category: '规则', title: '', content: '', do_not_violate: '' }
  } else {
    form.value = {
      title: '',
      description: '',
      thread_type: '伏笔',
      status: '未回收',
      introduced_chapter: '',
      resolved_chapter: '',
    }
  }
}

function startEdit(type: string, row: any) {
  formError.value = ''
  editing.value = { type, id: row.id }
  form.value = { ...row }
  if (type === 'characters') {
    form.value.relationshipsText = formatRelationshipInput(row.relationships)
    if (Array.isArray(row.aliases)) form.value.aliases = row.aliases.join('、')
  }
  if (type === 'threads') {
    form.value.introduced_chapter = row.introduced_chapter ?? ''
    form.value.resolved_chapter = row.resolved_chapter ?? ''
  }
}

function cancelEdit() {
  editing.value = null
  formError.value = ''
}

function splitAliases(raw: unknown) {
  return String(raw || '')
    .split(/[、,，]/)
    .map((s) => s.trim())
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

async function save() {
  if (!editing.value) return
  formError.value = ''
  const t = editing.value.type
  try {
    if (t === 'characters') {
      const name = String(form.value.name || '').trim()
      if (!name) {
        formError.value = '请填写姓名'
        return
      }
      const parsed = parseRelationshipInput(String(form.value.relationshipsText || ''))
      if (!parsed.ok) {
        formError.value = parsed.error
        return
      }
      const body: Partial<Character> = {
        name,
        aliases: splitAliases(form.value.aliases),
        role: form.value.role || '',
        status: form.value.status || '',
        personality: form.value.personality || '',
        speech_style: form.value.speech_style || '',
        relationships: parsed.value,
      }
      if (editing.value.id) await bibleApi.updateCharacter(novelId, editing.value.id, body)
      else await bibleApi.createCharacter(novelId, body)
    } else if (t === 'world') {
      if (editing.value.id) await bibleApi.updateWorld(novelId, editing.value.id, form.value)
      else await bibleApi.createWorld(novelId, form.value)
    } else {
      const title = String(form.value.title || '').trim()
      if (!title) {
        formError.value = '请填写标题'
        return
      }
      const intro = parseChapterField(form.value.introduced_chapter)
      const resolved = parseChapterField(form.value.resolved_chapter)
      if (!intro.ok) {
        formError.value = intro.error
        return
      }
      if (!resolved.ok) {
        formError.value = resolved.error
        return
      }
      const body: Partial<PlotThread> = {
        title,
        description: form.value.description || '',
        thread_type: form.value.thread_type || '伏笔',
        status: form.value.status || '未回收',
        introduced_chapter: intro.value,
        resolved_chapter: resolved.value,
      }
      if (editing.value.id) await bibleApi.updateThread(novelId, editing.value.id, body)
      else await bibleApi.createThread(novelId, body)
    }
    editing.value = null
    await load()
  } catch (err) {
    formError.value = errorText(err)
  }
}

async function remove(type: string, id: number) {
  if (!confirm('确认删除？')) return
  if (type === 'characters') await bibleApi.deleteCharacter(novelId, id)
  else if (type === 'world') await bibleApi.deleteWorld(novelId, id)
  else await bibleApi.deleteThread(novelId, id)
  if (activeCharacterId.value === id) activeCharacterId.value = null
  if (activeThreadId.value === id) activeThreadId.value = null
  await load()
}

function focusCharacter(id: number) {
  activeCharacterId.value = id
  document.getElementById(`bible-char-${id}`)?.scrollIntoView({ block: 'nearest' })
}

function focusThread(id: number) {
  activeThreadId.value = id
  document.getElementById(`bible-thread-${id}`)?.scrollIntoView({ block: 'nearest' })
}

onMounted(load)
</script>

<template>
  <div>
    <WritebackReview :novel-id="novelId" mode="pending" @applied="load" />
    <div class="flex flex-wrap gap-2 mb-5 items-center">
      <div class="ws-tabs">
        <button
          type="button"
          class="ws-tab"
          :class="tab === 'characters' && 'ws-tab--active'"
          @click="tab = 'characters'"
        >
          人物卡
        </button>
        <button
          type="button"
          class="ws-tab"
          :class="tab === 'world' && 'ws-tab--active'"
          @click="tab = 'world'"
        >
          世界观
        </button>
        <button
          type="button"
          class="ws-tab"
          :class="tab === 'threads' && 'ws-tab--active'"
          @click="tab = 'threads'"
        >
          伏笔线
        </button>
      </div>
      <button class="btn ml-auto" @click="startCreate">新增</button>
    </div>

    <div v-if="editing" class="panel p-5 mb-5 space-y-3">
      <template v-if="editing.type === 'characters'">
        <div class="grid sm:grid-cols-2 gap-3">
          <div><label class="label">姓名</label><input v-model="form.name" class="input" /></div>
          <div><label class="label">别称（、分隔）</label><input v-model="form.aliases" class="input" /></div>
          <div><label class="label">角色</label><input v-model="form.role" class="input" /></div>
          <div><label class="label">状态</label><input v-model="form.status" class="input" /></div>
        </div>
        <div><label class="label">性格</label><textarea v-model="form.personality" class="textarea textarea-sm" /></div>
        <div><label class="label">语言特征</label><textarea v-model="form.speech_style" class="textarea textarea-sm" /></div>
        <div>
          <label class="label">关系</label>
          <textarea
            v-model="form.relationshipsText"
            class="textarea textarea-sm"
            placeholder="一行一条，例如&#10;苏婉：青梅竹马&#10;叶天：师徒"
          />
          <p class="meta mt-1.5">对方姓名能对上人物卡或别称时，会连到同一个人。也可以直接贴 JSON。</p>
        </div>
      </template>
      <template v-else-if="editing.type === 'world'">
        <div class="grid sm:grid-cols-2 gap-3">
          <div>
            <label class="label">分类</label>
            <select v-model="form.category" class="input">
              <option>力量体系</option><option>地理</option><option>组织</option><option>规则</option>
            </select>
          </div>
          <div><label class="label">标题</label><input v-model="form.title" class="input" /></div>
        </div>
        <div><label class="label">内容</label><textarea v-model="form.content" class="textarea" /></div>
        <div><label class="label">禁止事项</label><textarea v-model="form.do_not_violate" class="textarea textarea-sm" /></div>
      </template>
      <template v-else>
        <div class="grid sm:grid-cols-2 gap-3">
          <div><label class="label">标题</label><input v-model="form.title" class="input" /></div>
          <div>
            <label class="label">类型</label>
            <select v-model="form.thread_type" class="input">
              <option>伏笔</option><option>主线</option><option>支线</option>
            </select>
          </div>
          <div>
            <label class="label">状态</label>
            <select v-model="form.status" class="input">
              <option>未回收</option><option>已回收</option>
            </select>
          </div>
          <div>
            <label class="label">出现章节</label>
            <input v-model="form.introduced_chapter" class="input" type="number" min="1" step="1" placeholder="第几章出现" />
          </div>
          <div>
            <label class="label">回收章节</label>
            <input v-model="form.resolved_chapter" class="input" type="number" min="1" step="1" placeholder="留空表示未回收" />
          </div>
        </div>
        <div><label class="label">描述</label><textarea v-model="form.description" class="textarea textarea-sm" /></div>
      </template>
      <p v-if="formError" class="alert alert--danger">{{ formError }}</p>
      <div class="flex gap-2 pt-1">
        <button class="btn" @click="save">保存</button>
        <button class="btn-ghost" @click="cancelEdit">取消</button>
      </div>
    </div>

    <RelationGraph
      v-if="tab === 'characters' && characters.length"
      :characters="characters"
      :active-id="activeCharacterId"
      @select="focusCharacter"
    />

    <ul v-if="tab === 'characters'" class="space-y-3">
      <li
        v-for="c in characters"
        :id="`bible-char-${c.id}`"
        :key="c.id"
        class="panel cv-item px-5 py-4"
        :class="{ 'bible-row--active': activeCharacterId === c.id }"
        @click="activeCharacterId = c.id"
      >
        <div class="flex justify-between gap-3">
          <div class="flex gap-3 min-w-0">
            <div class="avatar" aria-hidden="true">{{ (c.name || '·').slice(0, 1) }}</div>
            <div class="min-w-0">
              <div class="font-medium">
                {{ c.name }}
                <span v-if="c.role" class="badge ml-1.5">{{ c.role }}</span>
              </div>
              <div class="meta mt-1">
                别称：{{ (c.aliases || []).join('、') || '无' }} · {{ c.status || '状态未知' }}
              </div>
              <div v-if="c.personality" class="text-sm mt-1.5" style="color: var(--ink-muted)">{{ c.personality }}</div>
              <div v-if="relationBrief(c)" class="meta mt-1.5">关系：{{ relationBrief(c) }}</div>
            </div>
          </div>
          <div class="flex gap-2 shrink-0" @click.stop>
            <button class="btn-ghost" @click="startEdit('characters', c)">编辑</button>
            <button class="btn-danger" @click="remove('characters', c.id)">删除</button>
          </div>
        </div>
      </li>
      <li v-if="!characters.length" class="empty-state">
        <p class="empty">暂无人物，入库后会自动抽取，也可手动添加。</p>
      </li>
    </ul>

    <ul v-else-if="tab === 'world'" class="space-y-3">
      <li v-for="w in worlds" :key="w.id" class="panel cv-item px-5 py-4">
        <div class="flex justify-between gap-3">
          <div class="min-w-0">
            <div class="font-medium flex items-center gap-2 flex-wrap">
              <span class="badge">{{ w.category }}</span>
              <span>{{ w.title }}</span>
            </div>
            <div class="text-sm mt-1.5" style="color: var(--ink-muted)">{{ w.content }}</div>
            <div v-if="w.do_not_violate" class="meta mt-1.5" style="color: var(--danger)">禁止：{{ w.do_not_violate }}</div>
          </div>
          <div class="flex gap-2 shrink-0">
            <button class="btn-ghost" @click="startEdit('world', w)">编辑</button>
            <button class="btn-danger" @click="remove('world', w.id)">删除</button>
          </div>
        </div>
      </li>
      <li v-if="!worlds.length" class="empty-state">
        <p class="empty">暂无世界观条目，入库后会自动抽取，也可手动添加。</p>
      </li>
    </ul>

    <template v-else>
      <ThreadTimeline
        v-if="threads.length"
        :threads="threads"
        :active-id="activeThreadId"
        @select="focusThread"
      />
      <ul class="space-y-3">
        <li
          v-for="t in threads"
          :id="`bible-thread-${t.id}`"
          :key="t.id"
          class="panel cv-item px-5 py-4"
          :class="{ 'bible-row--active': activeThreadId === t.id }"
          @click="activeThreadId = t.id"
        >
          <div class="flex justify-between gap-3">
            <div class="min-w-0">
              <div class="font-medium flex items-center gap-2 flex-wrap">
                <span>{{ t.title }}</span>
                <span class="badge">{{ t.thread_type }}</span>
                <span class="status-pill" :class="t.status === '已回收' ? 'status-pill--ok' : 'status-pill--idle'">
                  {{ t.status }}
                </span>
              </div>
              <div v-if="threadSpan(t)" class="meta mt-1 tabular">{{ threadSpan(t) }}</div>
              <div class="text-sm mt-1.5" style="color: var(--ink-muted)">{{ t.description }}</div>
            </div>
            <div class="flex gap-2 shrink-0" @click.stop>
              <button class="btn-ghost" @click="startEdit('threads', t)">编辑</button>
              <button class="btn-danger" @click="remove('threads', t.id)">删除</button>
            </div>
          </div>
        </li>
        <li v-if="!threads.length" class="empty-state">
          <p class="empty">暂无伏笔线，入库后会自动抽取，也可手动添加。</p>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.bible-row--active {
  box-shadow: inset 3px 0 0 var(--accent);
  background: color-mix(in srgb, var(--accent-soft) 55%, var(--panel));
}
</style>
