import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export type NovelRole = 'manuscript' | 'reference'
export type NovelOrigin = 'import' | 'scratch'

export interface Novel {
  id: number
  title: string
  author?: string | null
  genre: string
  description?: string
  /** manuscript=原稿，可续写导出；reference=参考，不进入正文 */
  role?: NovelRole
  /** import=导入续写；scratch=从零开书 */
  origin?: NovelOrigin
  premise?: string | null
  writing_style?: string | null
  status: string
  total_chars: number
  chapter_count: number
  avg_chapter_chars?: number
  median_chapter_chars?: number
  created_at: string
  updated_at: string
}

export interface ChapterPreview {
  index: number
  title: string
  volume?: string
  char_count: number
  preview: string
}

export interface ImportPreview {
  title: string
  total_chars: number
  chapter_count: number
  chapters: ChapterPreview[]
  import_token: string
}

export interface Task {
  id: number
  novel_id?: number
  task_type: string
  status: string
  progress: number
  message: string
  result?: Record<string, unknown> | null
  error?: string | null
  recoverable?: boolean
  created_at?: string
  updated_at?: string
}

export interface Character {
  id: number
  novel_id: number
  name: string
  aliases: string[]
  role?: string
  status?: string
  personality?: string
  speech_style?: string
  relationships: Record<string, unknown>
  last_appear_chapter?: number
  notes?: string
}

export interface WorldSetting {
  id: number
  novel_id: number
  category: string
  title: string
  content: string
  do_not_violate?: string
}

export interface PlotThread {
  id: number
  novel_id: number
  title: string
  description?: string
  thread_type: string
  status: string
  introduced_chapter?: number | null
  resolved_chapter?: number | null
  planned_resolve_chapter?: number | null
}

export interface OpenThread {
  id: number
  title: string
  thread_type: string
  status: string
  introduced_chapter?: number | null
  planned_resolve_chapter?: number | null
  due?: 'approaching' | 'due' | 'overdue' | null
  note: string
}

export interface QualityHint {
  id: string
  kind: string
  severity: string
  message: string
  detail?: string | null
}

export interface WritebackField {
  key: string
  label: string
  before?: string | null
  after?: string | null
}

export interface WritebackChange {
  id: string
  kind: string
  op: string
  target_id?: number | null
  label: string
  summary: string
  fields: WritebackField[]
  after?: Record<string, unknown>
}

export interface BibleProposal {
  id: number
  novel_id: number
  chapter_id?: number | null
  chapter_index?: number | null
  chapter_title?: string | null
  status: string
  changes: WritebackChange[]
  created_at: string
  updated_at: string
}

export interface OutlineItem {
  id: number
  outline_id: number
  order: number
  title: string
  summary: string
  key_points: string[]
  purpose: string
  conflict: string
  suspense_hook: string
  characters: string[]
  status: string
}

export interface Outline {
  id: number
  novel_id: number
  title: string
  status: string
  start_from_chapter: number
  items: OutlineItem[]
}

export interface ScratchSeed {
  novel: Novel
  characters: Character[]
  world_settings: WorldSetting[]
  plot_threads: PlotThread[]
}

export const novelsApi = {
  list: (role?: NovelRole) =>
    api.get<Novel[]>('/novels', { params: role ? { role } : {} }),
  get: (id: number) => api.get<Novel>(`/novels/${id}`),
  create: (body: {
    title: string
    author?: string
    genre?: string
    description?: string
    role?: NovelRole
  }) => api.post<Novel>('/novels', body),
  update: (
    id: number,
    body: {
      title?: string
      author?: string | null
      genre?: string
      premise?: string
      writing_style?: string
    },
  ) => api.patch<Novel>(`/novels/${id}`, body),
  createScratch: (body: {
    title: string
    author?: string
    genre?: string
    premise: string
    writing_style: string
  }) => api.post<Novel>('/novels/scratch', body),
  seedScratch: (id: number) => api.post<ScratchSeed>(`/novels/${id}/scratch/seed`),
  remove: (id: number) => api.delete(`/novels/${id}`),
  /** 导出全书章节正文；format: txt（默认）| md | epub */
  exportUrl: (id: number, format: 'txt' | 'md' | 'epub' = 'txt') =>
    `/api/novels/${id}/export?format=${format}`,
  /** 下载这本小说的数据行 ZIP */
  backupUrl: (id: number) => `/api/novels/${id}/backup`,
  restoreBackup: (form: FormData) => api.post<Novel>('/novels/backup/restore', form),
  previewImport: (form: FormData) =>
    api.post<ImportPreview>('/novels/import/preview', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  confirmImport: (body: {
    import_token: string
    title?: string
    author?: string
    genre?: string
    role?: NovelRole
  }) => api.post<Novel>('/novels/import/confirm', body),
  ingest: (id: number) => api.post<{ task_id: number }>(`/novels/${id}/ingest`),
  chapters: (id: number) =>
    api.get<
      Array<{
        id: number
        novel_id: number
        index: number
        title: string
        volume?: string
        char_count: number
        status: string
        is_generated: boolean
        outline_item_id?: number | null
        content?: string | null
      }>
    >(`/novels/${id}/chapters`),
  chapter: (nid: number, cid: number) =>
    api.get<{
      id: number
      novel_id: number
      index: number
      title: string
      volume?: string
      char_count: number
      status: string
      is_generated: boolean
      outline_item_id?: number | null
      content?: string | null
    }>(`/novels/${nid}/chapters/${cid}`),
  openThreads: (nid: number, chapterIndex: number) =>
    api.get<{ chapter_index: number; threads: OpenThread[] }>(`/novels/${nid}/open-threads`, {
      params: { chapter_index: chapterIndex },
    }),
  chapterQuality: (nid: number, cid: number) =>
    api.get<{ chapter_index: number; critical: boolean; hints: QualityHint[] }>(
      `/novels/${nid}/chapters/${cid}/quality`,
    ),
  chapterByOutlineItem: (nid: number, outlineItemId: number) =>
    api.get<{
      id: number
      novel_id: number
      index: number
      title: string
      volume?: string
      char_count: number
      status: string
      is_generated: boolean
      outline_item_id?: number | null
      content?: string | null
    }>(`/novels/${nid}/chapters/by-outline-item/${outlineItemId}`),
  versions: (nid: number, cid: number) =>
    api.get<
      Array<{
        id: number
        chapter_id: number
        version_type: string
        content: string
        consistency_report?: Record<string, unknown> | null
        parent_version_id?: number | null
        created_at: string
      }>
    >(`/novels/${nid}/chapters/${cid}/versions`),
  revise: (nid: number, cid: number, content: string, commit = true) =>
    api.post<{
      id: number
      chapter_id: number
      version_type: string
      content: string
      consistency_report?: Record<string, unknown> | null
      parent_version_id?: number | null
      created_at: string
      task_id?: number | null
    }>(`/novels/${nid}/chapters/${cid}/revise`, {
      content,
      commit_to_knowledge: commit,
    }),
  criticSelectRevise: (
    nid: number,
    cid: number,
    body: {
      content: string
      issues: Array<{ type: string; severity?: string; message: string; detail?: string | null }>
      confirm?: boolean
      commit_to_knowledge?: boolean
    },
  ) =>
    api.post<{
      base_content: string
      revised_content: string
      consistency?: Record<string, unknown> | null
      changed: boolean
      version_id?: number | null
      task_id?: number | null
    }>(`/novels/${nid}/chapters/${cid}/critic-select-revise`, body),
  /** 仅重新入队知识库增量更新，不新建 user_edited 版本（用于入库失败重试） */
  commitKnowledge: (nid: number, cid: number) =>
    api.post<{
      chapter_id: number
      task_id: number
      version_id?: number | null
    }>(`/novels/${nid}/chapters/${cid}/commit-knowledge`),
  removeChapter: (nid: number, cid: number) =>
    api.delete<{
      message: string
      chapter_id: number
      chapter_index: number
      outline_item_id?: number | null
      outline_item_reset: boolean
    }>(`/novels/${nid}/chapters/${cid}`),
  removeChapterVersion: (nid: number, cid: number, vid: number) =>
    api.delete<{
      message: string
      chapter_id: number
      version_id: number
      chapter_deleted: boolean
      content_rolled_back: boolean
      remaining_versions: number
      outline_item_id?: number | null
      outline_item_reset: boolean
      chapter_index?: number
      active_content?: string | null
    }>(`/novels/${nid}/chapters/${cid}/versions/${vid}`),
}

export const bibleApi = {
  get: (id: number) =>
    api.get<{ characters: Character[]; world_settings: WorldSetting[]; plot_threads: PlotThread[] }>(
      `/novels/${id}/bible`,
    ),
  createCharacter: (id: number, body: Partial<Character>) =>
    api.post(`/novels/${id}/bible/characters`, body),
  updateCharacter: (id: number, cid: number, body: Partial<Character>) =>
    api.patch(`/novels/${id}/bible/characters/${cid}`, body),
  deleteCharacter: (id: number, cid: number) => api.delete(`/novels/${id}/bible/characters/${cid}`),
  createWorld: (id: number, body: Partial<WorldSetting>) =>
    api.post(`/novels/${id}/bible/world-settings`, body),
  updateWorld: (id: number, wid: number, body: Partial<WorldSetting>) =>
    api.patch(`/novels/${id}/bible/world-settings/${wid}`, body),
  deleteWorld: (id: number, wid: number) => api.delete(`/novels/${id}/bible/world-settings/${wid}`),
  createThread: (id: number, body: Partial<PlotThread>) =>
    api.post(`/novels/${id}/bible/plot-threads`, body),
  updateThread: (id: number, tid: number, body: Partial<PlotThread>) =>
    api.patch(`/novels/${id}/bible/plot-threads/${tid}`, body),
  deleteThread: (id: number, tid: number) => api.delete(`/novels/${id}/bible/plot-threads/${tid}`),
  listProposals: (id: number, status = 'pending') =>
    api.get<BibleProposal[]>(`/novels/${id}/bible/proposals`, { params: { status } }),
  proposeWriteback: (id: number, chapterId: number, force = false) =>
    api.post<BibleProposal>(`/novels/${id}/bible/proposals`, { chapter_id: chapterId, force }),
  applyProposal: (id: number, proposalId: number, changeIds?: string[]) =>
    api.post<BibleProposal>(`/novels/${id}/bible/proposals/${proposalId}/apply`, {
      change_ids: changeIds ?? null,
    }),
  dismissProposal: (id: number, proposalId: number) =>
    api.post<BibleProposal>(`/novels/${id}/bible/proposals/${proposalId}/dismiss`),
}

export const outlineApi = {
  list: (id: number) => api.get<Outline[]>(`/novels/${id}/outlines`),
  generate: (id: number, body: { chapter_count: number; guidance?: string }) =>
    api.post<{ task_id: number; status: string }>(`/novels/${id}/outlines/generate`, body),
  update: (nid: number, oid: number, body: unknown) =>
    api.put<Outline>(`/novels/${nid}/outlines/${oid}`, body),
  confirm: (nid: number, oid: number) => api.post<Outline>(`/novels/${nid}/outlines/${oid}/confirm`),
  remove: (nid: number, oid: number) =>
    api.delete<{ message: string; outline_id: number; unbound_chapters: number }>(
      `/novels/${nid}/outlines/${oid}`,
    ),
}

export const generationApi = {
  batch: (
    novelId: number,
    body: {
      outline_id: number
      from_order: number
      count: number
      run_critic: boolean
      spot_check?: boolean
    },
  ) =>
    api.post<{ task_id: number; status: string }>(`/novels/${novelId}/generate/batch`, body),
}

export const tasksApi = {
  get: (id: number) => api.get<Task>(`/tasks/${id}`),
  list: (novelId?: number) =>
    api.get<Task[]>('/tasks', { params: novelId ? { novel_id: novelId } : {} }),
  cancel: (id: number) => api.post<Task>(`/tasks/${id}/cancel`),
  retry: (id: number) => api.post<Task>(`/tasks/${id}/retry`),
  /** SSE 实时进度：/api/tasks/{id}/events */
  eventsUrl: (id: number) => `/api/tasks/${id}/events`,
}

export const costsApi = {
  summary: (novelId?: number) =>
    api.get('/costs', { params: novelId ? { novel_id: novelId } : {} }),
}

export const configApi = {
  get: () => api.get('/config'),
}

export interface HealthCheck {
  ok: boolean
  detail: string
}

export interface HealthLlmStage {
  stage: string
  label: string
  configured: boolean
  provider: string
  model: string
  base_url: string
}

export interface HealthLlmCheck extends HealthCheck {
  configured: boolean
  probed: boolean
  latency_ms?: number | null
  reply?: string | null
  stages: HealthLlmStage[]
}

export interface HealthReport {
  status: 'ok' | 'degraded'
  app: string
  ready: boolean
  first_run: boolean
  novel_count: number
  checks: {
    api: HealthCheck
    db: HealthCheck
    llm: HealthLlmCheck
  }
}

export const healthApi = {
  get: (probe = false) =>
    api.get<HealthReport>('/health', {
      params: probe ? { probe: 'llm' } : {},
      validateStatus: (status) => status === 200 || status === 503,
    }),
}

export interface ProviderPreset {
  id: string
  label: string
  base_url: string
  default_model: string
  models: string[]
  docs_url: string
  notes: string
}

export interface ConnectionTestResult {
  ok: boolean
  error?: string | null
  latency_ms?: number | null
  reply?: string | null
  base_url?: string | null
  model?: string | null
}

export interface KeyStatus {
  mode: 'anonymous' | 'keyed'
  mask: string | null
}

export interface LLMProfile {
  id: number
  name: string
  vendor_id: string | null
  is_active: boolean
  summary_follows_generation: boolean
  generation_provider: string
  generation_base_url: string
  generation_model: string
  generation_key: KeyStatus
  summary_provider: string
  summary_base_url: string
  summary_model: string
  summary_key: KeyStatus
  embedding_base_url: string
  embedding_model: string
  embedding_dims: number
  embedding_key: KeyStatus
}

export interface ActiveLLMSettings {
  source: 'env' | 'profile'
  profile_id: number | null
  profile_name: string | null
  vendor_id: string | null
  summary_follows_generation: boolean
  generation_provider: string
  generation_base_url: string
  generation_model: string
  generation_key: KeyStatus
  summary_provider: string
  summary_base_url: string
  summary_model: string
  summary_key: KeyStatus
  embedding_base_url: string
  embedding_model: string
  embedding_dims: number
  embedding_key: KeyStatus
  vec_dims: number
  dims_mismatch: boolean
}

export const providersApi = {
  list: () => api.get<{ presets: ProviderPreset[] }>('/providers'),
  active: () => api.get<ActiveLLMSettings>('/providers/active'),
  profiles: () => api.get<{ profiles: LLMProfile[] }>('/providers/profiles'),
  createProfile: (body: {
    name: string
    from_current?: boolean
    activate?: boolean
    vendor_id?: string | null
    summary_follows_generation?: boolean
    generation_provider?: string
    generation_base_url?: string
    generation_api_key?: string
    generation_model?: string
    embedding_base_url?: string
    embedding_api_key?: string
    embedding_model?: string
    embedding_dims?: number | null
  }) => api.post<LLMProfile>('/providers/profiles', body),
  updateProfile: (id: number, body: { name?: string }) =>
    api.patch<LLMProfile>(`/providers/profiles/${id}`, body),
  activateProfile: (id: number) => api.post<LLMProfile>(`/providers/profiles/${id}/activate`),
  updateProfileFromCurrent: (id: number) =>
    api.post<LLMProfile>(`/providers/profiles/${id}/update-from-current`),
  deleteProfile: (id: number) => api.delete<{ message: string }>(`/providers/profiles/${id}`),
  test: (body: {
    vendor_id?: string | null
    api_key: string
    base_url?: string | null
    model?: string | null
  }) => api.post<ConnectionTestResult>('/providers/test', body),
}
