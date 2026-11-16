import { ref, watch } from 'vue'

export const UI_STORAGE_KEY = 'mythweaver.ui'

export const UI_THEMES = ['mist', 'ink'] as const
export const UI_ACCENTS = ['teal', 'lagoon', 'pine', 'slate'] as const
export const UI_DENSITIES = ['regular', 'compact'] as const

export type UiTheme = (typeof UI_THEMES)[number]
export type UiAccent = (typeof UI_ACCENTS)[number]
export type UiDensity = (typeof UI_DENSITIES)[number]

export interface UiPrefs {
  theme: UiTheme
  accent: UiAccent
  density: UiDensity
}

const DEFAULTS: UiPrefs = {
  theme: 'mist',
  accent: 'teal',
  density: 'regular',
}

const theme = ref<UiTheme>(DEFAULTS.theme)
const accent = ref<UiAccent>(DEFAULTS.accent)
const density = ref<UiDensity>(DEFAULTS.density)

function allowed<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return typeof value === 'string' && (options as readonly string[]).includes(value)
    ? (value as T)
    : fallback
}

export function readUiPrefs(): UiPrefs {
  if (typeof localStorage === 'undefined') return { ...DEFAULTS }
  try {
    const raw = localStorage.getItem(UI_STORAGE_KEY)
    if (!raw) return { ...DEFAULTS }
    const data = JSON.parse(raw) as Partial<UiPrefs>
    return {
      theme: allowed(data.theme, UI_THEMES, DEFAULTS.theme),
      accent: allowed(data.accent, UI_ACCENTS, DEFAULTS.accent),
      density: allowed(data.density, UI_DENSITIES, DEFAULTS.density),
    }
  } catch {
    return { ...DEFAULTS }
  }
}

function currentPrefs(): UiPrefs {
  return { theme: theme.value, accent: accent.value, density: density.value }
}

export function applyUiPrefs(prefs: UiPrefs) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.theme = prefs.theme
  root.dataset.accent = prefs.accent
  root.dataset.density = prefs.density
}

function persist(prefs: UiPrefs) {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(UI_STORAGE_KEY, JSON.stringify(prefs))
}

let started = false

export function installUiPrefs() {
  if (started) return
  started = true
  const saved = readUiPrefs()
  theme.value = saved.theme
  accent.value = saved.accent
  density.value = saved.density
  applyUiPrefs(saved)
  watch([theme, accent, density], () => {
    const next = currentPrefs()
    applyUiPrefs(next)
    persist(next)
  })
}

export function useUiPrefs() {
  installUiPrefs()

  function setTheme(next: UiTheme) {
    theme.value = next
  }

  function setAccent(next: UiAccent) {
    accent.value = next
  }

  function setDensity(next: UiDensity) {
    density.value = next
  }

  function reset() {
    theme.value = DEFAULTS.theme
    accent.value = DEFAULTS.accent
    density.value = DEFAULTS.density
  }

  return { theme, accent, density, setTheme, setAccent, setDensity, reset }
}
