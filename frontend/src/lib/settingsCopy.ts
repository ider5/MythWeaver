import { computed } from 'vue'
import { useUiPrefs, type UiLocale } from '@/composables/useUiPrefs'

export interface SettingsCopy {
  providersKicker: string
  providersTitle: string
  providersLead: string
  providersHealthLink: string
  providersHealthTail: string
  providersLookLink: string
  fromStart: string
  backHome: string
  loadingSettings: string
  loadFailed: string
  activeTitle: string
  envSource: string
  profileSource: (name: string) => string
  draftLabel: string
  summaryLabel: string
  embedLabel: string
  sameAsDraft: string
  keyUnused: string
  keyConfigured: (mask: string) => string
  dims: (n: number) => string
  dimsMismatchBefore: string
  dimsMismatchBetween: string
  dimsMismatchAfter: string
  quoted: (text: string) => string
  savedTitle: string
  savedEmpty: string
  inUse: string
  profileEmbed: (model: string) => string
  profileKeys: (draftKey: string, embedKey: string) => string
  activate: string
  rename: string
  save: string
  cancel: string
  overwrite: string
  remove: string
  saveProfileTitle: string
  saveProfileLead: string
  nameLabel: string
  namePlaceholder: string
  activateOnSave: string
  saveAsProfile: string
  needName: string
  savedAndEnabled: (name: string) => string
  savedOnly: (name: string) => string
  enabledName: (name: string) => string
  renameFailed: string
  overwriteConfirm: (name: string) => string
  overwritten: (name: string) => string
  overwriteFailed: string
  deleteConfirm: (name: string, extra: string) => string
  deleteActiveExtra: string
  deleteFailed: string
  saveFailed: string
  activateFailed: string
  vendor: string
  docs: string
  baseUrl: string
  baseUrlPlaceholder: string
  modelLabel: string
  modelPlaceholder: string
  apiKey: string
  keyPlaceholder: string
  testing: string
  testConnection: string
  testHint: string
  connected: string
  connectFailed: string
  unknownError: string
  requestFailed: string
  replyBit: (reply: string) => string
  stagesTitle: string
  stagesLead: string
  healthKicker: string
  healthTitle: string
  healthLead: string
  healthOtherKey: string
  checking: string
  probing: string
  probeModel: string
  openLlm: string
  responded: string
  probeFailed: string
  probeSkipped: string
  healthStages: string
  noAddress: string
  configured: string
  notConfigured: string
  noModel: string
  noBooks: string
  pickPath: string
  glanceApi: string
  glanceOnline: string
  glanceDown: string
  glanceDb: string
  glanceDbOk: string
  glanceDbBad: string
  glanceBooks: (count: number) => string
  glanceLlm: string
  glanceUnconfigured: string
  glanceReachable: string
  glanceFail: string
  glanceConfigured: string
  healthNoResponse: string
  costKicker: string
  costTitle: string
  costLead: string
  totalUsd: string
  inputTokens: string
  outputTokens: string
  routesLead: string
  colStage: string
  colModel: string
  colPurposes: string
  routesEmpty: string
  byPurpose: string
  colPurpose: string
  colIn: string
  colOut: string
  colCost: string
  purposeEmpty: string
  recentTitle: string
  colInOut: string
  recentEmpty: string
}

const COPY: Record<UiLocale, SettingsCopy> = {
  zh: {
    providersKicker: '设置',
    providersTitle: '模型设置',
    providersLead:
      '当前续写和向量用的连接在下面。配置存在本机数据库，启用后马上生效。密钥只显示末四位。',
    providersHealthLink: '运行状态',
    providersHealthTail: '看接口、数据库和模型。',
    providersLookLink: '界面外观在这里调整。',
    fromStart: '保存或测通之后回到首页，选开书或续写。',
    backHome: '回到首页',
    loadingSettings: '加载设置…',
    loadFailed: '加载设置失败',
    activeTitle: '当前生效',
    envSource: '环境变量 .env',
    profileSource: (name) => `配置「${name}」`,
    draftLabel: '续写',
    summaryLabel: '摘要',
    embedLabel: '向量',
    sameAsDraft: '与续写相同',
    keyUnused: '未使用密钥',
    keyConfigured: (mask) => `已配置密钥 ${mask}`.trim(),
    dims: (n) => `${n} 维`,
    dimsMismatchBefore: '这条配置的向量维度是 ',
    dimsMismatchBetween: ' ，当前库按 ',
    dimsMismatchAfter: ' 建的。不一致时新向量可能进不了向量表。',
    quoted: (text) => `「${text}」`,
    savedTitle: '已存配置',
    savedEmpty: '还没有配置。没启用时继续用 .env。',
    inUse: '使用中',
    profileEmbed: (model) => ` · 向量 ${model}`,
    profileKeys: (draftKey, embedKey) => `续写${draftKey} · 向量${embedKey}`,
    activate: '启用',
    rename: '改名',
    save: '保存',
    cancel: '取消',
    overwrite: '用当前生效覆盖',
    remove: '删除',
    saveProfileTitle: '存下当前生效配置',
    saveProfileLead: '把上面正在用的地址、模型和密钥存成一条。密钥写入本机库，页面上不回显。',
    nameLabel: '名称',
    namePlaceholder: '例如 DeepSeek 长文',
    activateOnSave: '保存后启用',
    saveAsProfile: '存为配置',
    needName: '先写配置名称',
    savedAndEnabled: (name) => `已保存并启用「${name}」`,
    savedOnly: (name) => `已保存「${name}」`,
    enabledName: (name) => `已启用「${name}」`,
    renameFailed: '改名失败',
    overwriteConfirm: (name) =>
      `用当前生效配置覆盖「${name}」？原来的地址和密钥会被换掉。`,
    overwritten: (name) => `已用当前生效配置覆盖「${name}」`,
    overwriteFailed: '覆盖失败',
    deleteConfirm: (name, extra) => `删除配置「${name}」？${extra}`,
    deleteActiveExtra: '删除后回到 .env。',
    deleteFailed: '删除失败',
    saveFailed: '保存失败',
    activateFailed: '启用失败',
    vendor: '厂商',
    docs: '文档',
    baseUrl: 'Base URL',
    baseUrlPlaceholder: 'https://api.example.com/v1',
    modelLabel: '模型',
    modelPlaceholder: 'model-id',
    apiKey: 'API Key',
    keyPlaceholder: '仅用于本次探测',
    testing: '测试中…',
    testConnection: '测试连接',
    testHint: '只探测，不写入配置。匿名端点填 anonymous。',
    connected: '连接成功',
    connectFailed: '连接失败：',
    unknownError: '未知错误',
    requestFailed: '请求失败',
    replyBit: (reply) => `回复「${reply}」`,
    stagesTitle: '各阶段用的模型',
    stagesLead: '摘要和审校看摘要模型，大纲和续写看续写模型，向量单独走。启用配置后这里跟着变。',
    healthKicker: '设置',
    healthTitle: '运行状态',
    healthLead: '接口、数据库，以及当前生效的模型。探测会用这份续写密钥发一次短请求。',
    healthOtherKey: '用别的密钥测试。',
    checking: '正在检查…',
    probing: '探测中…',
    probeModel: '探测续写模型',
    openLlm: '打开 LLM 设置',
    responded: '有响应',
    probeFailed: '探测失败：',
    probeSkipped: '续写密钥还没配置。这里的探测不会发请求。',
    healthStages: '各阶段',
    noAddress: '未填地址',
    configured: '已配置',
    notConfigured: '未配置',
    noModel: '未填模型',
    noBooks: '还没有书。',
    pickPath: '选开书或续写。',
    glanceApi: '接口',
    glanceOnline: '在线',
    glanceDown: '无响应',
    glanceDb: '数据库',
    glanceDbOk: '可读写',
    glanceDbBad: '不可用',
    glanceBooks: (count) => `${count} 本`,
    glanceLlm: '续写模型',
    glanceUnconfigured: '未配置',
    glanceReachable: '连通',
    glanceFail: '失败',
    glanceConfigured: '已配置',
    healthNoResponse: '接口没有响应',
    costKicker: '用量',
    costTitle: '成本',
    costLead: '这本书的阶段模型、用途和最近调用。',
    totalUsd: '总成本 (USD)',
    inputTokens: '输入 tokens',
    outputTokens: '输出 tokens',
    routesLead: '服务端按阶段绑的模型，来自配置。',
    colStage: '阶段',
    colModel: '模型',
    colPurposes: '用途标签',
    routesEmpty: '还没有模型配置',
    byPurpose: '按用途（tokens + 成本）',
    colPurpose: '用途',
    colIn: 'in',
    colOut: 'out',
    colCost: '成本',
    purposeEmpty: '还没有记录',
    recentTitle: '最近调用',
    colInOut: 'in/out',
    recentEmpty: '还没有调用记录',
  },
  en: {
    providersKicker: 'Settings',
    providersTitle: 'Model settings',
    providersLead:
      'Draft and embedding connections are below. Profiles live in the local database and apply as soon as you enable one. Keys show only the last four characters.',
    providersHealthLink: 'Status',
    providersHealthTail: 'shows the API, database, and models.',
    providersLookLink: 'Appearance is adjusted here.',
    fromStart: 'After a save or a successful test, go back home and choose start or continue.',
    backHome: 'Back home',
    loadingSettings: 'Loading settings…',
    loadFailed: 'Could not load settings',
    activeTitle: 'In effect',
    envSource: 'Environment file .env',
    profileSource: (name) => `Profile “${name}”`,
    draftLabel: 'Draft',
    summaryLabel: 'Summary',
    embedLabel: 'Embeddings',
    sameAsDraft: 'Same as draft',
    keyUnused: 'No key',
    keyConfigured: (mask) => `Key set ${mask}`.trim(),
    dims: (n) => `${n} dims`,
    dimsMismatchBefore: 'This profile’s embedding size is ',
    dimsMismatchBetween: '. The library was built at ',
    dimsMismatchAfter: '. When they differ, new vectors may not enter the vector table.',
    quoted: (text) => `“${text}”`,
    savedTitle: 'Saved profiles',
    savedEmpty: 'No profiles yet. Until one is enabled, .env stays in effect.',
    inUse: 'In use',
    profileEmbed: (model) => ` · embeddings ${model}`,
    profileKeys: (draftKey, embedKey) => `Draft ${draftKey} · Embeddings ${embedKey}`,
    activate: 'Enable',
    rename: 'Rename',
    save: 'Save',
    cancel: 'Cancel',
    overwrite: 'Overwrite with current',
    remove: 'Delete',
    saveProfileTitle: 'Save the current setup',
    saveProfileLead:
      'Store the address, model, and key in effect above as one profile. The key is written to the local database and is not shown again.',
    nameLabel: 'Name',
    namePlaceholder: 'For example, DeepSeek long form',
    activateOnSave: 'Enable after saving',
    saveAsProfile: 'Save profile',
    needName: 'Write a profile name first',
    savedAndEnabled: (name) => `Saved and enabled “${name}”`,
    savedOnly: (name) => `Saved “${name}”`,
    enabledName: (name) => `Enabled “${name}”`,
    renameFailed: 'Could not rename',
    overwriteConfirm: (name) =>
      `Overwrite “${name}” with the setup in effect? The old address and key will be replaced.`,
    overwritten: (name) => `Overwrote “${name}” with the setup in effect`,
    overwriteFailed: 'Could not overwrite',
    deleteConfirm: (name, extra) =>
      extra ? `Delete profile “${name}”? ${extra}` : `Delete profile “${name}”?`,
    deleteActiveExtra: 'After deletion, .env is used again.',
    deleteFailed: 'Could not delete',
    saveFailed: 'Could not save',
    activateFailed: 'Could not enable',
    vendor: 'Provider',
    docs: 'Docs',
    baseUrl: 'Base URL',
    baseUrlPlaceholder: 'https://api.example.com/v1',
    modelLabel: 'Model',
    modelPlaceholder: 'model-id',
    apiKey: 'API Key',
    keyPlaceholder: 'Used only for this probe',
    testing: 'Testing…',
    testConnection: 'Test connection',
    testHint: 'Probe only. Nothing is written. For an anonymous endpoint, enter anonymous.',
    connected: 'Connected',
    connectFailed: 'Connection failed: ',
    unknownError: 'Unknown error',
    requestFailed: 'Request failed',
    replyBit: (reply) => `reply “${reply}”`,
    stagesTitle: 'Models by stage',
    stagesLead:
      'Summary and critique use the summary model. Outline and draft use the draft model. Embeddings are separate. This list follows the enabled profile.',
    healthKicker: 'Settings',
    healthTitle: 'Status',
    healthLead:
      'API, database, and the model in effect. A probe sends one short request with this draft key.',
    healthOtherKey: 'Test with another key.',
    checking: 'Checking…',
    probing: 'Probing…',
    probeModel: 'Probe the draft model',
    openLlm: 'Open LLM settings',
    responded: 'Responded',
    probeFailed: 'Probe failed: ',
    probeSkipped: 'The draft key is not set. This probe will not send a request.',
    healthStages: 'Stages',
    noAddress: 'No address',
    configured: 'Configured',
    notConfigured: 'Not configured',
    noModel: 'No model',
    noBooks: 'No books yet.',
    pickPath: 'Choose start or continue.',
    glanceApi: 'API',
    glanceOnline: 'Online',
    glanceDown: 'No response',
    glanceDb: 'Database',
    glanceDbOk: 'Read and write',
    glanceDbBad: 'Unavailable',
    glanceBooks: (count) => `${count} ${count === 1 ? 'book' : 'books'}`,
    glanceLlm: 'Draft model',
    glanceUnconfigured: 'Not set',
    glanceReachable: 'Reachable',
    glanceFail: 'Failed',
    glanceConfigured: 'Set',
    healthNoResponse: 'The API did not respond',
    costKicker: 'Usage',
    costTitle: 'Cost',
    costLead: 'Stage models, purposes, and recent calls for this book.',
    totalUsd: 'Total cost (USD)',
    inputTokens: 'Input tokens',
    outputTokens: 'Output tokens',
    routesLead: 'Models bound to each stage on the server, from configuration.',
    colStage: 'Stage',
    colModel: 'Model',
    colPurposes: 'Purpose tags',
    routesEmpty: 'No model configuration yet',
    byPurpose: 'By purpose (tokens + cost)',
    colPurpose: 'Purpose',
    colIn: 'in',
    colOut: 'out',
    colCost: 'Cost',
    purposeEmpty: 'No records yet',
    recentTitle: 'Recent calls',
    colInOut: 'in/out',
    recentEmpty: 'No calls yet',
  },
}

export function useSettingsCopy() {
  const { locale } = useUiPrefs()
  return computed(() => COPY[locale.value])
}
