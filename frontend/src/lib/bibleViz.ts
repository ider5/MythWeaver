/** 把 Story Bible 的 relationships JSON 和伏笔章节整理成图、时间线。 */

export interface BibleCharacter {
  id: number
  name: string
  aliases?: string[] | null
  role?: string | null
  relationships?: Record<string, unknown> | null
}

export interface BibleThread {
  id: number
  title: string
  description?: string | null
  thread_type: string
  status: string
  introduced_chapter?: number | null
  resolved_chapter?: number | null
}

export type ParseResult<T> = { ok: true; value: T } | { ok: false; error: string }

export interface RelNode {
  id: string
  name: string
  role?: string
  characterId?: number
  known: boolean
  tone: 'lead' | 'rival' | 'cast'
}

export interface RelEdge {
  id: string
  sourceId: string
  targetId: string
  label: string
}

export interface RelationIndex {
  edges: RelEdge[]
  nodes: RelNode[]
  isolated: number
  bySource: Map<number, { name: string; label: string }[]>
}

export interface LaidEdge extends RelEdge {
  x1: number
  y1: number
  x2: number
  y2: number
  cx: number
  cy: number
  lx: number
  ly: number
}

export interface LaidNode extends RelNode {
  x: number
  y: number
  shortName: string
  glyph: string
}

export interface GraphLayout {
  width: number
  height: number
  nodes: LaidNode[]
  edges: LaidEdge[]
  isolated: number
  summary: string
  hasExternal: boolean
}

export interface TimelineTick {
  chapter: number
  pct: number
  align: 'start' | 'mid' | 'end'
}

export interface TimelineLane {
  id: number
  title: string
  threadType: string
  status: string
  description: string
  kind: 'main' | 'hook' | 'side'
  start: number
  end: number
  open: boolean
  point: boolean
  leftPct: number
  widthPct: number
}

export interface TimelineModel {
  min: number
  max: number
  ticks: TimelineTick[]
  lanes: TimelineLane[]
  unmarked: { id: number; title: string }[]
}

const LIST_KEYS = new Set(['links', 'edges', 'items', 'relations', 'relationships', 'list'])
const META_KEYS = new Set([
  'notes',
  'note',
  'source',
  'chapter',
  'updated',
  'id',
  'meta',
  'comment',
  '备注',
  '说明',
])
const RELATION_WORDS = new Set([
  '父亲',
  '母亲',
  '爸爸',
  '妈妈',
  '儿子',
  '女儿',
  '哥哥',
  '姐姐',
  '弟弟',
  '妹妹',
  '师父',
  '师傅',
  '徒弟',
  '师兄',
  '师姐',
  '师弟',
  '师妹',
  '朋友',
  '好友',
  '恋人',
  '情人',
  '夫妻',
  '丈夫',
  '妻子',
  '未婚妻',
  '未婚夫',
  '青梅',
  '竹马',
  '青梅竹马',
  '同门',
  '同伴',
  '伙伴',
  '盟友',
  '敌人',
  '仇人',
  '对手',
  '宿敌',
  '主公',
  '下属',
  '上司',
  '主人',
  '仆人',
  '兄弟',
  '姐妹',
  '义兄',
  '义弟',
  '义妹',
  '义父',
  '义子',
  '恩人',
  '仇敌',
  '情敌',
  '同窗',
  '故人',
  '亲人',
  '家人',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function normKey(value: string): string {
  return value.trim().replace(/\s+/g, '').toLowerCase()
}

function toneOf(role?: string | null): RelNode['tone'] {
  if (!role) return 'cast'
  if (role.includes('主角') || role.includes('主人公')) return 'lead'
  if (role.includes('反派') || role.includes('敌')) return 'rival'
  return 'cast'
}

function nodeFromCharacter(character: BibleCharacter): RelNode {
  return {
    id: `c${character.id}`,
    name: character.name,
    role: character.role || undefined,
    characterId: character.id,
    known: true,
    tone: toneOf(character.role),
  }
}

function pickString(obj: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = obj[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function asRelationshipRecord(value: unknown): Record<string, unknown> | null {
  if (value == null) return null
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text) return null
    if (text.startsWith('{') || text.startsWith('[')) {
      try {
        return asRelationshipRecord(JSON.parse(text) as unknown)
      } catch {
        return null
      }
    }
    return null
  }
  if (Array.isArray(value)) return { links: value }
  if (isRecord(value)) return value
  return null
}

export function parseRelationshipInput(text: string): ParseResult<Record<string, unknown>> {
  const raw = text.trim()
  if (!raw) return { ok: true, value: {} }
  if (raw.startsWith('{') || raw.startsWith('[')) {
    try {
      const parsed = JSON.parse(raw) as unknown
      if (Array.isArray(parsed)) return { ok: true, value: { links: parsed } }
      if (!isRecord(parsed)) return { ok: false, error: '关系 JSON 需要是对象' }
      return { ok: true, value: parsed }
    } catch {
      return { ok: false, error: '关系 JSON 无法解析' }
    }
  }
  const value: Record<string, string> = {}
  const lines = raw.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line) continue
    const idx = line.search(/[:：]/)
    if (idx <= 0) return { ok: false, error: `第 ${i + 1} 行请写成「姓名：关系」` }
    const name = line.slice(0, idx).trim()
    const rel = line.slice(idx + 1).trim()
    if (!name || !rel) return { ok: false, error: `第 ${i + 1} 行请写成「姓名：关系」` }
    value[name] = value[name] ? `${value[name]}、${rel}` : rel
  }
  return { ok: true, value }
}

export function formatRelationshipInput(rel: unknown): string {
  if (rel == null) return ''
  if (typeof rel === 'string') {
    const text = rel.trim()
    if (!text) return ''
    if (text.startsWith('{') || text.startsWith('[')) {
      try {
        return formatRelationshipInput(JSON.parse(text) as unknown)
      } catch {
        return text
      }
    }
    return text
  }
  if (Array.isArray(rel)) return JSON.stringify(rel, null, 2)
  if (!isRecord(rel)) return ''
  const entries = Object.entries(rel)
  if (!entries.length) return ''
  if (entries.every(([, value]) => typeof value === 'string')) {
    return entries.map(([key, value]) => `${key}：${value}`).join('\n')
  }
  return JSON.stringify(rel, null, 2)
}

export function parseChapterField(value: unknown): ParseResult<number | null> {
  if (value === '' || value == null) return { ok: true, value: null }
  const n = typeof value === 'number' ? value : Number(String(value).trim())
  if (!Number.isInteger(n) || n < 1) return { ok: false, error: '章节请填正整数，或留空' }
  return { ok: true, value: n }
}

function buildNameIndex(characters: BibleCharacter[]): Map<string, BibleCharacter> {
  const byName = new Map<string, BibleCharacter>()
  for (const character of characters) {
    const keys = [character.name, ...(character.aliases || [])]
    for (const key of keys) {
      const norm = normKey(String(key || ''))
      if (norm && !byName.has(norm)) byName.set(norm, character)
    }
  }
  return byName
}

export function indexRelationships(characters: BibleCharacter[]): RelationIndex {
  const byName = buildNameIndex(characters)
  const nodes = new Map<string, RelNode>()
  const bucket = new Map<string, { sourceId: string; targetId: string; labels: Set<string> }>()

  function ensureCharacterNode(character: BibleCharacter) {
    const id = `c${character.id}`
    if (!nodes.has(id)) nodes.set(id, nodeFromCharacter(character))
    return id
  }

  function resolveTarget(name: string, owner: BibleCharacter): string | null {
    const trimmed = name.trim()
    if (!trimmed) return null
    const found = byName.get(normKey(trimmed))
    if (found) {
      if (found.id === owner.id) return null
      return ensureCharacterNode(found)
    }
    const id = `x:${normKey(trimmed)}`
    if (!nodes.has(id)) {
      nodes.set(id, { id, name: trimmed, known: false, tone: 'cast' })
    }
    return id
  }

  function addEdge(owner: BibleCharacter, targetName: string, label: string) {
    const targetId = resolveTarget(targetName, owner)
    if (!targetId) return
    const sourceId = ensureCharacterNode(owner)
    if (sourceId === targetId) return
    const clean = label.trim() || '相关'
    if (clean.length > 80) return
    const key = `${sourceId}|${targetId}`
    let row = bucket.get(key)
    if (!row) {
      row = { sourceId, targetId, labels: new Set() }
      bucket.set(key, row)
    }
    row.labels.add(clean.length > 24 ? `${[...clean].slice(0, 23).join('')}…` : clean)
  }

  function unknownPair(key: string, value: string): { target: string; label: string } {
    const keyRel = RELATION_WORDS.has(key)
    const valueRel = RELATION_WORDS.has(value)
    if (keyRel && !valueRel) return { target: value, label: key }
    return { target: key, label: value }
  }

  function consumeString(owner: BibleCharacter, key: string, value: string) {
    if (!value) return
    const keyChar = byName.get(normKey(key))
    const valueChar = byName.get(normKey(value))
    if (keyChar && keyChar.id !== owner.id) {
      addEdge(owner, keyChar.name, value)
      return
    }
    if (valueChar && valueChar.id !== owner.id) {
      addEdge(owner, valueChar.name, key)
      return
    }
    if (value.length > 40) return
    const pair = unknownPair(key, value)
    addEdge(owner, pair.target, pair.label)
  }

  function consumeObject(owner: BibleCharacter, key: string, obj: Record<string, unknown>) {
    const targetField = pickString(obj, ['target', 'with', 'to', 'character', 'who', 'name'])
    const labelField =
      pickString(obj, ['relation', 'type', 'label', 'rel', 'relationship', 'desc', 'description']) || '相关'
    const keyChar = key ? byName.get(normKey(key)) : undefined
    const keyIsOther = !!keyChar && keyChar.id !== owner.id
    if (targetField) {
      addEdge(owner, targetField, labelField === '相关' && key && !keyIsOther ? key : labelField)
      return
    }
    if (keyChar && keyIsOther) addEdge(owner, keyChar.name, labelField)
    else if (key && !META_KEYS.has(key)) addEdge(owner, key, labelField)
  }

  for (const character of characters) {
    const rel = asRelationshipRecord(character.relationships)
    if (!rel) continue

    for (const key of LIST_KEYS) {
      const list = rel[key]
      if (!Array.isArray(list)) continue
      for (const item of list) {
        if (typeof item === 'string') addEdge(character, item, '相关')
        else if (isRecord(item)) consumeObject(character, '', item)
      }
    }

    for (const [key, value] of Object.entries(rel)) {
      if (LIST_KEYS.has(key) || META_KEYS.has(key)) continue
      if (typeof value === 'string') {
        consumeString(character, key, value.trim())
      } else if (Array.isArray(value)) {
        const texts = value.filter((item): item is string => typeof item === 'string' && !!item.trim())
        const objects = value.filter(isRecord)
        const keyChar = byName.get(normKey(key))
        if (keyChar && keyChar.id !== character.id && texts.length) {
          addEdge(character, keyChar.name, texts.map((item) => item.trim()).join('、'))
        } else {
          for (const item of texts) addEdge(character, item.trim(), key)
        }
        for (const item of objects) consumeObject(character, key, item)
      } else if (isRecord(value)) {
        consumeObject(character, key, value)
      }
    }
  }

  const edges: RelEdge[] = [...bucket.values()].map((row) => ({
    id: `${row.sourceId}|${row.targetId}`,
    sourceId: row.sourceId,
    targetId: row.targetId,
    label: [...row.labels].join('、'),
  }))

  const used = new Set<string>()
  for (const edge of edges) {
    used.add(edge.sourceId)
    used.add(edge.targetId)
  }
  const visibleNodes = [...nodes.values()].filter((node) => used.has(node.id))
  const usedCharacters = new Set(
    visibleNodes.filter((node) => node.characterId != null).map((node) => node.characterId as number),
  )
  const bySource = new Map<number, { name: string; label: string }[]>()
  const nameOf = new Map(visibleNodes.map((node) => [node.id, node.name]))
  for (const edge of edges) {
    if (!edge.sourceId.startsWith('c')) continue
    const id = Number(edge.sourceId.slice(1))
    const list = bySource.get(id) || []
    list.push({ name: nameOf.get(edge.targetId) || edge.targetId, label: edge.label })
    bySource.set(id, list)
  }

  return {
    edges,
    nodes: visibleNodes,
    isolated: characters.filter((character) => !usedCharacters.has(character.id)).length,
    bySource,
  }
}

export function outgoingBrief(index: RelationIndex, characterId: number): string {
  const rows = index.bySource.get(characterId) || []
  return rows.map((row) => `${row.name}（${row.label}）`).join('、')
}

function shortText(value: string, max: number): string {
  const chars = [...value]
  if (chars.length <= max) return value
  return `${chars.slice(0, max - 1).join('')}…`
}

interface SimPoint {
  id: string
  x: number
  y: number
  vx: number
  vy: number
  tone: RelNode['tone']
}

function layoutPoints(nodes: RelNode[], edges: RelEdge[], width: number, height: number): Map<string, { x: number; y: number }> {
  const padX = 78
  const padY = 48
  const cx = width / 2
  const cy = height / 2
  const ordered = [...nodes].sort((a, b) => {
    const rank = (tone: RelNode['tone']) => (tone === 'lead' ? 0 : tone === 'rival' ? 2 : 1)
    return rank(a.tone) - rank(b.tone) || a.name.localeCompare(b.name, 'zh')
  })
  const pts: SimPoint[] = ordered.map((node, i) => {
    const angle = -Math.PI / 2 + (i / Math.max(ordered.length, 1)) * Math.PI * 2
    const radius = Math.min(width, height) * (ordered.length === 1 ? 0 : 0.28)
    return {
      id: node.id,
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
      tone: node.tone,
    }
  })
  const index = new Map(pts.map((point) => [point.id, point]))
  const iterations = ordered.length <= 1 ? 1 : 110
  for (let iter = 0; iter < iterations; iter++) {
    const cool = 1 - iter / iterations
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        let dx = pts[j].x - pts[i].x
        let dy = pts[j].y - pts[i].y
        let dist = Math.hypot(dx, dy) || 0.01
        const min = 96
        const force = (min * min) / dist
        const ux = dx / dist
        const uy = dy / dist
        pts[i].vx -= ux * force * 0.08
        pts[i].vy -= uy * force * 0.08
        pts[j].vx += ux * force * 0.08
        pts[j].vy += uy * force * 0.08
      }
    }
    for (const edge of edges) {
      const a = index.get(edge.sourceId)
      const b = index.get(edge.targetId)
      if (!a || !b) continue
      const dx = b.x - a.x
      const dy = b.y - a.y
      const dist = Math.hypot(dx, dy) || 0.01
      const rest = ordered.length > 8 ? 128 : 156
      const pull = 0.045 * (dist - rest)
      const ux = dx / dist
      const uy = dy / dist
      a.vx += ux * pull
      a.vy += uy * pull
      b.vx -= ux * pull
      b.vy -= uy * pull
    }
    for (const point of pts) {
      const gravity = point.tone === 'lead' ? 0.11 : 0.035
      point.vx += (cx - point.x) * gravity
      point.vy += (cy - point.y) * gravity
      point.vx *= 0.62
      point.vy *= 0.62
      const mag = Math.hypot(point.vx, point.vy) || 1
      const step = Math.min(mag, 7.5 * cool + 0.4)
      point.x += (point.vx / mag) * step
      point.y += (point.vy / mag) * step
      point.x = Math.max(padX, Math.min(width - padX, point.x))
      point.y = Math.max(padY, Math.min(height - padY, point.y))
    }
  }

  const minDist = 84
  for (let pass = 0; pass < 48; pass++) {
    let moved = false
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[j].x - pts[i].x
        const dy = pts[j].y - pts[i].y
        const dist = Math.hypot(dx, dy) || 0.01
        if (dist >= minDist) continue
        const push = (minDist - dist) / 2
        const ux = dx / dist
        const uy = dy / dist
        pts[i].x -= ux * push
        pts[i].y -= uy * push
        pts[j].x += ux * push
        pts[j].y += uy * push
        moved = true
      }
    }
    for (const point of pts) {
      point.x = Math.max(padX, Math.min(width - padX, point.x))
      point.y = Math.max(padY, Math.min(height - padY, point.y))
    }
    if (!moved) break
  }

  return new Map(pts.map((point) => [point.id, { x: point.x, y: point.y }]))
}

export function layoutGraph(characters: BibleCharacter[], width: number): GraphLayout | null {
  const indexed = indexRelationships(characters)
  if (!indexed.edges.length) return null
  const viewWidth = Math.max(280, Math.round(width))
  const n = indexed.nodes.length
  const viewHeight = Math.round(Math.min(460, Math.max(230, 168 + Math.sqrt(n) * 78)))
  const points = layoutPoints(indexed.nodes, indexed.edges, viewWidth, viewHeight)
  const reverse = new Set(indexed.edges.map((edge) => `${edge.targetId}|${edge.sourceId}`))
  const nodeR = 24
  const laidEdges: LaidEdge[] = indexed.edges.map((edge) => {
    const a = points.get(edge.sourceId) || { x: viewWidth / 2, y: viewHeight / 2 }
    const b = points.get(edge.targetId) || { x: viewWidth / 2, y: viewHeight / 2 }
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len = Math.hypot(dx, dy) || 1
    const ux = dx / len
    const uy = dy / len
    const x1 = a.x + ux * nodeR
    const y1 = a.y + uy * nodeR
    const x2 = b.x - ux * (nodeR + 6)
    const y2 = b.y - uy * (nodeR + 6)
    const mx = (x1 + x2) / 2
    const my = (y1 + y2) / 2
    const nx = -uy
    const ny = ux
    const mutual = reverse.has(`${edge.targetId}|${edge.sourceId}`)
    const sign = edge.sourceId < edge.targetId ? 1 : -1
    const bend = mutual ? 34 * sign : 0
    const cx = mx + nx * bend
    const cy = my + ny * bend
    const labelLift = bend === 0 ? -13 : 0
    return {
      ...edge,
      x1,
      y1,
      x2,
      y2,
      cx,
      cy,
      lx: 0.25 * x1 + 0.5 * cx + 0.25 * x2 + nx * labelLift,
      ly: 0.25 * y1 + 0.5 * cy + 0.25 * y2 + ny * labelLift,
    }
  })
  const nameOf = new Map(indexed.nodes.map((node) => [node.id, node.name]))
  const summary = laidEdges
    .map((edge) => `${nameOf.get(edge.sourceId) || ''}对${nameOf.get(edge.targetId) || ''}：${edge.label}`)
    .join('；')
  return {
    width: viewWidth,
    height: viewHeight,
    nodes: indexed.nodes.map((node) => {
      const point = points.get(node.id) || { x: viewWidth / 2, y: viewHeight / 2 }
      return {
        ...node,
        x: point.x,
        y: point.y,
        shortName: shortText(node.name, 6),
        glyph: [...node.name][0] || '·',
      }
    }),
    edges: laidEdges,
    isolated: indexed.isolated,
    summary: summary || '人物关系',
    hasExternal: indexed.nodes.some((node) => !node.known),
  }
}

function chapterNum(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const n = Math.trunc(value)
  return n >= 1 ? n : null
}

function chapterPct(chapter: number, min: number, max: number): number {
  if (max <= min) return 50
  return ((chapter - min) / (max - min)) * 100
}

function threadKind(threadType: string): TimelineLane['kind'] {
  if (threadType.includes('主线')) return 'main'
  if (threadType.includes('支线')) return 'side'
  return 'hook'
}

function ticksFor(min: number, max: number): TimelineTick[] {
  let chapters: number[]
  if (max <= min) chapters = [min]
  else if (max - min <= 4) {
    chapters = []
    for (let n = min; n <= max; n++) chapters.push(n)
  } else {
    const span = max - min
    chapters = [...new Set([min, min + Math.round(span / 3), min + Math.round((span * 2) / 3), max])].sort(
      (a, b) => a - b,
    )
  }
  return chapters.map((chapter, index) => {
    let align: TimelineTick['align'] = 'mid'
    if (chapters.length > 1 && index === 0) align = 'start'
    else if (chapters.length > 1 && index === chapters.length - 1) align = 'end'
    return { chapter, pct: chapterPct(chapter, min, max), align }
  })
}

export function buildTimeline(threads: BibleThread[]): TimelineModel | null {
  const marked: { thread: BibleThread; intro: number | null; resolved: number | null }[] = []
  const unmarked: { id: number; title: string }[] = []
  for (const thread of threads) {
    const intro = chapterNum(thread.introduced_chapter)
    const resolved = chapterNum(thread.resolved_chapter)
    if (intro == null && resolved == null) unmarked.push({ id: thread.id, title: thread.title })
    else marked.push({ thread, intro, resolved })
  }
  if (!marked.length) return null
  const chapters = marked.flatMap((row) => [row.intro, row.resolved].filter((n): n is number => n != null))
  const min = Math.min(...chapters)
  const max = Math.max(...chapters)
  const lanes: TimelineLane[] = marked
    .map((row) => {
      const intro = row.intro
      const resolved = row.resolved
      let start: number
      let end: number
      let open = false
      if (intro != null && resolved != null) {
        start = Math.min(intro, resolved)
        end = Math.max(intro, resolved)
      } else if (intro != null) {
        start = intro
        end = max
        open = true
      } else {
        start = resolved as number
        end = resolved as number
      }
      const point = start === end || max === min
      const leftPct = chapterPct(start, min, max)
      const widthPct = point ? 0 : Math.max(chapterPct(end, min, max) - leftPct, 0)
      return {
        id: row.thread.id,
        title: row.thread.title,
        threadType: row.thread.thread_type,
        status: row.thread.status,
        description: row.thread.description || '',
        kind: threadKind(row.thread.thread_type),
        start,
        end,
        open: open && !point,
        point,
        leftPct,
        widthPct,
      }
    })
    .sort((a, b) => a.start - b.start || a.end - b.end || a.id - b.id)

  return { min, max, ticks: ticksFor(min, max), lanes, unmarked }
}

export function threadSpan(thread: BibleThread): string {
  const intro = chapterNum(thread.introduced_chapter)
  const resolved = chapterNum(thread.resolved_chapter)
  const parts: string[] = []
  if (intro != null) parts.push(`第${intro}章出现`)
  if (resolved != null) parts.push(`第${resolved}章回收`)
  return parts.join(' · ')
}
