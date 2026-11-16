<script setup lang="ts">
import { useChromeCopy } from '@/lib/chromeCopy'

defineProps<{ modelValue: 'manuscript' | 'reference' }>()
const emit = defineEmits<{ 'update:modelValue': ['manuscript' | 'reference'] }>()
const copy = useChromeCopy()
</script>

<template>
  <div class="role-choice" role="radiogroup" :aria-label="copy.importGroup">
    <label class="role-choice__item" :class="{ 'is-on': modelValue === 'manuscript' }">
      <input
        class="sr-only"
        type="radio"
        name="novel-role"
        value="manuscript"
        :checked="modelValue === 'manuscript'"
        @change="emit('update:modelValue', 'manuscript')"
      />
      <span class="role-choice__name">{{ copy.importManuscript }}</span>
      <span class="role-choice__line">{{ copy.importManuscriptLine }}</span>
      <span class="role-choice__note">{{ copy.importManuscriptNote }}</span>
    </label>
    <label
      class="role-choice__item role-choice__item--ref"
      :class="{ 'is-on': modelValue === 'reference' }"
    >
      <input
        class="sr-only"
        type="radio"
        name="novel-role"
        value="reference"
        :checked="modelValue === 'reference'"
        @change="emit('update:modelValue', 'reference')"
      />
      <span class="role-choice__name">{{ copy.importReference }}</span>
      <span class="role-choice__line">{{ copy.importReferenceLine }}</span>
      <span class="role-choice__note">{{ copy.importReferenceNote }}</span>
    </label>
  </div>
</template>

<style scoped>
.role-choice {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.role-choice__item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.25rem;
  min-height: 9rem;
  padding: 1.15rem 1.2rem 1.25rem;
  border: 1px solid var(--line);
  border-left: 3px solid var(--line-strong);
  border-radius: var(--radius);
  background: var(--paper);
  cursor: pointer;
  text-align: left;
  transition: border-color 160ms ease, background-color 160ms ease;
}

.role-choice__item:hover {
  border-color: var(--line-strong);
  border-left-color: var(--ink-muted);
}

.role-choice__item.is-on {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.role-choice__item--ref.is-on {
  border-color: var(--ink);
  background: var(--paper);
}

.role-choice__item:focus-within {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.role-choice__name {
  font-family: var(--font-prose);
  font-size: 1.85rem;
  font-weight: 650;
  letter-spacing: -0.03em;
  line-height: 1.05;
  color: var(--ink);
}

.role-choice__item.is-on .role-choice__name {
  color: var(--accent);
}

.role-choice__item--ref.is-on .role-choice__name {
  color: var(--ink);
}

.role-choice__line {
  font-size: 0.95rem;
  font-weight: 650;
}

.role-choice__note {
  font-size: 0.84rem;
  line-height: 1.45;
  color: var(--ink-muted);
}

@media (max-width: 640px) {
  .role-choice {
    grid-template-columns: 1fr;
  }
}
</style>
