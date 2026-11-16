<script setup lang="ts">
import { RouterLink } from 'vue-router'
import {
  useUiPrefs,
  type UiAccent,
  type UiDensity,
  type UiLocale,
  type UiTheme,
} from '@/composables/useUiPrefs'
import { useChromeCopy } from '@/lib/chromeCopy'

const { theme, accent, density, locale, setTheme, setAccent, setDensity, setLocale, reset } =
  useUiPrefs()
const copy = useChromeCopy()

const themes: { id: UiTheme; label: string; copy: string }[] = [
  { id: 'mist', label: '薄雾', copy: '冷石板底，白天阅读' },
  { id: 'ink', label: '墨色', copy: '深石板，夜间长读' },
]

const accents: { id: UiAccent; label: string }[] = [
  { id: 'teal', label: '青绿' },
  { id: 'lagoon', label: '湖青' },
  { id: 'pine', label: '松绿' },
  { id: 'slate', label: '石板' },
]

const densities: { id: UiDensity; label: string; copy: string }[] = [
  { id: 'regular', label: '标准', copy: '标题和稿纸留出阅读空隙' },
  { id: 'compact', label: '紧凑', copy: '列表、步骤和正文收拢一档' },
]

const locales: { id: UiLocale; label: string; hint: 'localeZhHint' | 'localeEnHint' }[] = [
  { id: 'zh', label: '中文', hint: 'localeZhHint' },
  { id: 'en', label: 'English', hint: 'localeEnHint' },
]
</script>

<template>
  <div class="look">
    <header class="look__head">
      <p class="kicker">界面</p>
      <h1 class="page-title">外观</h1>
      <p class="page-desc">
        底色、强调色和疏密会立刻作用在整站，并只记在这台浏览器里。
        <RouterLink class="crumb" to="/settings/providers">模型连接在 LLM 设置。</RouterLink>
        <RouterLink class="crumb" to="/settings/skills">阶段写法单独安装。</RouterLink>
      </p>
    </header>

    <div class="look__layout">
      <div class="look__controls">
        <section class="look-block" aria-labelledby="look-theme">
          <h2 id="look-theme" class="look-block__title">底色</h2>
          <div class="look-grid">
            <button
              v-for="item in themes"
              :key="item.id"
              type="button"
              class="look-choice"
              :class="{ 'is-on': theme === item.id }"
              :aria-pressed="theme === item.id"
              @click="setTheme(item.id)"
            >
              <span class="look-theme" :data-theme="item.id" aria-hidden="true" />
              <span>
                <span class="look-choice__label">{{ item.label }}</span>
                <span class="look-choice__copy">{{ item.copy }}</span>
              </span>
            </button>
          </div>
        </section>

        <section class="look-block" aria-labelledby="look-accent">
          <h2 id="look-accent" class="look-block__title">强调色</h2>
          <div class="look-accents">
            <button
              v-for="item in accents"
              :key="item.id"
              type="button"
              class="look-choice look-choice--accent"
              :class="{ 'is-on': accent === item.id }"
              :aria-pressed="accent === item.id"
              @click="setAccent(item.id)"
            >
              <span class="look-swatch" :data-accent="item.id" aria-hidden="true" />
              <span class="look-choice__label">{{ item.label }}</span>
            </button>
          </div>
        </section>

        <section class="look-block" aria-labelledby="look-density">
          <h2 id="look-density" class="look-block__title">疏密</h2>
          <div class="look-grid">
            <button
              v-for="item in densities"
              :key="item.id"
              type="button"
              class="look-choice"
              :class="{ 'is-on': density === item.id }"
              :aria-pressed="density === item.id"
              @click="setDensity(item.id)"
            >
              <span class="look-density" :data-density="item.id" aria-hidden="true" />
              <span>
                <span class="look-choice__label">{{ item.label }}</span>
                <span class="look-choice__copy">{{ item.copy }}</span>
              </span>
            </button>
          </div>
        </section>

        <section class="look-block" aria-labelledby="look-locale">
          <h2 id="look-locale" class="look-block__title">{{ copy.localeTitle }}</h2>
          <div class="look-grid">
            <button
              v-for="item in locales"
              :key="item.id"
              type="button"
              class="look-choice"
              :class="{ 'is-on': locale === item.id }"
              :aria-pressed="locale === item.id"
              @click="setLocale(item.id)"
            >
              <span>
                <span class="look-choice__label">{{ item.label }}</span>
                <span class="look-choice__copy">{{ copy[item.hint] }}</span>
              </span>
            </button>
          </div>
        </section>

        <button class="btn-ghost" type="button" @click="reset">恢复默认</button>
      </div>

      <aside class="panel look-sample" aria-label="当前外观预览">
        <p class="kicker">预览</p>
        <p class="look-sample__title">长篇续写</p>
        <p class="look-sample__copy">导入、大纲、正文，沿同一条路径往下走。</p>
        <div class="look-sample__row">
          <span class="btn look-sample__btn">继续</span>
          <span class="status-pill status-pill--ok">就绪</span>
        </div>
      </aside>
    </div>
  </div>
</template>
