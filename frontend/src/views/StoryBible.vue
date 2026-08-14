<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  bibleApi,
  type Character,
  type PlotThread,
  type WorldSetting,
} from '@/api'

const route = useRoute()
const novelId = Number(route.params.id)
const tab = ref<'characters' | 'world' | 'threads'>('characters')
const characters = ref<Character[]>([])
const worlds = ref<WorldSetting[]>([])
const threads = ref<PlotThread[]>([])
const editing = ref<any>(null)
const form = ref<Record<string, any>>({})

async function load() {
  const { data } = await bibleApi.get(novelId)
  characters.value = data.characters
  worlds.value = data.world_settings
  threads.value = data.plot_threads
}

function startCreate() {
  editing.value = { type: tab.value, id: null }
  if (tab.value === 'characters') {
    form.value = { name: '', aliases: '', role: '', status: '', personality: '', speech_style: '' }
  } else if (tab.value === 'world') {
    form.value = { category: '规则', title: '', content: '', do_not_violate: '' }
  } else {
    form.value = { title: '', description: '', thread_type: '伏笔', status: '未回收' }
  }
}

function startEdit(type: string, row: any) {
  editing.value = { type, id: row.id }
  form.value = { ...row }
  if (type === 'characters' && Array.isArray(row.aliases)) {
    form.value.aliases = row.aliases.join('、')
  }
}

async function save() {
  if (!editing.value) return
  const t = editing.value.type
  if (t === 'characters') {
    const body = {
      ...form.value,
      aliases: String(form.value.aliases || '')
        .split(/[、,，]/)
        .map((s: string) => s.trim())
        .filter(Boolean),
    }
    if (editing.value.id) await bibleApi.updateCharacter(novelId, editing.value.id, body)
    else await bibleApi.createCharacter(novelId, body)
  } else if (t === 'world') {
    if (editing.value.id) await bibleApi.updateWorld(novelId, editing.value.id, form.value)
    else await bibleApi.createWorld(novelId, form.value)
  } else {
    if (editing.value.id) await bibleApi.updateThread(novelId, editing.value.id, form.value)
    else await bibleApi.createThread(novelId, form.value)
  }
  editing.value = null
  await load()
}

async function remove(type: string, id: number) {
  if (!confirm('确认删除？')) return
  if (type === 'characters') await bibleApi.deleteCharacter(novelId, id)
  else if (type === 'world') await bibleApi.deleteWorld(novelId, id)
  else await bibleApi.deleteThread(novelId, id)
  await load()
}

onMounted(load)
</script>

<template>
  <div>
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
        </div>
        <div><label class="label">描述</label><textarea v-model="form.description" class="textarea textarea-sm" /></div>
      </template>
      <div class="flex gap-2 pt-1">
        <button class="btn" @click="save">保存</button>
        <button class="btn-ghost" @click="editing = null">取消</button>
      </div>
    </div>

    <ul v-if="tab === 'characters'" class="space-y-3">
      <li v-for="c in characters" :key="c.id" class="panel cv-item px-5 py-4">
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
            </div>
          </div>
          <div class="flex gap-2 shrink-0">
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

    <ul v-else class="space-y-3">
      <li v-for="t in threads" :key="t.id" class="panel cv-item px-5 py-4">
        <div class="flex justify-between gap-3">
          <div class="min-w-0">
            <div class="font-medium flex items-center gap-2 flex-wrap">
              <span>{{ t.title }}</span>
              <span class="badge">{{ t.thread_type }}</span>
              <span class="status-pill" :class="t.status === '已回收' ? 'status-pill--ok' : 'status-pill--busy'">
                {{ t.status }}
              </span>
            </div>
            <div class="text-sm mt-1.5" style="color: var(--ink-muted)">{{ t.description }}</div>
          </div>
          <div class="flex gap-2 shrink-0">
            <button class="btn-ghost" @click="startEdit('threads', t)">编辑</button>
            <button class="btn-danger" @click="remove('threads', t.id)">删除</button>
          </div>
        </div>
      </li>
      <li v-if="!threads.length" class="empty-state">
        <p class="empty">暂无伏笔线，入库后会自动抽取，也可手动添加。</p>
      </li>
    </ul>
  </div>
</template>
