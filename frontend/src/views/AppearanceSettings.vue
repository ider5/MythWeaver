<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useUiPrefs, type UiLocale } from '@/composables/useUiPrefs'
import { useChromeCopy } from '@/lib/chromeCopy'

const { theme, accent, density, locale, setTheme, setAccent, setDensity, setLocale, reset } =
  useUiPrefs()
const copy = useChromeCopy()

const themes = computed(() => [
  { id: 'mist' as const, label: copy.value.themeMist, line: copy.value.themeMistLine },
  { id: 'ink' as const, label: copy.value.themeInk, line: copy.value.themeInkLine },
])

const accents = computed(() => [
  { id: 'teal' as const, label: copy.value.accentTeal },
  { id: 'lagoon' as const, label: copy.value.accentLagoon },
  { id: 'pine' as const, label: copy.value.accentPine },
  { id: 'slate' as const, label: copy.value.accentSlate },
])

const densities = computed(() => [
  { id: 'regular' as const, label: copy.value.densityRegular, line: copy.value.densityRegularLine },
  { id: 'compact' as const, label: copy.value.densityCompact, line: copy.value.densityCompactLine },
])

const locales: { id: UiLocale; label: string; hint: 'localeZhHint' | 'localeEnHint' }[] = [
  { id: 'zh', label: '中文', hint: 'localeZhHint' },
  { id: 'en', label: 'English', hint: 'localeEnHint' },
]
</script>

<template>
  <div class="look">
    <header class="look__head">
      <p class="kicker">{{ copy.lookKicker }}</p>
      <h1 class="page-title">{{ copy.lookTitle }}</h1>
      <p class="page-desc">
        {{ copy.lookLead }}
        <RouterLink class="crumb" to="/settings/providers">{{ copy.lookLlm }}</RouterLink>
        <RouterLink class="crumb" to="/settings/skills">{{ copy.lookCraft }}</RouterLink>
      </p>
    </header>

    <div class="look__layout">
      <div class="look__controls">
        <section class="look-block" aria-labelledby="look-theme">
          <h2 id="look-theme" class="look-block__title">{{ copy.themeTitle }}</h2>
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
                <span class="look-choice__copy">{{ item.line }}</span>
              </span>
            </button>
          </div>
        </section>

        <section class="look-block" aria-labelledby="look-accent">
          <h2 id="look-accent" class="look-block__title">{{ copy.accentTitle }}</h2>
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
          <h2 id="look-density" class="look-block__title">{{ copy.densityTitle }}</h2>
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
                <span class="look-choice__copy">{{ item.line }}</span>
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

        <button class="btn-ghost" type="button" @click="reset">{{ copy.lookReset }}</button>
      </div>

      <aside class="panel look-sample" :aria-label="copy.previewLabel">
        <p class="kicker">{{ copy.previewKicker }}</p>
        <p class="look-sample__title">{{ copy.previewTitle }}</p>
        <p class="look-sample__copy">{{ copy.previewLine }}</p>
        <div class="look-sample__row">
          <span class="btn look-sample__btn">{{ copy.previewContinue }}</span>
          <span class="status-pill status-pill--ok">{{ copy.previewReady }}</span>
        </div>
      </aside>
    </div>
  </div>
</template>
