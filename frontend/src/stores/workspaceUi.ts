import { defineStore } from 'pinia'
import { ref } from 'vue'

/** Cross-tab UI memory inside a novel workspace (survives route leave/return with keep-alive). */
export const useWorkspaceUiStore = defineStore('workspaceUi', () => {
  const selectedOutlineItemId = ref<Record<number, number | null>>({})
  const outlineFilter = ref<Record<number, string>>({})
  const taskRoleFilter = ref<string>('all')
  const importDraft = ref<{
    role: 'manuscript' | 'reference'
    title: string
    text: string
  } | null>(null)

  function setSelectedItem(novelId: number, itemId: number | null) {
    selectedOutlineItemId.value = { ...selectedOutlineItemId.value, [novelId]: itemId }
  }

  function getSelectedItem(novelId: number): number | null {
    return selectedOutlineItemId.value[novelId] ?? null
  }

  function setOutlineFilter(novelId: number, q: string) {
    outlineFilter.value = { ...outlineFilter.value, [novelId]: q }
  }

  function getOutlineFilter(novelId: number): string {
    return outlineFilter.value[novelId] ?? ''
  }

  function rememberImportDraft(draft: {
    role: 'manuscript' | 'reference'
    title: string
    text: string
  }) {
    importDraft.value = draft
  }

  function clearImportDraft() {
    importDraft.value = null
  }

  return {
    selectedOutlineItemId,
    outlineFilter,
    taskRoleFilter,
    importDraft,
    setSelectedItem,
    getSelectedItem,
    setOutlineFilter,
    getOutlineFilter,
    rememberImportDraft,
    clearImportDraft,
  }
})
