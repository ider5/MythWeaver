import { computed } from 'vue'
import { useUiPrefs, type UiLocale } from '@/composables/useUiPrefs'

export interface ChromeCopy {
  navWorks: string
  navStart: string
  navContinue: string
  navLlm: string
  navCraft: string
  navStatus: string
  navLook: string
  homeStart: string
  homeContinue: string
  emptyStart: string
  emptyImport: string
  emptyReference: string
  importGroup: string
  importManuscript: string
  importManuscriptLine: string
  importManuscriptNote: string
  importReference: string
  importReferenceLine: string
  importReferenceNote: string
  localeTitle: string
  localeZhHint: string
  localeEnHint: string
}

const COPY: Record<UiLocale, ChromeCopy> = {
  zh: {
    navWorks: '作品',
    navStart: '开书',
    navContinue: '续写',
    navLlm: 'LLM 设置',
    navCraft: '写法',
    navStatus: '状态',
    navLook: '外观',
    homeStart: '开书',
    homeContinue: '续写',
    emptyStart: '从零开书',
    emptyImport: '导入续写',
    emptyReference: '导入参考',
    importGroup: '导入用途',
    importManuscript: '原稿',
    importManuscriptLine: '接着写这本书',
    importManuscriptNote: '入库后可大纲、续写，并导出成书。',
    importReference: '参考',
    importReferenceLine: '只拆文风与结构',
    importReferenceNote: '不会成为可续写正文，也不会导出成书。',
    localeTitle: '界面语言',
    localeZhHint: '默认',
    localeEnHint: '导航和主要按钮',
  },
  en: {
    navWorks: 'Works',
    navStart: 'Start',
    navContinue: 'Continue',
    navLlm: 'LLM',
    navCraft: 'Craft',
    navStatus: 'Status',
    navLook: 'Look',
    homeStart: 'Start',
    homeContinue: 'Continue',
    emptyStart: 'Start a book',
    emptyImport: 'Import to continue',
    emptyReference: 'Import a reference',
    importGroup: 'Import purpose',
    importManuscript: 'Manuscript',
    importManuscriptLine: 'Continue this book',
    importManuscriptNote: 'After import you can outline, continue, and export the book.',
    importReference: 'Reference',
    importReferenceLine: 'Style and structure only',
    importReferenceNote: 'It will not become continuable prose, and it will not export as a book.',
    localeTitle: 'Language',
    localeZhHint: 'Default',
    localeEnHint: 'Nav and primary buttons',
  },
}

export function useChromeCopy() {
  const { locale } = useUiPrefs()
  return computed(() => COPY[locale.value])
}
