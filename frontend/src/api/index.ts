import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export interface Novel {
  id: number
  title: string
  author?: string
  genre: string
  description?: string
  status: string
  total_chars: number
  chapter_count: number
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
  result?: Record<string, unknown>
  error?: string
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
  introduced_chapter?: number
  resolved_chapter?: number
}

export interface OutlineItem {
  id: number
  outline_id: number
  order: number
  title: string
  summary: string
  key_points: string[]
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

export const novelsApi = {
  list: () => api.get<Novel[]>('/novels'),
  get: (id: number) => api.get<Novel>(`/novels/${id}`),
  remove: (id: number) => api.delete(`/novels/${id}`),
  previewImport: (form: FormData) =>
    api.post<ImportPreview>('/novels/import/preview', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  confirmImport: (body: {
    import_token: string
    title?: string
    author?: string
    genre?: string
  }) => api.post<Novel>('/novels/import/confirm', body),
  ingest: (id: number) => api.post<{ task_id: number }>(`/novels/${id}/ingest`),
  chapters: (id: number) => api.get(`/novels/${id}/chapters`),
  chapter: (nid: number, cid: number) => api.get(`/novels/${nid}/chapters/${cid}`),
  versions: (nid: number, cid: number) => api.get(`/novels/${nid}/chapters/${cid}/versions`),
  revise: (nid: number, cid: number, content: string, commit = true) =>
    api.post(`/novels/${nid}/chapters/${cid}/revise`, {
      content,
      commit_to_knowledge: commit,
    }),
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
}

export const outlineApi = {
  list: (id: number) => api.get<Outline[]>(`/novels/${id}/outlines`),
  generate: (id: number, body: { chapter_count: number; guidance?: string }) =>
    api.post<Outline>(`/novels/${id}/outlines/generate`, body),
  update: (nid: number, oid: number, body: unknown) =>
    api.put<Outline>(`/novels/${nid}/outlines/${oid}`, body),
  confirm: (nid: number, oid: number) => api.post<Outline>(`/novels/${nid}/outlines/${oid}/confirm`),
}

export const tasksApi = {
  get: (id: number) => api.get<Task>(`/tasks/${id}`),
  list: (novelId?: number) =>
    api.get<Task[]>('/tasks', { params: novelId ? { novel_id: novelId } : {} }),
}

export const costsApi = {
  summary: (novelId?: number) =>
    api.get('/costs', { params: novelId ? { novel_id: novelId } : {} }),
}

export const configApi = {
  get: () => api.get('/config'),
}
