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
  lookKicker: string
  lookTitle: string
  lookLead: string
  lookLlm: string
  lookCraft: string
  themeTitle: string
  themeMist: string
  themeMistLine: string
  themeInk: string
  themeInkLine: string
  accentTitle: string
  accentTeal: string
  accentLagoon: string
  accentPine: string
  accentSlate: string
  densityTitle: string
  densityRegular: string
  densityRegularLine: string
  densityCompact: string
  densityCompactLine: string
  lookReset: string
  previewLabel: string
  previewKicker: string
  previewTitle: string
  previewLine: string
  previewContinue: string
  previewReady: string
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
    lookKicker: '界面',
    lookTitle: '外观',
    lookLead: '底色、强调色和疏密会立刻作用在整站，并只记在这台浏览器里。',
    lookLlm: '模型连接在 LLM 设置。',
    lookCraft: '阶段写法单独安装。',
    themeTitle: '底色',
    themeMist: '薄雾',
    themeMistLine: '冷石板底，白天阅读',
    themeInk: '墨色',
    themeInkLine: '深石板，夜间长读',
    accentTitle: '强调色',
    accentTeal: '青绿',
    accentLagoon: '湖青',
    accentPine: '松绿',
    accentSlate: '石板',
    densityTitle: '疏密',
    densityRegular: '标准',
    densityRegularLine: '标题和稿纸留出阅读空隙',
    densityCompact: '紧凑',
    densityCompactLine: '列表、步骤和正文收拢一档',
    lookReset: '恢复默认',
    previewLabel: '当前外观预览',
    previewKicker: '预览',
    previewTitle: '长篇续写',
    previewLine: '导入、大纲、正文，沿同一条路径往下走。',
    previewContinue: '继续',
    previewReady: '就绪',
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
    lookKicker: 'Interface',
    lookTitle: 'Appearance',
    lookLead: 'Theme, accent, and density apply across the site, and stay in this browser.',
    lookLlm: 'Model connection is in LLM settings.',
    lookCraft: 'Stage craft is installed separately.',
    themeTitle: 'Theme',
    themeMist: 'Mist',
    themeMistLine: 'Cool slate, for daytime reading',
    themeInk: 'Ink',
    themeInkLine: 'Dark slate, for long nights',
    accentTitle: 'Accent',
    accentTeal: 'Teal',
    accentLagoon: 'Lagoon',
    accentPine: 'Pine',
    accentSlate: 'Slate',
    densityTitle: 'Density',
    densityRegular: 'Regular',
    densityRegularLine: 'Room around titles and the page',
    densityCompact: 'Compact',
    densityCompactLine: 'Lists, steps, and prose sit tighter',
    lookReset: 'Reset',
    previewLabel: 'Appearance preview',
    previewKicker: 'Preview',
    previewTitle: 'Long-form',
    previewLine: 'Import, outline, prose. One path.',
    previewContinue: 'Continue',
    previewReady: 'Ready',
  },
}

export function useChromeCopy() {
  const { locale } = useUiPrefs()
  return computed(() => COPY[locale.value])
}
